"""Full WhisperX ASR comparison, not merely re-aligning old erroneous segments.

Uses the installed WhisperX pipeline with offline Silero ONNX from faster-whisper.
Preserves real-time chunks, does not suppress numerals, never uses OCR prompts.
Raw words have NO estimated timestamps: alignment must supply or flag them later.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import sys
import time
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/versions/v2.1.0'))
from acoustic_chunks import merge_speech


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Keep prior experiments')
    os.environ['PATH'] = os.pathsep.join([str(Path(sys.prefix)/'Library/bin'), os.environ.get('PATH', '')])
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    import torch
    from faster_whisper.vad import VadOptions, get_speech_timestamps
    from whisperx.vads.vad import Vad
    import whisperx
    vad_settings = dict(threshold=.35, neg_threshold=.30, min_speech_duration_ms=80,
                        min_silence_duration_ms=300, speech_pad_ms=200, max_speech_duration_s=20)

    class OfflineSilero(Vad):
        def __init__(self):
            super().__init__(.35)
            self.ranges = []

        @staticmethod
        def preprocess_audio(audio):
            return audio

        def __call__(self, audio):
            if audio['sample_rate'] != 16000:
                raise ValueError('16kHz audio required')
            ranges = get_speech_timestamps(audio['waveform'], VadOptions(**vad_settings))
            self.ranges = [(r['start']/16000, r['end']/16000) for r in ranges]
            return [SimpleNamespace(start=a, end=b) for a,b in self.ranges]

        @staticmethod
        def merge_chunks(segments, chunk_size, **kwargs):
            return merge_speech([(s.start, s.end) for s in segments], maximum=chunk_size, max_pause=1.)

    vad = OfflineSilero()
    model = whisperx.load_model(args.model, 'cuda', compute_type='int8_float16', language='en',
        vad_model=vad, local_files_only=True,
        asr_options={'without_timestamps': True, 'word_timestamps': False,
                     'suppress_numerals': False, 'initial_prompt': None, 'hotwords': None})
    args.output.mkdir(parents=True)
    reports, manifest = [], []
    sources = [Path(__file__), ROOT/'tools/versions/v2.1.0/acoustic_chunks.py']
    source_hashes = {str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in sources}
    for item in json.loads(args.manifest.read_text(encoding='utf-8-sig')):
        target = args.output/item['name']
        target.mkdir()
        audio = whisperx.load_audio(item['audio'])
        audio_hash = hashlib.sha256(Path(item['audio']).read_bytes()).hexdigest()
        (target/'input.json').write_text(json.dumps({'audio_sha256': audio_hash,
            'duration': len(audio)/16000, 'source_sha256': source_hashes,
            'vad_settings': vad_settings, 'model': args.model}), encoding='utf-8')
        print(f"START {item['name']}: {len(audio)/16000:.1f}s", flush=True)
        started = time.monotonic()
        result = model.transcribe(audio, batch_size=2, language='en', chunk_size=20, print_progress=True)
        segments = [dict(s, id=i, start=float(s['start']), end=float(s['end']),
                         avg_logprob=float(s['avg_logprob']) if s.get('avg_logprob') is not None else None)
                    for i,s in enumerate(result['segments']) if s['text'].strip()]
        report = {'name': item['name'], 'duration': len(audio)/16000, 'segment_count': len(segments),
                  'token_count': sum(len(s['text'].split()) for s in segments),
                  'vad_settings': vad_settings, 'max_pause_seconds': 1, 'batch_size': 2,
                  'device': 'cuda', 'compute_type': 'int8_float16', 'model': args.model,
                  'without_timestamps': True, 'scope': 'complete_audio', 'words_require_alignment': True,
                  'elapsed_seconds': time.monotonic()-started, 'accuracy': None, 'release_allowed': False,
                  'source_sha256': source_hashes, 'audio_sha256': audio_hash}
        for filename, data in [('whisper_segments.json', segments), ('whisper_words.json', []),
                               ('vad_ranges.json', vad.ranges), ('asr.json', {'segments': segments, 'words': [], 'report': report})]:
            (target/filename).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        reports.append(report)
        manifest.append({**item, 'baseline_cache': item['cache'], 'cache': str(target.resolve())})
        (args.output/'summary.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
        (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
