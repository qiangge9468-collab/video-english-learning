"""Whole-cohort single-parameter segmentation ablation on saved model evidence.

No ASR/model inference is rerun. Existing SaT/spaCy features are immutable inputs;
this isolates a threshold change instead of confounding it with new recognition.
"""
import argparse
from dataclasses import asdict, replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/versions/v2.1.0'))
from semantic_caption_segmenter_v206 import BoundaryFeatures, SegmenterConfig, normalize_words, learning_sentences


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def restore_features(internal, word_count):
    if [f['index'] for f in internal] != list(range(1,word_count)):
        raise ValueError('Saved features do not cover all words')
    return [BoundaryFeatures(index=0)] + [BoundaryFeatures(**f) for f in internal] + [BoundaryFeatures(index=word_count)]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest',type=Path)
    parser.add_argument('pipeline',type=Path)
    parser.add_argument('output',type=Path)
    parser.add_argument('--threshold',type=float,required=True)
    parser.add_argument('--soft-dependencies',action='store_true')
    args = parser.parse_args()
    if not 0 < args.threshold < 1:
        raise ValueError('Invalid threshold')
    if args.output.exists():
        raise FileExistsError('Keep earlier parameter tests')
    args.output.mkdir(parents=True)
    summary = []
    for item in read(args.manifest):
        name = item['name']
        alignment = args.pipeline/'alignment'/name/'alignment.json'
        debug_path = args.pipeline/'learning'/name/'debug.json'
        previous = read(debug_path)
        words = normalize_words(read(alignment)['words'])
        internal = previous['boundaries']
        # The debug format omits the two unused outer sentinels, not words.
        features = restore_features(internal,len(words))
        config = SegmenterConfig(**previous['config'])
        old_threshold = config.learning_boundary_probability
        old = read(args.pipeline/'learning'/name/'learning.json')
        replayed,_ = learning_sentences(words,features,config)
        if replayed != old:
            raise ValueError('Baseline replay differs: cannot claim a one-parameter ablation')
        config = replace(config, learning_boundary_probability=args.threshold,
                         learning_soft_dependency_boundaries=args.soft_dependencies)
        result,debug = learning_sentences(words,features,config)
        target = args.output/name
        target.mkdir()
        (target/'learning.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'debug.json').write_text(json.dumps(debug),encoding='utf-8')
        report = {'name':name,'scope':'all_cached_words_and_boundaries_no_new_model_inference',
                  'input_words':len(words),'old_threshold':old_threshold,'threshold':args.threshold,
                  'soft_dependency_boundaries':args.soft_dependencies,
                  'old_learning_sentences':len(old),'learning_sentences':len(result),
                  'old_units_over_40_words':sum(s['word_end']-s['word_start'] > 40 for s in old),
                  'units_over_40_words':sum(s['word_end']-s['word_start'] > 40 for s in result),
                  'old_single_word_units':sum(s['word_end']-s['word_start'] == 1 for s in old),
                  'single_word_units':sum(s['word_end']-s['word_start'] == 1 for s in result),
                  'boundary_review_units':sum(s['boundary_review_required'] for s in result),
                  'input_alignment_sha256':hashlib.sha256(alignment.read_bytes()).hexdigest(),
                  'input_features_sha256':hashlib.sha256(debug_path.read_bytes()).hexdigest(),
                  'config':asdict(config),'accuracy':None,'release_allowed':False}
        summary.append(report)
        print(json.dumps(report),flush=True)
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
