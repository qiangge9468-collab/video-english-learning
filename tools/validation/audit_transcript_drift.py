"""Whole-transcript timestamp disagreement audit; neither decode is ground truth.

Match phrases unique in BOTH complete transcripts. Repeated phrases are skipped,
not deduplicated or moved. Flag consistent multiword shifts for review only.
No audio, source words or service cache is rewritten. Absence of anchors is not
a pass. This is a diagnostic, not a calibrated accuracy or release gate.
"""
import argparse
from collections import defaultdict
import hashlib
import json
import math
from pathlib import Path
import re
import statistics


def lexical_words(words):
    result = []
    for index, word in enumerate(words):
        start, end = float(word['start']), float(word['end'])
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end < start:
            raise ValueError('Invalid word span')
        for token in re.findall(r"[a-z]+(?:'[a-z]+)?|\d+", word['text'].lower().replace('’', "'")):
            result.append({'text': token, 'start': start, 'end': end, 'word_index': index})
    return result


def phrases(words, width):
    result = defaultdict(list)
    for i in range(len(words)-width+1):
        result[tuple(w['text'] for w in words[i:i+width])].append(i)
    return result


def audit(primary, comparison, width=5, threshold=3.):
    if width < 3 or not math.isfinite(threshold) or threshold <= 0:
        raise ValueError('Invalid diagnostic settings')
    left, right = lexical_words(primary), lexical_words(comparison)
    left_phrases, right_phrases = phrases(left, width), phrases(right, width)
    matched, ambiguous, flags = 0, 0, []
    for phrase, indexes in left_phrases.items():
        other = right_phrases.get(phrase, [])
        if not other:
            continue
        if len(indexes) != 1 or len(other) != 1:
            ambiguous += 1
            continue
        a, b = indexes[0], other[0]
        matched += 1
        deltas = [(right[b+i]['start']+right[b+i]['end']-
                   left[a+i]['start']-left[a+i]['end'])/2 for i in range(width)]
        # Every token must disagree in the same direction. A single odd word
        # or low-score token cannot move an entire sentence.
        if not (min(deltas) > threshold or max(deltas) < -threshold):
            continue
        flags.append({'phrase': ' '.join(phrase),
                      'primary_word_start': left[a]['word_index'],
                      'primary_word_end': left[a+width-1]['word_index']+1,
                      'comparison_word_start': right[b]['word_index'],
                      'comparison_word_end': right[b+width-1]['word_index']+1,
                      'primary_start': left[a]['start'], 'comparison_start': right[b]['start'],
                      'median_delta_seconds': statistics.median(deltas),
                      'delta_spread_seconds': max(deltas)-min(deltas)})
    flagged_words = {i for flag in flags for i in range(flag['primary_word_start'], flag['primary_word_end'])}
    return {'status': 'review_required' if flags else 'no_large_disagreement_found' if matched else 'insufficient_overlap',
            'scope': 'two_complete_transcripts_not_independent_truth',
            'primary_words': len(primary), 'comparison_words': len(comparison),
            'unique_phrase_anchors': matched, 'ambiguous_phrase_keys_skipped': ambiguous,
            'flagged_phrase_anchors': len(flags), 'flagged_primary_words': len(flagged_words),
            'threshold_seconds': threshold, 'phrase_tokens': width, 'flags': flags,
            'accuracy': None, 'release_allowed': False}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('alignment', type=Path)
    parser.add_argument('comparison', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve earlier audits')
    reports = []
    for item in json.loads(args.manifest.read_text(encoding='utf-8-sig')):
        primary = args.alignment/item['name']/'alignment.json'
        comparison = args.comparison/item['name']/'asr.json'
        report = audit(json.loads(primary.read_text(encoding='utf-8'))['words'],
                       json.loads(comparison.read_text(encoding='utf-8'))['words'])
        reports.append({'name': item['name'], **report,
                        'primary_sha256': hashlib.sha256(primary.read_bytes()).hexdigest(),
                        'comparison_sha256': hashlib.sha256(comparison.read_bytes()).hexdigest()})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding='utf-8')
    for report in reports:
        print(json.dumps({k:v for k,v in report.items() if k != 'flags'}))


if __name__ == '__main__':
    main()
