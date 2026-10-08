"""Apply existing deterministic counting and quality guards to a complete experiment.

No inference or audio/text edits. Deterministic counting is not ASR verification.
"""
import argparse
from collections import Counter
import copy
import os
from pathlib import Path
import sys
from run_local_semantic_boundaries import read,save,digest,ROOT


def main():
    p = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest','input','output'):
        p.add_argument(name,type=Path)
    args = p.parse_args()
    args.output.mkdir(parents=True,exist_ok=False)
    os.environ.update(VIDEO_ENGLISH_DATA_DIR=str(args.output/'isolated-service'),
                      WHISPER_RUNTIME_CONFIG=str(args.output/'config.json'),
                      WHISPER_RUNTIME_STATUS=str(args.output/'status.json'))
    sys.path.insert(0,str(ROOT/'tools/versions/v2.1.0'))
    import service
    summaries = []
    for item in read(args.manifest):
        name = item['name']
        source = args.input/name/'bilingual.json'
        before = read(source)
        result = copy.deepcopy(before)
        deterministic = []
        for i,u in enumerate(result):
            direct = service.deterministic_caption_translation(u['text'])
            if direct is not None:
                u.update(translation=direct,translation_status='deterministic',translation_warnings=[])
                deterministic.append(i)
                continue
            check = service.caption_translation_status(u['text'],u['translation'])
            if check not in ('generated_unreviewed','deterministic'):
                u['translation_status'] = check
                u['translation_warnings'] = sorted(set(u.get('translation_warnings',[])+['service_quality_'+check]))
        dest = args.output/name
        dest.mkdir()
        save(dest/'bilingual.json',result)
        summary = {'name':name,'units':len(result),'deterministic_unit_ids':deterministic,
                   'prior_sha256':digest(source),'script_sha256':digest(Path(__file__)),
                   'service_sha256':digest(Path(service.__file__)),
                   'statuses':dict(Counter(u['translation_status'] for u in result)),
                   'source_preserved':all({k:v for k,v in a.items() if not k.startswith('translation')} ==
                                          {k:v for k,v in b.items() if not k.startswith('translation')}
                                          for a,b in zip(before,result)),
                   'accuracy':None,'release_allowed':False}
        if not summary['source_preserved']:
            raise ValueError('Source fields changed')
        summaries.append(summary)
        print(summary,flush=True)
    save(args.output/'summary.json',summaries)


if __name__ == '__main__':
    main()
