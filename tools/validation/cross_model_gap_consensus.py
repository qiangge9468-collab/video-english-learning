"""Conservative cross-ASR gap agreement report; no automatic transcript insertion."""
import argparse
from collections import Counter
from difflib import SequenceMatcher
import json
from pathlib import Path
import re


def token(word):
    return re.sub(r'[^a-z0-9\']+', '', word['text'].lower())


def consensus(first, second, baseline, tolerance=.75, minimum_run=2):
    if first['window'] != second['window'] or first['index'] != second['index']:
        raise ValueError('Different windows cannot be used as independent agreement')
    left, right = first['inside_gap'], second['inside_gap']
    matcher = SequenceMatcher(None, [token(w) for w in left], [token(w) for w in right], autojunk=False)
    proposals, rejected = [], []
    for match in matcher.get_matching_blocks():
        run = []
        def flush():
            if len(run) >= minimum_run:
                proposals.extend(run)
            else:
                rejected.extend(dict(r,reason='insufficient_contiguous_agreement') for r in run)
            run.clear()
        for i in range(match.size):
            a,b = left[match.a+i], right[match.b+i]
            record = {'text':b['text'],'start':b['start'],'end':b['end'],
                      'peer_start':a['start'],'peer_end':a['end'],
                      'window_index':first['index'],'review_required':True,'inserted':False}
            reason = None
            if not token(a):
                reason = 'empty_normalized_token'
            elif not all(0 < w['end']-w['start'] <= 1.5 for w in (a,b)):
                reason = 'unreliable_word_duration'
            elif abs((a['start']+a['end']-b['start']-b['end'])/2) > tolerance:
                reason = 'time_disagreement'
            elif b.get('probability',0) < .5:
                reason = 'low_whisper_probability'
            elif any(min(b['end'], w['end'])-max(b['start'],w['start']) > .15 for w in baseline):
                reason = 'overlaps_existing_word'
            if reason:
                flush()
                rejected.append(dict(record,reason=reason))
            else:
                if run and (b['start'] < run[-1]['end']-.08 or b['start']-run[-1]['end'] > 1.):
                    flush()
                run.append(record)
        flush()
    return proposals, rejected


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('alignment', type=Path)
    parser.add_argument('parakeet', type=Path)
    parser.add_argument('whisper', type=Path)
    parser.add_argument('output', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Keep earlier evidence')
    args.output.mkdir(parents=True)
    reports = []
    for item in read(args.manifest):
        name = item['name']
        if read(args.parakeet/name/'inventory.json') != read(args.whisper/name/'inventory.json'):
            raise ValueError('Input inventories differ')
        left = [json.loads(line) for line in (args.parakeet/name/'candidates.jsonl').read_text(encoding='utf-8').splitlines()]
        right = [json.loads(line) for line in (args.whisper/name/'candidates.jsonl').read_text(encoding='utf-8').splitlines()]
        if len(left) != len(right):
            raise ValueError('Incomplete whole-gap comparison')
        words = read(args.alignment/name/'alignment.json')['words']
        proposals, rejected = [], []
        for a,b in zip(left,right):
            accepted, denied = consensus(a,b,words)
            proposals.extend(accepted)
            rejected.extend(denied)
        # Only collapse the SAME token/time found in DIFFERENT context windows;
        # successive repetitions from a single utterance must survive.
        unique = []
        for p in sorted(proposals,key=lambda p:(p['start'],p['end'],p['window_index'])):
            if any(token(p)==token(q) and abs(p['start']-q['start']) <= .2
                   and p['window_index'] != q['window_index'] for q in unique):
                rejected.append(dict(p,reason='duplicate_context_evidence'))
            else:
                unique.append(p)
        report = {'name':name,'windows_compared':len(left),'agreement_candidate_words':len(unique),
                  'inserted_words':0,'rejection_counts':dict(Counter(r['reason'] for r in rejected)),
                  'accuracy':None,'release_allowed':False,'scope':'all_saved_full_audio_gaps'}
        (args.output/(name+'.json')).write_text(json.dumps({'report':report,'proposals':unique,'rejected':rejected},
            ensure_ascii=False,indent=2),encoding='utf-8')
        reports.append(report)
        print(json.dumps(report),flush=True)
    (args.output/'summary.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
