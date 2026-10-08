"""Compare complete transcript candidates with retained diagnostics, not a score gate.

Whole-output comparisons include every OCR proposal (when available). OCR and
another ASR decode are imperfect diagnostic references, never verified accuracy.
"""
import argparse
import hashlib
import json
from pathlib import Path
from audit_transcript_drift import audit
from compare_ocr_proposals import compare, proposals


def read(path):
    return json.loads(path.read_text(encoding='utf-8-sig'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('comparison', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--format', choices=('asr', 'alignment'), default='asr')
    parser.add_argument('--ocr-root', type=Path)
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve previous comparisons')
    args.output.mkdir(parents=True)
    summary = []
    for item in read(args.manifest):
        name = item['name']
        path = args.candidate/name/(args.format+'.json')
        words = read(path)['words']
        if not words:
            raise ValueError('Alignment required before word/timing comparison')
        peer = read(args.comparison/name/'asr.json')['words']
        drift = audit(words, peer)
        (args.output/(name+'-drift.json')).write_text(json.dumps(drift, ensure_ascii=False, indent=2), encoding='utf-8')
        row = {'name': name, 'candidate_words': len(words), 'comparison_words': len(peer),
               'large_disagreement_anchors': drift['flagged_phrase_anchors'],
               'large_disagreement_words': drift['flagged_primary_words'],
               'candidate_sha256': hashlib.sha256(path.read_bytes()).hexdigest(),
               'independent_accuracy': None, 'release_allowed': False}
        folder = args.ocr_root/('updated-ocr-'+name) if args.ocr_root else None
        if folder and folder.exists():
            extraction = read(folder/'extraction.json')
            if not extraction['complete_video_reference']:
                raise ValueError('Cannot report partial OCR as complete')
            cues = proposals(folder, item.get('ocr_min_y', 0))
            triage = compare(cues, words)
            (args.output/(name+'-ocr.json')).write_text(json.dumps(triage, ensure_ascii=False, indent=2), encoding='utf-8')
            row.update(ocr_word_recall_not_accuracy=triage['ocr_word_recall'],
                       ocr_unmatched_cues=triage['unmatched_cues'], ocr_cues=triage['cue_count'])
        else:
            row['reference_status'] = 'no_complete_ocr_reference'
        summary.append(row)
        print(json.dumps(row), flush=True)
    (args.output/'summary.json').write_text(json.dumps(summary, indent=2), encoding='utf-8')


if __name__ == '__main__':
    main()
