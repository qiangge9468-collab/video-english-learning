"""Whole-file exact hard-caption anchors; display times are NOT speech truth.

Unmatched and ambiguous captions remain in the report. Only phrases unique in
both full texts become timing anchors. Never moves words, prompts ASR, or grants
release based on another imperfect automatic system.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
import math
from pathlib import Path

from audit_transcript_drift import lexical_words
from compare_ocr_proposals import proposals, tokens


def audit(cues, words, minimum_tokens=4, tolerance_seconds=2.):
    if minimum_tokens < 3 or not math.isfinite(tolerance_seconds) or tolerance_seconds < 0:
        raise ValueError('Invalid anchor policy')
    transcript = lexical_words(words)
    keys = [tuple(tokens(c['text'])) for c in cues]
    occurrences = Counter(keys)
    by_width = {}
    for width in {len(k) for k in keys if len(k) >= minimum_tokens}:
        table = defaultdict(list)
        for i in range(len(transcript)-width+1):
            table[tuple(w['text'] for w in transcript[i:i+width])].append(i)
        by_width[width] = table
    rows = []
    for cue, key in zip(cues, keys):
        start, end = float(cue['start']), float(cue['end'])
        if not math.isfinite(start+end) or start < 0 or end <= start:
            raise ValueError('Invalid OCR display range')
        row = dict(cue, timing_reference='unreviewed_display_not_speech', release_allowed=False)
        if len(key) < minimum_tokens:
            row['status'] = 'insufficient_text'
        else:
            matches = by_width[len(key)].get(key, [])
            if not matches:
                row['status'] = 'no_exact_match'
            elif occurrences[key] != 1 or len(matches) != 1:
                row['status'] = 'ambiguous_repetition'
            else:
                first, last = matches[0], matches[0]+len(key)-1
                a, b = transcript[first]['start'], transcript[last]['end']
                distance = max(start-b, a-end, 0.)
                row.update(status='large_display_disagreement' if distance > tolerance_seconds else 'anchor_found',
                           word_start=transcript[first]['word_index'], word_end=transcript[last]['word_index']+1,
                           candidate_start=a, candidate_end=b,
                           onset_delta_from_display=a-start, offset_delta_from_display=b-end,
                           nonoverlap_distance_seconds=distance)
        rows.append(row)
    counts = dict(Counter(r['status'] for r in rows))
    return {'scope': 'whole_transcript_unreviewed_display_anchors', 'cue_count': len(cues),
            'word_count': len(words), 'minimum_tokens': minimum_tokens,
            'tolerance_seconds': tolerance_seconds, 'counts': counts, 'items': rows,
            'speech_timing_accuracy': None, 'text_accuracy': None, 'release_allowed': False}


def read(path):
    return path and json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--format', choices=('asr', 'alignment'), default='alignment')
    parser.add_argument('--ocr-root', type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve prior audits')
    args.output.mkdir(parents=True)
    summary = []
    for item in read(args.manifest):
        name = item['name']
        candidate = args.candidate/name/(args.format+'.json')
        words = read(candidate)['words']
        folder = args.ocr_root/('updated-ocr-'+name)
        if folder.exists():
            if not read(folder/'extraction.json')['complete_video_reference']:
                raise ValueError('Partial OCR cannot be reported as complete')
            result = audit(proposals(folder, item.get('ocr_min_y', 0)), words)
        else:
            result = {'reference_status': 'no_complete_ocr_reference', 'speech_timing_accuracy': None,
                      'text_accuracy': None, 'release_allowed': False}
        result['name'] = name
        result['candidate_sha256'] = hashlib.sha256(candidate.read_bytes()).hexdigest()
        (args.output/(name+'.json')).write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
        summary.append({k:v for k,v in result.items() if k != 'items'})
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')
    print(json.dumps(summary, indent=2))


if __name__ == '__main__':
    main()
