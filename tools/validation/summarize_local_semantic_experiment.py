"""Publish aggregate development evidence, never transcripts or a joint90 claim."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


EXPERIMENTS = (
    ('baseline', 'wespeaker-learning-online-r2', 'wespeaker-publisher-r2'),
    ('4b_indices', 'qwen-learning-online-r1', 'qwen-publisher-index-r1'),
    ('4b_partition', 'qwen-partition-online-r2', 'qwen-publisher-partition-r2'),
    ('4b_partition_consensus', 'qwen-consensus-online-r2', 'qwen-publisher-consensus-r2'),
    ('4b_unpunctuated', 'qwen-partition-online-r3', 'qwen-publisher-partition-r3'),
    ('4b_unpunctuated_consensus', 'qwen-consensus-online-r3', 'qwen-publisher-consensus-r3'),
    ('4b_examples', 'qwen-partition-online-r4', 'qwen-publisher-partition-r4'),
    ('4b_examples_consensus', 'qwen-consensus-online-r4', 'qwen-publisher-consensus-r4'),
    ('4b_decisions', 'qwen-decisions-online-r5', 'qwen-publisher-decisions-r5'),
    ('7b_partition', 'qwen25-partition-online-r6', 'qwen25-publisher-partition-r6'),
    ('7b_partition_consensus', 'qwen25-consensus-online-r6', 'qwen25-publisher-consensus-r6'),
    ('7b_decisions', 'qwen25-decisions-online-r7', 'qwen25-publisher-decisions-r7'),
)
COHORTS = (
    ('online', 'online-holdout-r1/manifest.json'),
    ('budget', 'punctuation-reserved-r4/manifest.json'),
    ('original', 'updated-cohort.json'),
)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def pooled_boundaries(rows):
    if not rows or len({r['name'] for r in rows}) != len(rows):
        raise ValueError('Missing or duplicated publisher reports')
    tp, predicted, expected = (sum(r[k] for r in rows) for k in
        ('correct_boundaries', 'predicted_boundaries', 'reference_boundaries'))
    if not 0 <= tp <= min(predicted, expected) or predicted + expected == 0:
        raise ValueError('Invalid boundary counts')
    return dict(correct=tp, predicted=predicted, reference=expected,
                micro_f1=2*tp/(predicted+expected))


def source_fields(unit):
    return {k: v for k, v in unit.items() if not k.startswith('translation')}


def translation_comparison(before, after):
    if len(before) != len(after) or not after or any(
            source_fields(a) != source_fields(b) for a, b in zip(before, after)):
        raise ValueError('Translation changed source units')
    return {
        'units': len(after),
        'before_statuses': dict(Counter(u['translation_status'] for u in before)),
        'after_statuses': dict(Counter(u['translation_status'] for u in after)),
        'source_preserved': True,
        'semantic_accuracy': None,
    }


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('validation', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    root = args.validation
    names = [v['name'] for v in read(root/'online-holdout-r1/manifest.json')]
    boundaries, translations = [], []
    for label, learning, evaluation in EXPERIMENTS:
        artifacts = {name: sha(root/learning/name/'learning.json') for name in names}
        report_path = root/evaluation/'summary.json'
        reports = read(report_path)
        if {r['name'] for r in reports} != {'new_champion', 'new_movement', 'new_thirty_days'}:
            raise ValueError('Incomplete publisher evaluation')
        boundaries.append(dict(method=label, complete_cached_transcripts=len(artifacts),
                               publisher_texts=len(reports), **pooled_boundaries(reports),
                               evaluation_sha256=sha(report_path), learning_sha256=artifacts))
    for cohort, manifest in COHORTS:
        integrity = {r['name']: r for r in read(root/f'qwen-final-integrity-{cohort}-r4/summary.json')}
        for video in read(root/manifest):
            name = video['name']
            old = root/f'wespeaker-translation-{cohort}-r2'/name/'bilingual.json'
            new = root/f'qwen-context-final-{cohort}-r3'/name/'bilingual.json'
            if integrity[name].get('integrity_passed') is not True:
                raise ValueError('Failed full-pipeline integrity')
            translations.append(dict(name=name, **translation_comparison(read(old), read(new)),
                                     before_sha256=sha(old), after_sha256=sha(new), integrity_passed=True))
    before_totals, after_totals = Counter(), Counter()
    for row in translations:
        before_totals.update(row['before_statuses'])
        after_totals.update(row['after_statuses'])
    result = dict(
        date='2026-10-08', scope='development_full_cached_transcripts_not_new_audio_listening',
        joint_accuracy=None, release_allowed=False,
        limitation='No complete independent joint reference or four untouched full-video passes.',
        boundaries=boundaries,
        translation=dict(videos=len(translations), units=sum(r['units'] for r in translations),
                         before_statuses=dict(before_totals), after_statuses=dict(after_totals),
                         semantic_accuracy=None, rows=translations),
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('x', encoding='utf-8') as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
        handle.write('\n')
    print(json.dumps({'videos': len(translations), 'units': result['translation']['units'],
                      'boundary_variants': len(boundaries)-1, 'release_allowed': False}))


if __name__ == '__main__':
    main()
