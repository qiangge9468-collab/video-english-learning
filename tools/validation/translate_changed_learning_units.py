"""Translate changed units; reuse exact unchanged bilingual inputs with provenance.

Produces a complete output for every video. This is explicitly NOT a fresh
translation of all units, nor an independent translation accuracy assessment.
"""
import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/versions/v2.1.0'))


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def key(unit):
    return unit['word_start'],unit['word_end'],unit['text'],unit['start'],unit['end']


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','learning','prior_translation','output'):
        p.add_argument(name,type=Path)
    p.add_argument('--model',type=Path,required=True)
    args = p.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve previous results')
    args.output.mkdir(parents=True)
    os.environ.update(VIDEO_ENGLISH_DATA_DIR=str(args.output/'isolated-service'),
        WHISPER_RUNTIME_CONFIG=str(args.output/'config.json'), WHISPER_RUNTIME_STATUS=str(args.output/'status.json'),
        TRANSLATION_MODEL=str(args.model), TRANSLATION_DEVICE='cuda',TRANSLATION_PROVIDER='transformers',
        TRANSLATION_STYLE='generic',TRANSLATION_LOCAL_FILES_ONLY='1',TRANSLATION_BATCH_SIZE='8',
        HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
    summary = []
    for item in read(args.manifest):
        name = item['name']
        source = args.learning/name/'learning.json'
        cached = args.prior_translation/name/'bilingual.json'
        units = read(source)
        lookup = {key(u):u for u in read(cached)}
        indexes = [i for i,u in enumerate(units) if key(u) not in lookup]
        translated = {}
        if indexes:
            import service
            result = service.translate_segments([units[i] for i in indexes])
            if len(result) != len(indexes) or any(key(a)!=key(b) for a,b in zip(result,[units[i] for i in indexes])):
                raise ValueError('Translation changed source units')
            translated = dict(zip(indexes,result))
        output = []
        for i,u in enumerate(units):
            prior = translated[i] if i in translated else lookup[key(u)]
            output.append(dict(u,translation=prior.get('translation',''),
                               translation_status=prior.get('translation_status','missing')))
        target = args.output/name
        target.mkdir()
        (target/'bilingual.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
        report = {'name':name,'units':len(units),'freshly_translated':len(indexes),'reused_exact_units':len(units)-len(indexes),
                  'learning_sha256':hashlib.sha256(source.read_bytes()).hexdigest(),
                  'prior_translation_sha256':hashlib.sha256(cached.read_bytes()).hexdigest(),
                  'statuses':dict(Counter(u['translation_status'] for u in output)),
                  'accuracy':None,'release_allowed':False}
        summary.append(report)
        print(json.dumps(report),flush=True)
    (args.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')


if __name__ == '__main__':
    main()
