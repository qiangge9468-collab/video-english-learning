"""Replay whole cached semantic analyses with independently computed acoustic evidence."""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/versions/v2.1.0'))
from semantic_caption_segmenter_v206 import (normalize_words, BoundaryFeatures, SegmenterConfig,
                                             learning_sentences, apply_speaker_evidence)


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','alignment','baseline','speakers','output'):
        p.add_argument(name,type=Path)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve previous results')
    args.output.mkdir(parents=True)
    summary = []
    for item in read(args.manifest):
        name = item['name']
        path = args.alignment/name/'alignment.json'
        words = normalize_words(read(path)['words'])
        old = read(args.baseline/name/'learning.json')
        debug = read(args.baseline/name/'debug.json')
        config = SegmenterConfig(**debug['config'])
        features = [BoundaryFeatures(index=0)]+[BoundaryFeatures(**b) for b in debug['boundaries']]+[BoundaryFeatures(index=len(words))]
        replay,_ = learning_sentences(words,features,config)
        if replay != old:
            raise ValueError('Cached baseline does not reproduce exactly')
        speaker = read(args.speakers/(name+'.json'))
        if speaker['alignment_sha256'] != hashlib.sha256(path.read_bytes()).hexdigest():
            raise ValueError('Wrong aligned input')
        rejected = apply_speaker_evidence(words,features,speaker,config)
        result,new_debug = learning_sentences(words,features,replace(config,learning_speaker_boundaries=True))
        new_debug['speaker_rejected_without_semantic_support'] = rejected
        target = args.output/name
        target.mkdir()
        for file,data in [('learning.json',result),('debug.json',new_debug)]:
            (target/file).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
        old_cuts = {s['word_end'] for s in old}
        new_cuts = {s['word_end'] for s in result}
        summary.append({'name':name,'scope':'complete_cached_transcript','words':len(words),
                        'old_units':len(old),'new_units':len(result),'acoustic_candidates':len(speaker['boundaries']),
                        'semantic_rejections':len(rejected),'added_cuts':sorted(new_cuts-old_cuts),
                        'removed_cuts':sorted(old_cuts-new_cuts),'accuracy':None,'release_allowed':False})
        print(json.dumps(summary[-1]),flush=True)
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
