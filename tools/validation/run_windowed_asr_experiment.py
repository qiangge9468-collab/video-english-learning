"""Decode complete audio on an absolute-clock grid, retain every raw window.

No source cache or video is changed. No OCR or expected text is a model prompt.
Exports cache-shaped artifacts for the same full alignment/learning pipeline.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/versions/v2.1.0'))
from windowed_asr import audio_windows, owned_words


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', required=True)
    parser.add_argument('--reuse-raw', type=Path, help='Reuse complete raw window logs after an export-only failure; provenance retained')
    parser.add_argument('--export-only', action='store_true', help='Replay complete saved raw logs without loading/running ASR')
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Choose a fresh experiment directory')
    os.environ['PATH'] = os.pathsep.join([str(Path(sys.prefix)/'Library/bin'), os.environ.get('PATH', '')])
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import torch
    from faster_whisper import WhisperModel
    from faster_whisper.audio import decode_audio
    if args.export_only and not args.reuse_raw:
        raise ValueError('Export-only requires retained raw logs')
    model = None if args.export_only else WhisperModel(args.model, device='cuda', compute_type='int8_float16', local_files_only=True)
    args.output.mkdir(parents=True)
    sources = [Path(__file__), ROOT/'tools/versions/v2.1.0/windowed_asr.py']
    options = dict(language='en', beam_size=5, word_timestamps=True, vad_filter=False,
                   condition_on_previous_text=False, initial_prompt=None,
                   temperature=[0., .2, .4, .6, .8, 1.])
    reports, manifest = [], []
    for item in json.loads(args.manifest.read_text(encoding='utf-8-sig')):
        target = args.output/item['name']
        target.mkdir()
        audio = decode_audio(item['audio'], sampling_rate=16000)
        windows = list(audio_windows(len(audio)))
        reused, raw_path = [], None
        if args.reuse_raw:
            raw_path = args.reuse_raw/item['name']/'windows.jsonl'
            if raw_path.exists():
                reused = [json.loads(line) for line in raw_path.read_text(encoding='utf-8').splitlines()]
                if [row['window'] for row in reused] != windows:
                    raise ValueError('Reused raw log must exactly cover the complete audio grid')
        if args.export_only and not reused:
            raise ValueError('Missing complete raw log for export-only replay')
        started = time.monotonic()
        segments, words, rejected = [], [], []
        print(f"START {item['name']}: {len(audio)/16000:.2f}s, {len(windows)} complete-audio windows", flush=True)
        with (target/'windows.jsonl').open('w', encoding='utf-8') as log:
            for window in windows:
                if reused:
                    raw = reused[window['index']]['raw']
                else:
                    stream, _ = model.transcribe(audio[window['clip_start_sample']:window['clip_end_sample']], **options)
                    raw = [{'text': p.text.strip(), 'start': p.start, 'end': p.end,
                            'avg_logprob': p.avg_logprob, 'no_speech_prob': p.no_speech_prob,
                            'compression_ratio': p.compression_ratio, 'temperature': p.temperature,
                            'words': [{'text': w.word.strip(), 'start': w.start, 'end': w.end,
                                       'probability': w.probability} for w in p.words or []]} for p in stream]
                new_segments, new_words, issues = owned_words(raw, window, len(segments), len(words))
                log.write(json.dumps({'window': window, 'raw': raw, 'issues': issues})+'\n')
                log.flush()
                segments.extend(new_segments)
                words.extend(new_words)
                rejected.extend({'window_index': window['index'], **issue} for issue in issues)
                if window['index'] % 10 == 0:
                    print(f"{item['name']}: {window['core_end']:.0f}/{len(audio)/16000:.0f}s", flush=True)
        report = {'name': item['name'], 'scope': 'complete_audio', 'duration': len(audio)/16000,
                  'windows': len(windows), 'core_seconds': 20, 'context_seconds': 4,
                  'options': options, 'word_count': len(words), 'segment_count': len(segments),
                  'rejected_invalid_words': len(rejected), 'boundary_review_words': sum(w['boundary_review_required'] for w in words),
                  'zero_duration_words_retained_for_alignment': sum(w['asr_timing_estimated'] for w in words),
                  'model_inference_executed': not bool(reused),
                  'elapsed_seconds': time.monotonic()-started, 'accuracy': None, 'release_allowed': False,
                  'reused_raw_log': str(raw_path.resolve()) if reused else None,
                  'reused_raw_sha256': hashlib.sha256(raw_path.read_bytes()).hexdigest() if reused else None,
                  'source_sha256': {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}}
        for filename, data in [('asr.json', {'words': words, 'segments': segments, 'report': report}),
                               ('whisper_words.json', words), ('whisper_segments.json', segments),
                               ('rejected.json', rejected)]:
            (target/filename).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        reports.append(report)
        manifest.append({**item, 'baseline_cache': item['cache'], 'cache': str(target.resolve())})
        (args.output/'summary.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
        (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
