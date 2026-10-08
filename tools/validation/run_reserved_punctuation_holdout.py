"""Frozen, complete-video evaluation of the previously unused Budget Cuts clip."""
import argparse
import datetime
import hashlib
import json
import os
from pathlib import Path
import subprocess

ROOT = Path(__file__).resolve().parents[2]
GPU = 'D:/Anaconda/envs/video-english-whisperx/python.exe'
SEMANTIC = 'D:/Anaconda/envs/subtitle/python.exe'
PROJECT = Path('C:/tmp/video-english-learning-remote')


def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for b in iter(lambda:f.read(4*1024*1024),b''):
            h.update(b)
    return h.hexdigest()


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path)
    a=p.parse_args()
    root=a.output.resolve()
    root.mkdir(parents=True,exist_ok=False)
    items=json.loads((ROOT/'.validation/online-holdout-media/manifest.json').read_text(encoding='utf-8'))
    cohort=[i for i in items if i['name']=='new_budget']
    if len(cohort)!=1:
        raise ValueError('Exactly one previously reserved complete video required')
    (root/'manifest.json').write_text(json.dumps(cohort,indent=2),encoding='utf-8')
    sources=list((ROOT/'tools/versions/v2.1.0').glob('*.py'))+list((ROOT/'tools/validation').glob('*.py'))
    frozen={str(f.relative_to(ROOT)):sha(f) for f in sources}
    record={'created_utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'sources':frozen,
            'video_sha256':sha(Path(cohort[0]['video'])),'audio_sha256':sha(Path(cohort[0]['audio'])),
            'parameters':{'asr_core_seconds':20,'asr_context_seconds':4,'sat_threshold':.25,
                          'soft_dependencies':True,'restored_terminal_threshold':.8},
            'role':'unused_project_holdout_at_freeze','reference_used_as_prompt':False,
            'complete':False,'release_allowed':False,'accuracy':None,'stages':[]}
    def save():
        (root/'freeze.json').write_text(json.dumps(record,indent=2),encoding='utf-8')
    save()
    env=dict(os.environ,HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1',PYTHONIOENCODING='utf-8')
    def run(label,script,args,python=GPU,environment=None):
        if any(sha(ROOT/f)!=h for f,h in frozen.items()):
            raise RuntimeError('Source changed after freeze; preserve failed run')
        print('START '+label,flush=True)
        with (root/(label+'.log')).open('x',encoding='utf-8') as log:
            proc=subprocess.run([python,str(ROOT/'tools/validation'/script),*map(str,args)],
                                cwd=ROOT,env=environment or env,stdout=log,stderr=subprocess.STDOUT)
        record['stages'].append({'name':label,'exit_code':proc.returncode})
        save()
        if proc.returncode:
            raise RuntimeError('Failed '+label+'; see retained log')
        print('COMPLETE '+label,flush=True)
    run('asr','run_windowed_asr_experiment.py',[root/'manifest.json',root/'asr','--model',PROJECT/'models/faster-whisper-large-v3'])
    run('alignment','run_full_audio_alignment_experiment.py',[root/'asr/manifest.json',root/'pipeline/alignment','--model-dir',PROJECT/'models/whisperx'])
    run('punctuation','run_punctuation_experiment.py',[root/'manifest.json',root/'pipeline/alignment',root/'punctuation','--model',ROOT/'.validation-deps/models/bert-restore-punctuation'])
    common=['--project',PROJECT,'--phase','segment','--learning-threshold','.25','--soft-dependencies']
    run('baseline-learning','run_cohort_learning_experiment.py',[root/'manifest.json',root/'pipeline/alignment',root/'baseline-learning',*common],SEMANTIC)
    run('learning','run_cohort_learning_experiment.py',[root/'manifest.json',root/'pipeline/alignment',root/'pipeline/learning',*common,'--punctuation-root',root/'punctuation'],SEMANTIC)
    run('translation','run_cohort_learning_experiment.py',[root/'manifest.json',root/'pipeline/learning',root/'pipeline/translation','--project',PROJECT,'--phase','translate'])
    run('ocr','extract_burned_subtitles.py',[cohort[0]['video'],root/'updated-ocr-new_budget','--interval','.5','--crop-top','.65',
         '--rec-model',ROOT/'.validation-deps/en_PP-OCRv3_rec_infer.onnx'],environment=dict(env,PYTHONPATH=str(ROOT/'.validation-deps/site')))
    run('integrity','audit_pipeline_integrity.py',[root/'manifest.json',root/'pipeline',root/'integrity'])
    run('timing','audit_ocr_timeline.py',[root/'manifest.json',root/'pipeline/alignment',root/'timing','--ocr-root',root])
    record['complete']=True
    save()
    print('Full held-out video completed; accuracy is unverified.',flush=True)


if __name__=='__main__':
    main()
