"""Diagnose every uncovered speech range with a second local ASR, never insert it.

The first pass scans COMPLETE audio with VAD. The second recognizer can replay
the exact saved windows. No OCR, file-name vocabulary, or expected text is used.
Both recognizers agreeing remains review evidence, not ground truth.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/versions/v2.1.0'))
from guarded_alignment import valid_span
from run_parakeet_asr_experiment import token_words, digest


def uncovered(speech, words, duration, minimum=.35, maximum=8.):
    # A many-second/estimated word must not mask a whole missing utterance.
    cover = sorted((max(0., float(w['start'])-.1), min(duration, float(w['end'])+.1))
                   for w in words if valid_span(w) and float(w['end'])-float(w['start']) <= 2.
                   and not w.get('asr_timing_estimated')
                   and w.get('alignment_status') != 'estimated_review_required')
    gaps = []
    for first, last in speech:
        cursor, last = max(0., first), min(duration, last)
        for a,b in cover:
            if b <= cursor:
                continue
            if a >= last:
                break
            if a-cursor >= minimum:
                gaps.append([cursor, min(a, last)])
            cursor = max(cursor, min(last, b))
        if last-cursor >= minimum:
            gaps.append([cursor, last])
    result = []
    for a,b in gaps:
        while b-a > maximum:
            result.append([a,a+maximum])
            a += maximum
        if b-a >= minimum:
            result.append([a,b])
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('alignment', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--engine', choices=['parakeet', 'whisper'], required=True)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--windows-from', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Keep previous diagnostic outputs')
    from faster_whisper.audio import decode_audio
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    if args.engine == 'parakeet':
        import sherpa_onnx
        recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
            encoder=str(args.model/'encoder.int8.onnx'), decoder=str(args.model/'decoder.int8.onnx'),
            joiner=str(args.model/'joiner.int8.onnx'), tokens=str(args.model/'tokens.txt'),
            model_type='nemo_transducer', num_threads=4, provider='cpu')
    else:
        from faster_whisper import WhisperModel
        recognizer = WhisperModel(str(args.model), device='cuda', compute_type='int8_float16', local_files_only=True)
    args.output.mkdir(parents=True)
    summary = []
    for item in json.loads(args.manifest.read_text(encoding='utf-8-sig')):
        started = time.monotonic()
        name = item['name']
        target = args.output/name
        target.mkdir()
        audio = decode_audio(item['audio'], sampling_rate=16000)
        duration = len(audio)/16000
        audio_hash = digest(Path(item['audio']))
        alignment = args.alignment/name/'alignment.json'
        if args.windows_from:
            inventory = json.loads((args.windows_from/name/'inventory.json').read_text(encoding='utf-8'))
            if inventory['audio_sha256'] != audio_hash or inventory['alignment_sha256'] != digest(alignment):
                raise ValueError('Window replay input mismatch')
        else:
            words = json.loads(alignment.read_text(encoding='utf-8'))['words']
            vad = get_speech_timestamps(audio, VadOptions(threshold=.35, neg_threshold=.30,
                min_speech_duration_ms=80, min_silence_duration_ms=250, speech_pad_ms=200))
            speech = [[r['start']/16000,r['end']/16000] for r in vad]
            gaps = uncovered(speech, words, duration)
            inventory = {'audio_sha256': audio_hash, 'alignment_sha256': digest(alignment),
                         'duration': duration, 'speech_ranges': speech, 'uncovered_ranges': gaps,
                         'windows': [{'gap': [a,b], 'clip': [max(0.,a-1.5),min(duration,b+1.5)]} for a,b in gaps],
                         'scope': 'all_uncovered_ranges_from_complete_audio_vad', 'vad_is_not_ground_truth': True}
        (target/'inventory.json').write_text(json.dumps(inventory), encoding='utf-8')
        inside_count = 0
        with (target/'candidates.jsonl').open('w', encoding='utf-8') as log:
            for i,window in enumerate(inventory['windows']):
                a,b = window['clip']
                clip = audio[int(a*16000):int(b*16000)]
                if args.engine == 'parakeet':
                    stream = recognizer.create_stream()
                    stream.accept_waveform(16000, clip)
                    recognizer.decode_stream(stream)
                    raw = {k: getattr(stream.result,k) for k in ('text','tokens','timestamps','durations','ys_log_probs')}
                    member = token_words(raw)
                else:
                    result, _ = recognizer.transcribe(clip, language='en', beam_size=5, word_timestamps=True,
                        vad_filter=False, condition_on_previous_text=False, initial_prompt=None, temperature=0.)
                    raw, member = [], []
                    for s in result:
                        raw.append({'text':s.text, 'avg_logprob':s.avg_logprob, 'no_speech_prob':s.no_speech_prob})
                        member.extend({'text':w.word.strip(),'start':w.start,'end':w.end,'probability':w.probability} for w in s.words or [])
                member = [dict(w, start=float(w['start'])+a, end=float(w['end'])+a) for w in member]
                inside = [w for w in member if window['gap'][0] <= (w['start']+w['end'])/2 < window['gap'][1]]
                inside_count += len(inside)
                log.write(json.dumps({'index':i,'window':window,'raw':raw,'words':member,'inside_gap':inside,
                                     'inserted':False,'review_required':True})+'\n')
                log.flush()
                if i % 20 == 0:
                    print(f'{name} {args.engine}: {i+1}/{len(inventory["windows"])} gaps', flush=True)
        summary.append({'name':name,'engine':args.engine,'windows':len(inventory['windows']),
                        'inside_gap_candidate_words':inside_count,'inserted_words':0,'accuracy':None,
                        'release_allowed':False,'audio_sha256':audio_hash,'duration':duration,
                        'source_sha256':hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                        'elapsed_seconds':time.monotonic()-started})
        (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
        print(json.dumps(summary[-1]),flush=True)


if __name__ == '__main__':
    main()
