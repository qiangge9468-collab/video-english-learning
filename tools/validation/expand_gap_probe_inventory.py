"""Expand fragmented VAD gaps to bounded complete word gaps, preserving r1."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/versions/v2.1.0'))
from speech_coverage import expand_to_word_gaps
from guarded_alignment import valid_span


def whole_gaps(inventory, words, maximum=14.):
    reliable = [w for w in words if valid_span(w) and w['end']-w['start'] <= 2.
                and not w.get('asr_timing_estimated')
                and w.get('alignment_status') != 'estimated_review_required']
    expanded = expand_to_word_gaps(inventory['uncovered_ranges'], reliable, inventory['duration'], max_seconds=maximum)
    result = []
    for a,b in expanded:
        while b-a > maximum:
            result.append([a,a+maximum])
            a += maximum
        if b > a:
            result.append([a,b])
    return result


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('alignment',type=Path)
    parser.add_argument('input',type=Path)
    parser.add_argument('output',type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve previous inventories')
    args.output.mkdir(parents=True)
    for item in read(args.manifest):
        name = item['name']
        parent = args.input/name/'inventory.json'
        inventory = read(parent)
        alignment = args.alignment/name/'alignment.json'
        if hashlib.sha256(alignment.read_bytes()).hexdigest() != inventory['alignment_sha256']:
            raise ValueError('Alignment changed since gap scan')
        gaps = whole_gaps(inventory,read(alignment)['words'])
        inventory.update(parent_inventory_sha256=hashlib.sha256(parent.read_bytes()).hexdigest(),
                         policy='bounded_complete_word_gaps_v1',expanded_ranges=gaps,
                         windows=[{'gap':[a,b],'clip':[max(0.,a-1.5),min(inventory['duration'],b+1.5)]} for a,b in gaps])
        target = args.output/name
        target.mkdir()
        (target/'inventory.json').write_text(json.dumps(inventory),encoding='utf-8')
        print(name,len(inventory['uncovered_ranges']),len(gaps),flush=True)


if __name__ == '__main__':
    main()
