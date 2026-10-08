"""Exact boundary agreement with publisher punctuation (not audio gold).

Every missing reference boundary and extra predicted boundary is counted.
An unalignable boundary is NOT silently excluded or credited as correct.
"""
import argparse
import json
from pathlib import Path
import re
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'tools/versions/v2.1.0'))
from semantic_caption_segmenter_v206 import abbreviation_continues
from compare_publisher_reference import tokenize, remove_nonspeech_labels, align


def reference_boundaries(text):
    result = set()
    for match in re.finditer(r'[.!?][\"\u201d\u2019\)\]]*(?=\s|$)', text):
        before = text[:match.end()].split()
        after = text[match.end():].split()
        if not before or not after or abbreviation_continues(before[-1], after[0]):
            continue
        result.add(len(tokenize(text[:match.end()])))
    return result


def audit(text, words, sentences):
    ref = tokenize(text)
    hyp, word_ends = [], [0]
    for w in words:
        hyp.extend(tokenize(w['text']))
        word_ends.append(len(hyp))
    rows = align(ref,hyp)
    mapping = {r['hypothesis_index']:r['reference_index'] for r in rows if r['operation']=='equal'}
    expected = reference_boundaries(text)
    # Do not collapse duplicate cuts around punctuation-only ASR words; the
    # second cut is still an extra boundary, not another correct prediction.
    observed = [word_ends[s['word_end']] for s in sentences[:-1]]
    correct, errors, matched = 0, [], set()
    for boundary in sorted(observed):
        left,right = mapping.get(boundary-1),mapping.get(boundary)
        mapped = right if left is not None and right == left+1 else None
        if mapped in expected and mapped not in matched:
            correct += 1
            matched.add(mapped)
        else:
            errors.append({'kind':'extra_or_unalignable_boundary','hypothesis_boundary':boundary,
                           'context':' '.join(hyp[max(0,boundary-6):boundary])+' | '+' '.join(hyp[boundary:boundary+6])})
    for boundary in sorted(expected-matched):
        errors.append({'kind':'missed_reference_boundary','reference_boundary':boundary,
                       'context':' '.join(ref[max(0,boundary-6):boundary])+' | '+' '.join(ref[boundary:boundary+6])})
    precision = correct/len(observed) if observed else 0
    recall = correct/len(expected) if expected else 0
    return {'reference_boundaries':len(expected),'predicted_boundaries':len(observed),'correct_boundaries':correct,
            'precision':precision,'recall':recall,'f1':2*precision*recall/(precision+recall) if precision+recall else 0,
            'errors':errors,'scope':'complete_publisher_transcript_exact_punctuation_boundaries',
            'audio_accuracy':None,'release_allowed':False}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('references',type=Path)
    p.add_argument('alignment',type=Path)
    p.add_argument('learning',type=Path)
    p.add_argument('output',type=Path)
    a = p.parse_args()
    a.output.mkdir(parents=True,exist_ok=False)
    summary = []
    for source in sorted(a.references.glob('*.json')):
        reference = json.loads(source.read_text(encoding='utf-8'))
        paragraphs = reference['response']['data']['translation']['paragraphs']
        text = remove_nonspeech_labels(' '.join(c['text'] for p in paragraphs for c in p['cues']))
        words = json.loads((a.alignment/source.stem/'alignment.json').read_text(encoding='utf-8'))['words']
        sentences = json.loads((a.learning/source.stem/'learning.json').read_text(encoding='utf-8'))
        report = audit(text,words,sentences)
        report['name'] = source.stem
        (a.output/(source.stem+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
        summary.append({k:v for k,v in report.items() if k != 'errors'})
    (a.output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
