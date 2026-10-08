"""Combine cached whole-transcript semantic proposals with independent evidence.

This does not consult evaluation references, nor rerun audio recognition.
"""
import argparse
from dataclasses import asdict
from pathlib import Path
from run_local_semantic_boundaries import (
    read, save, digest, normalize_words, BoundaryFeatures, SegmenterConfig,
    choose_cuts, units_for_cuts,
)


def consensus_cuts(words, features, config, old_cuts, proposals, failed_ranges=()):
    cuts,guards = choose_cuts(words,features,config,proposals)
    cuts = set(cuts)
    restored, rejected_additions = [], []
    for i in old_cuts:
        if not 0 < i < len(words):
            continue
        f = features[i]
        # Never discard an acoustically supported turn or a boundary on which
        # two independent text models strongly agree solely on one LLM vote.
        if (config.learning_speaker_boundaries and f.acoustic_speaker_change
                or f.sat_probability >= .9 and (f.restored_terminal_probability or 0) >= .8):
            if i not in cuts:
                restored.append(i)
            cuts.add(i)
    for i in sorted(cuts-set(old_cuts)-{0,len(words)}):
        f = features[i]
        if not (f.forced_silence or f.gap >= .4 or f.acoustic_speaker_change
                or f.sat_probability >= .1 or (f.restored_terminal_probability or 0) >= .3
                or i in guards['safety_cuts']):
            cuts.remove(i)
            rejected_additions.append(i)
    for a,b in failed_ranges:
        cuts = {i for i in cuts if not a < i <= b}|{i for i in old_cuts if a < i <= b}
    guards.update(restored_independent_consensus=restored,rejected_unsupported_additions=rejected_additions)
    return sorted(cuts),guards


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','alignment','baseline','proposals','output'):
        p.add_argument(name,type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    summaries = []
    for item in read(args.manifest):
        name = item['name']
        aligned = args.alignment/name/'alignment.json'
        words = normalize_words(read(aligned)['words'])
        debug = read(args.baseline/name/'debug.json')
        proposed_debug = read(args.proposals/name/'debug.json')
        if proposed_debug['alignment_sha256'] != digest(aligned):
            raise ValueError('Wrong source alignment')
        config = SegmenterConfig(**debug['config'])
        features = [BoundaryFeatures(index=0)]+[BoundaryFeatures(**b) for b in debug['boundaries']]+[BoundaryFeatures(index=len(words))]
        old = {s['word_end'] for s in read(args.baseline/name/'learning.json')}
        failed_ranges = []
        for fail in proposed_debug['failures']:
            a,b = read(args.proposals/name/f"response-{fail['window']:03d}.json")['owned']
            failed_ranges.append((a-1,b))
        cuts,guards = consensus_cuts(words,features,config,old,proposed_debug['proposed_cuts'],failed_ranges)
        result = units_for_cuts(words,features,config,cuts)
        dest = args.output/name
        dest.mkdir()
        save(dest/'learning.json',result)
        save(dest/'debug.json',{'config':asdict(config),'boundaries':debug['boundaries'],'cuts':cuts,'guards':guards,
                               'alignment_sha256':digest(aligned),'proposal_sha256':digest(args.proposals/name/'debug.json'),
                               'algorithm_sha256':digest(Path(__file__))})
        summary = {'name':name,'words':len(words),'old_units':len(old),'new_units':len(result),
                   'added_cuts':sorted(set(cuts)-old-{0}),'removed_cuts':sorted(old-set(cuts)),
                   'scope':'complete_cached_transcript','accuracy':None,'release_allowed':False}
        summaries.append(summary)
        print(summary,flush=True)
    save(args.output/'summary.json',summaries)


if __name__ == '__main__':
    main()
