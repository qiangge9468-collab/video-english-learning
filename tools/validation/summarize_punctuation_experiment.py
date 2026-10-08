"""Compact completed-run evidence; no full publisher transcripts or media."""
import argparse
from collections import Counter
import hashlib
import json
import subprocess
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('output',type=Path)
    p.add_argument('--ffprobe',default='D:/Anaconda/envs/video-english-whisperx/Library/bin/ffprobe.exe')
    a=p.parse_args()
    work=ROOT/'.validation'
    groups=[('original',work/'updated-cohort.json',work/'windowed-pipeline-r5',work/'learning-threshold-r7',work/'learning-threshold-r7-translation'),
            ('online',work/'online-holdout-r1/manifest.json',work/'online-holdout-r1/pipeline',work/'online-holdout-r1/pipeline/learning',work/'online-holdout-r1/pipeline/translation')]
    rows=[]
    for group,manifest,pipeline,baseline,baseline_translation in groups:
        for item in read(manifest):
            name=item['name']
            old=read(baseline/name/'learning.json')
            new=read(work/f'punctuation-learning-r4-{group}'/name/'learning.json')
            trans=read(work/f'punctuation-translation-r4-{group}'/name/'bilingual.json')
            old_trans=read(baseline_translation/name/'bilingual.json')
            alignment=read(pipeline/'alignment'/name/'alignment.json')
            from audit_pipeline_integrity import audit
            integrity=audit(read(pipeline/'alignment'/name/'input.json'),alignment,new,trans)
            if not integrity['integrity_passed']:
                raise RuntimeError('Integrity failed '+name)
            if 'duration' in item:
                duration=item['duration']
            else:
                duration=float(subprocess.check_output([a.ffprobe,'-v','error','-show_entries','format=duration',
                    '-of','default=noprint_wrappers=1:nokey=1',str(item['audio'])],text=True).strip())
            rows.append({'name':name,'role':'development_regression','duration_seconds':duration,
                         'source_words':len(alignment['words']),'old_learning_units':len(old),'learning_units':len(new),
                         'old_over_40_words':sum(s['word_end']-s['word_start']>40 for s in old),
                         'over_40_words':sum(s['word_end']-s['word_start']>40 for s in new),
                         'old_translation_status':dict(Counter(s.get('translation_status') for s in old_trans)),
                         'translation_status':dict(Counter(s.get('translation_status') for s in trans)),
                         'integrity_passed':True,'asr_rerun_this_round':False})
    reserve=work/'punctuation-reserved-r4'
    freeze=read(reserve/'freeze.json')
    if not freeze['complete'] or any(s['exit_code'] for s in freeze['stages']):
        raise RuntimeError('Reserved video is not complete')
    reserved={'name':'new_budget','role':'unused_at_freeze','duration_seconds':read(reserve/'manifest.json')[0]['duration'],
              'freeze_sha256':hashlib.sha256((reserve/'freeze.json').read_bytes()).hexdigest(),
              'stages':freeze['stages'],'translation':read(reserve/'pipeline/translation/summary.json')[0],
              'ocr':read(reserve/'updated-ocr-new_budget/extraction.json'),
              'integrity':read(reserve/'integrity/summary.json')[0],
              'raw_ocr_timing':read(reserve/'timing/summary.json')[0],
              'remaining_failure':'dialogue turn merge around 179-186 seconds',
              'reference_caveat':'raw OCR cue 65 is a one-line fragment of a persistent two-line caption; inspected frames 246.48 and 250.30 seconds'}
    result={'algorithm':'punctuation-r4-experiment','release_allowed':False,'accuracy':None,
            'scope':'ten complete cached transcripts resegmented/retranslated; one unused full video ASR/alignment/OCR',
            'development':rows,'reserved':reserved,
            'publisher_boundaries_baseline':read(work/'punctuation-boundaries-baseline-final/summary.json'),
            'publisher_boundaries_r4':read(work/'punctuation-boundaries-r4-final/summary.json'),
            'total_duration_seconds':sum(r['duration_seconds'] for r in rows)+reserved['duration_seconds']}
    a.output.write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'complete_videos':len(rows)+1,'minutes':result['total_duration_seconds']/60,
                      'regression_units':sum(r['learning_units'] for r in rows),
                      'translation_counts':dict(sum((Counter(r['translation_status']) for r in rows),Counter())),
                      'release_allowed':False},indent=2))


if __name__=='__main__':
    main()
