"""Full-transcript ablation: cached SaT/parser features + new punctuation model.

Source words/times remain unchanged. This is not new ASR/alignment inference.
"""
import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT/'tools/versions/v2.1.0'))
from semantic_caption_segmenter_v206 import SegmenterConfig, normalize_words, learning_sentences, abbreviation_continues
from replay_learning_threshold import restore_features


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('pipeline', type=Path)
    parser.add_argument('punctuation', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--threshold', type=float, default=.8)
    args = parser.parse_args()
    if not 0 <= args.threshold <= 1:
        raise ValueError('Invalid threshold')
    if args.output.exists():
        raise FileExistsError('Preserve previous runs')
    args.output.mkdir(parents=True)
    reports = []
    for item in read(args.manifest):
        name = item['name']
        alignment = args.pipeline/'alignment'/name/'alignment.json'
        words = normalize_words(read(alignment)['words'])
        saved = read(args.pipeline/'learning'/name/'debug.json')
        features = restore_features(saved['boundaries'], len(words))
        config = SegmenterConfig(**saved['config'])
        old = read(args.pipeline/'learning'/name/'learning.json')
        original, _ = learning_sentences(words, features, config)
        if original != old:
            raise ValueError('Baseline replay must exactly match before evidence changes')
        punctuation = read(args.punctuation/name/'punctuation.json')
        if punctuation['input_sha256'] != hashlib.sha256(alignment.read_bytes()).hexdigest():
            raise ValueError('Evidence belongs to a different alignment')
        predictions = punctuation['predictions']
        if len(predictions) != len(words) or any(p['text'] != w['text'] or p['word_index'] != i for i,(p,w) in enumerate(zip(predictions, words))):
            raise ValueError('Punctuation/source word mismatch')
        for i in range(1,len(words)):
            features[i].restored_terminal_probability = predictions[i-1]['terminal_probability']
            if abbreviation_continues(words[i-1]['text'], words[i]['text']):
                features[i].protected_by_abbreviation = True
                features[i].punctuation = ''
        config = replace(config, learning_punctuation_threshold=args.threshold,
                         learning_boundary_probability=.25, learning_soft_dependency_boundaries=True)
        result, debug = learning_sentences(words, features, config)
        target = args.output/name
        target.mkdir()
        (target/'learning.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        (target/'debug.json').write_text(json.dumps(debug),encoding='utf-8')
        report = {'name':name,'words':len(words),'old_sentences':len(old),'sentences':len(result),
                  'old_over_40_words':sum(s['word_end']-s['word_start']>40 for s in old),
                  'over_40_words':sum(s['word_end']-s['word_start']>40 for s in result),
                  'abbreviation_protections':sum(f.protected_by_abbreviation for f in features),
                  'scope':'complete_cached_transcript','accuracy':None,'release_allowed':False}
        reports.append(report)
        print(json.dumps(report),flush=True)
    (args.output/'summary.json').write_text(json.dumps(reports,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
