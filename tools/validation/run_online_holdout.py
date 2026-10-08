"""Frozen new-video evaluation; publisher captions are evaluation-only.

GPU steps are serial. OCR can run in a separate CPU process. All phases check
the pre-inference source snapshot. No automatic promotion or accuracy claims.
"""
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
PROJECT = 'C:/tmp/video-english-learning-remote'


def sha(p):
    h = hashlib.sha256()
    with p.open('rb') as f:
        for b in iter(lambda: f.read(1024*1024), b''):
            h.update(b)
    return h.hexdigest()


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['freeze', 'gpu', 'ocr', 'audit'])
    p.add_argument('output', type=Path)
    a = p.parse_args()
    root = a.output.resolve()
    if a.phase == 'freeze':
        root.mkdir(parents=True, exist_ok=False)
        items = read(ROOT/'.validation/online-holdout-media/manifest.json') + read(ROOT/'.validation/online-ted-media/manifest.json')
        cohort = [i for i in items if i['role'] == 'frozen_holdout']
        for i in cohort:
            i['hardcaption_verified'] = True
            i['visual_check_scope'] = 'four pre-inference frames at 10%,30%,60%,85%; not whole-audio human review'
        (root/'manifest.json').write_text(json.dumps(cohort, indent=2), encoding='utf-8')
        paths = list((ROOT/'tools/versions/v2.1.0').glob('*.py'))+list((ROOT/'tools/validation').glob('*.py'))
        record = {'created_utc': datetime.datetime.now(datetime.timezone.utc).isoformat(),
                  'sources': {str(x.relative_to(ROOT)):sha(x) for x in paths},
                  'manifest_sha256':sha(root/'manifest.json'), 'threshold':.25, 'soft_dependencies':True,
                  'asr_core_seconds':20, 'asr_context_seconds':4, 'alignment_policy':'bounded-source-disagreement-v4',
                  'reference_used_as_prompt':False, 'preexisting_tuning_videos':False,
                  'reserve_excluded':['new_budget'], 'release_allowed':False}
        (root/'freeze.json').write_text(json.dumps(record, indent=2), encoding='utf-8')
        print(f'FROZEN {len(cohort)} complete videos, {sum(i["duration"] for i in cohort)/60:.2f} minutes', flush=True)
        return
    record = read(root/'freeze.json')
    def verify():
        if any(sha(ROOT/x) != v for x,v in record['sources'].items()) or sha(root/'manifest.json') != record['manifest_sha256']:
            raise RuntimeError('Frozen source/input changed; preserve run and create a new cohort protocol')
    verify()
    env = dict(os.environ, PYTHONIOENCODING='utf-8', HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1')
    scripts = ROOT/'tools/validation'
    def run(label, script, arguments, python=GPU, environment=None):
        verify()
        print('START '+label, flush=True)
        log = root/(label+'.log')
        with log.open('x', encoding='utf-8') as f:
            subprocess.run([python, str(scripts/script), *map(str,arguments)], cwd=ROOT,
                           env=environment or env, stdout=f, stderr=subprocess.STDOUT, check=True)
        print('COMPLETE '+label, flush=True)
    if a.phase == 'gpu':
        run('windowed-asr','run_windowed_asr_experiment.py',[root/'manifest.json',root/'windowed-asr','--model',PROJECT+'/models/faster-whisper-large-v3'])
        run('pipeline','run_caption_pipeline_experiment.py',[root/'windowed-asr/manifest.json',root/'pipeline','--project',PROJECT,
            '--alignment-python',GPU,'--semantic-python',SEMANTIC,'--learning-threshold','.25','--soft-dependencies'])
        run('baseline-asr','run_full_audio_asr_comparison.py',[root/'manifest.json',root/'baseline-asr','--model',PROJECT+'/models/faster-whisper-large-v3'])
        run('baseline-learning','run_cohort_learning_experiment.py',[root/'manifest.json',root/'pipeline/alignment',root/'baseline-learning','--project',PROJECT,'--phase','segment'],python=SEMANTIC)
    elif a.phase == 'ocr':
        ocr_env = dict(env, PYTHONPATH=str(ROOT/'.validation-deps/site'))
        for i in read(root/'manifest.json'):
            run('ocr-'+i['name'],'extract_burned_subtitles.py',[i['video'],root/('updated-ocr-'+i['name']),
                '--interval','.5','--crop-top','.65','--rec-model',ROOT/'.validation-deps/en_PP-OCRv3_rec_infer.onnx'],environment=ocr_env)
    elif a.phase == 'audit':
        run('integrity','audit_pipeline_integrity.py',[root/'manifest.json',root/'pipeline',root/'integrity'])
        run('comparison','compare_full_transcript_candidates.py',[root/'manifest.json',root/'pipeline/alignment',root/'baseline-asr',root/'comparison','--format','alignment','--ocr-root',root])
        run('timing','audit_ocr_timeline.py',[root/'manifest.json',root/'pipeline/alignment',root/'timing','--ocr-root',root])
        run('baseline-comparison','compare_full_transcript_candidates.py',[root/'manifest.json',root/'baseline-asr',root/'windowed-asr',root/'baseline-comparison','--ocr-root',root])


if __name__ == '__main__':
    main()
