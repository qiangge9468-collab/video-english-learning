"""Export compact evidence without redistributing videos or full transcripts."""
import argparse
from collections import Counter
import json
from pathlib import Path


def read(p):
    return json.loads(p.read_text(encoding='utf-8'))


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path)
    p.add_argument('output',type=Path)
    a = p.parse_args()
    if a.output.exists():
        raise FileExistsError('Preserve previous summary')
    root = a.root
    manifest = read(root/'manifest.json')
    def table(path):
        return {r['name']:r for r in read(root/path)}
    actual = table('windowed-asr/summary.json')
    baseline = table('baseline-asr/summary.json')
    integrity = table('integrity/summary.json')
    comparison = table('comparison/summary.json')
    bcomparison = table('baseline-comparison/summary.json')
    timing = table('timing/summary.json')
    publisher = read(root/'publisher-comparison/summary.json')
    pipeline = read(root/'pipeline/pipeline.json')
    if not pipeline['complete'] or len(manifest) != 6:
        raise ValueError('Unexpected/incomplete cohort')
    rows = []
    for i in manifest:
        n=i['name']
        ocr=read(root/('updated-ocr-'+n)/'extraction.json')
        if not ocr['complete_video_reference'] or not actual[n]['model_inference_executed']:
            raise ValueError('Incomplete real-video verification')
        candidate=read(root/'pipeline/learning'/n/'learning.json')
        original=read(root/'baseline-learning'/n/'learning.json')
        stats=integrity[n]
        r={'name':n,'title':i['title'],'source_url':i['source_url'],
           'video_sha256':i['video_sha256'],'audio_sha256':i['audio_sha256'],'duration_seconds':i['duration'],
           'complete_audio_candidate_and_baseline_executed':True,'complete_video_ocr_executed':True,
           'ocr_sampled_frames':ocr['sample_count'],'decoded_video_frames':ocr['decoded_frames'],
           'video_decode_errors':len(ocr['decode_errors']),
           'candidate_input_words':actual[n]['word_count'],'baseline_input_words':baseline[n]['word_count'],
           'candidate_learning_units':len(candidate),'baseline_learning_units_same_input':len(original),
           'candidate_units_over_40_words':sum(s['word_end']-s['word_start']>40 for s in candidate),
           'baseline_units_over_40_words_same_input':sum(s['word_end']-s['word_start']>40 for s in original),
           'translation_status_counts':stats['translation_status_counts'],'integrity_passed':stats['integrity_passed'],
           'ocr_word_recall_not_accuracy':comparison[n]['ocr_word_recall_not_accuracy'],
           'baseline_ocr_word_recall_not_accuracy':bcomparison[n]['ocr_word_recall_not_accuracy'],
           'ocr_anchor_counts':timing[n]['counts'],
           'publisher_transcript_comparison':[{k:v for k,v in x.items() if k in ('method','reference_words','edit_counts','publisher_transcript_wer')} for x in publisher if x['name']==n]}
        rows.append(r)
    totals=Counter()
    for r in rows:
        totals.update(r['translation_status_counts'])
    report={'scope':'six_new_complete_publisher_hardcaption_videos',
            'candidate_policy':read(root/'freeze.json'), 'results':rows,
            'total_duration_seconds':sum(r['duration_seconds'] for r in rows),
            'total_ocr_sampled_frames':sum(r['ocr_sampled_frames'] for r in rows),
            'total_decoded_video_frames':sum(r['decoded_video_frames'] for r in rows),
            'total_words_conserved':sum(r['candidate_input_words'] for r in rows),
            'total_learning_units':sum(r['candidate_learning_units'] for r in rows),
            'total_translation_status_counts':dict(totals),
            'human_full_audio_review_complete':False,'independent_accuracy_95_verified':False,
            'candidate_release_allowed':False,'production_files_changed':False}
    a.output.parent.mkdir(parents=True,exist_ok=True)
    a.output.write_text(json.dumps(report,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in ('candidate_policy','results')},indent=2))


if __name__ == '__main__':
    main()
