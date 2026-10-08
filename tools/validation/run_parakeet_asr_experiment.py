"""Independent local Parakeet-TDT ONNX full-audio comparison (never a gold label).

Runs on CPU in an isolated optional dependency directory. Every audio sample
belongs to a 20-second core with 4-second context, with raw outputs retained.
No OCR, video-title prompts, transcript rewrites, or production cache writes.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path
import re
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/versions/v2.1.0'))
from windowed_asr import audio_windows, owned_words


def token_words(result):
    """Map emitted BPE pieces to words without inventing phoneme boundaries."""
    pieces, starts, durations = result['tokens'], result['timestamps'], result['durations']
    if len(pieces) != len(starts) or len(pieces) != len(durations):
        raise ValueError('Missing TDT token timing')
    text = ''.join(pieces)
    # sherpa's display formatter can remove a space before currency signs
    # ("extra $2" -> "extra$2"). Keep the original BPE word boundaries; accept
    # whitespace-only formatting differences, never altered lexical content.
    if re.sub(r'\s+', '', text) != re.sub(r'\s+', '', result['text']):
        raise ValueError('Decoded text differs from the retained token stream')
    spans, offset = [], 0
    for token, start, duration in zip(pieces, starts, durations):
        if not math.isfinite(start+duration) or start < 0 or duration < 0:
            raise ValueError('Invalid TDT token time')
        spans.append((offset, offset+len(token), float(start), float(start+duration)))
        offset += len(token)
    words = []
    for match in re.finditer(r'\S+', text):
        members = [s for s in spans if s[0] < match.end() and s[1] > match.start()]
        words.append({'text': match.group(), 'start': min(s[2] for s in members),
                      'end': max(s[3] for s in members), 'aligned_by': 'parakeet_tdt',
                      'timing_source': 'tdt_token_spans_not_forced_alignment'})
    return words


def phrase_parts(words):
    """Keep forced-alignment windows local; final learning sentences are separate."""
    parts, current = [], []
    for word in words:
        if current and word['start']-current[-1]['end'] > .75:
            parts.append({'words': current})
            current = []
        current.append(word)
        if re.search(r'[.!?][\"\'\)]*$', word['text']):
            parts.append({'words': current})
            current = []
    if current:
        parts.append({'words': current})
    return parts


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(4*1024*1024), b''):
            h.update(block)
    return h.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--threads', type=int, default=4)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve prior experiment outputs')
    import sherpa_onnx
    from faster_whisper.audio import decode_audio
    model = args.model
    model_hashes = {p.name: digest(p) for p in sorted(model.glob('*.onnx'))}
    model_hashes['tokens.txt'] = digest(model/'tokens.txt')
    recognizer = sherpa_onnx.OfflineRecognizer.from_transducer(
        encoder=str(model/'encoder.int8.onnx'), decoder=str(model/'decoder.int8.onnx'),
        joiner=str(model/'joiner.int8.onnx'), tokens=str(model/'tokens.txt'),
        model_type='nemo_transducer', num_threads=args.threads, provider='cpu')
    args.output.mkdir(parents=True)
    sources = [Path(__file__), ROOT/'tools/versions/v2.1.0/windowed_asr.py']
    source_hashes = {str(p.relative_to(ROOT)): digest(p) for p in sources}
    reports, manifest = [], []
    for item in json.loads(args.manifest.read_text(encoding='utf-8-sig')):
        started = time.monotonic()
        target = args.output/item['name']
        target.mkdir()
        audio = decode_audio(item['audio'], sampling_rate=16000)
        audio_sha = digest(Path(item['audio']))
        windows = list(audio_windows(len(audio)))
        (target/'input.json').write_text(json.dumps({'audio_sha256': audio_sha, 'duration': len(audio)/16000,
            'model_sha256': model_hashes, 'source_sha256': source_hashes}), encoding='utf-8')
        words, segments, issues = [], [], []
        print(f"START {item['name']}: {len(audio)/16000:.1f}s, {len(windows)} windows", flush=True)
        with (target/'windows.jsonl').open('w', encoding='utf-8') as log:
            for window in windows:
                stream = recognizer.create_stream()
                stream.accept_waveform(16000, audio[window['clip_start_sample']:window['clip_end_sample']])
                recognizer.decode_stream(stream)
                result = stream.result
                raw = {name: getattr(result, name) for name in ('text', 'tokens', 'timestamps', 'durations', 'ys_log_probs')}
                log.write(json.dumps({'window': window, 'raw': raw,
                    'display_spacing_differs': ''.join(raw['tokens']).strip() != raw['text'].strip()})+'\n')
                log.flush()
                member = token_words(raw)
                new_segments, new_words, rejected = owned_words(phrase_parts(member), window, len(segments), len(words))
                segments.extend(new_segments)
                words.extend(new_words)
                issues.extend({'window_index': window['index'], **r} for r in rejected)
                if window['index'] % 10 == 0:
                    print(f"{item['name']}: {window['core_end']:.0f}/{len(audio)/16000:.0f}s", flush=True)
        report = {'name': item['name'], 'duration': len(audio)/16000, 'scope': 'complete_audio',
                  'model': 'parakeet-tdt-0.6b-v2-int8', 'runtime': sherpa_onnx.__version__, 'provider': 'cpu',
                  'threads': args.threads, 'core_seconds': 20, 'context_seconds': 4,
                  'windows': len(windows), 'word_count': len(words), 'segment_count': len(segments),
                  'rejected_invalid_words': len(issues),
                  'boundary_review_words': sum(w['boundary_review_required'] for w in words),
                  'elapsed_seconds': time.monotonic()-started, 'audio_sha256': audio_sha,
                  'model_sha256': model_hashes, 'source_sha256': source_hashes,
                  'accuracy': None, 'release_allowed': False}
        for name, data in [('asr.json', {'segments': segments, 'words': words, 'report': report}),
                           ('whisper_segments.json', segments), ('whisper_words.json', words), ('rejected.json', issues)]:
            (target/name).write_text(json.dumps(data, ensure_ascii=False), encoding='utf-8')
        reports.append(report)
        manifest.append({**item, 'baseline_cache': item['cache'], 'cache': str(target.resolve())})
        (args.output/'summary.json').write_text(json.dumps(reports, indent=2), encoding='utf-8')
        (args.output/'manifest.json').write_text(json.dumps(manifest, indent=2), encoding='utf-8')
        print(json.dumps(report), flush=True)


if __name__ == '__main__':
    main()
