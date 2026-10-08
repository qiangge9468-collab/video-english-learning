"""Audit all pipeline output tokens and ranges. Integrity is NOT speech accuracy."""
import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/versions/v2.1.0'))
from semantic_caption_segmenter_v206 import normalize_words,words_to_text


def translation_directory(pipeline, learning_override=None, translation_override=None):
    # A new segmentation must never be silently paired with stale translations
    # from a different experiment just because that directory happens to exist.
    if translation_override is not None:
        return translation_override
    return learning_override if learning_override is not None else pipeline/'translation'


def audit(source, alignment, learning, bilingual=None, max_gap=4.):
    words = alignment['words']
    normalized = normalize_words(words)
    expected = {(sid,i): t for sid,s in enumerate(source['segments']) for i,t in enumerate(s['text'].split())}
    actual = [(w['source_segment_id'], w['source_token_index']) for w in words]
    wrong = [k for k,w in zip(actual,words) if expected.get(k) != w['text']]
    groups = defaultdict(list)
    for w in words:
        groups[w['source_segment_id']].append(w['source_token_index'])
    inversions = [sid for sid,indexes in groups.items() if indexes != sorted(indexes)]
    covered, gaps, invalid_ranges, changed_learning_text, changed_learning_time = [], [], [], [], []
    for i,s in enumerate(learning):
        a,b = s['word_start'],s['word_end']
        if not (0 <= a < b <= len(words)):
            invalid_ranges.append(i)
            continue
        covered.extend(range(a,b))
        selected = normalized[a:b]
        if len(normalized) != len(words) or s.get('text') != words_to_text(selected):
            changed_learning_text.append(i)
        expected_start = selected[0]['start'] if selected else None
        expected_end = max(w['end'] for w in selected) if selected else None
        def matches_time(actual, expected):
            return (type(actual) in (int,float) and math.isfinite(actual)
                    and expected is not None and abs(actual-expected) <= 1e-6)
        if not matches_time(s.get('start'),expected_start) or not matches_time(s.get('end'),expected_end):
            changed_learning_time.append(i)
        for left,right in zip(words[a:b],words[a+1:b]):
            gap = right['start']-left['end']
            if gap >= max_gap:
                gaps.append({'learning_sentence':i,'left_word':left['index'],'gap':gap})
    report = {'source_tokens':len(expected),'output_tokens':len(words),
              'missing_source_tokens':len(set(expected)-set(actual)),
              'duplicate_source_tokens':len(actual)-len(set(actual)),
              'changed_source_tokens':len(wrong),'source_order_inversion_segments':inversions,
              'learning_units':len(learning),'invalid_learning_ranges':invalid_ranges,
              'learning_text_not_matching_word_range':changed_learning_text,
              'learning_time_not_matching_word_range':changed_learning_time,
              'learning_exactly_partitions_words':covered == list(range(len(words))),
              'learning_units_crossing_long_word_gap':gaps,
              'alignment_status_counts':dict(Counter(w.get('alignment_status','unknown') for w in words)),
              'translation_available':bilingual is not None,
              'independent_accuracy':None,'release_allowed':False}
    if bilingual is not None:
        report['translation_preserves_learning_inputs'] = (
            len(bilingual) == len(learning) and all(
                all(a.get(k) == b.get(k) for k in ('text','start','end','word_start','word_end'))
                for a,b in zip(learning,bilingual)))
        report['translation_status_counts'] = dict(Counter(s.get('translation_status','missing') for s in bilingual))
    report['integrity_passed'] = not any([report['missing_source_tokens'], report['duplicate_source_tokens'],
        report['changed_source_tokens'], inversions, invalid_ranges, gaps,changed_learning_text,
        changed_learning_time]) and report['learning_exactly_partitions_words']
    if bilingual is not None:
        report['integrity_passed'] &= report['translation_preserves_learning_inputs']
    return report


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('pipeline', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--learning-root',type=Path)
    parser.add_argument('--translation-root',type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Keep earlier audits')
    args.output.mkdir(parents=True)
    reports = []
    for item in read(args.manifest):
        name = item['name']
        root = args.pipeline
        learning_root = args.learning_root or root/'learning'
        translation_root = translation_directory(root,args.learning_root,args.translation_root)
        bilingual = translation_root/name/'bilingual.json'
        result = audit(read(root/'alignment'/name/'input.json'), read(root/'alignment'/name/'alignment.json'),
                       read(learning_root/name/'learning.json'), read(bilingual) if bilingual.exists() else None)
        result.update(name=name,scope='all_tokens_and_all_learning_units')
        reports.append(result)
        print(json.dumps(result),flush=True)
    (args.output/'summary.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')
    if not reports or not all(r['integrity_passed'] for r in reports):
        sys.exit(2)


if __name__ == '__main__':
    main()
