"""Full publisher-transcript edit distance, not manually verified ASR accuracy.

Counts substitutions, deletions AND insertions. Retains all errors including
number spelling, contractions and editorial omissions; no fuzzy score gate.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import re


def tokenize(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?|\d+", text.lower().replace('\u2019', "'"))


def remove_nonspeech_labels(text):
    # Do not remove arbitrary parenthetical speech/editorial phrases.
    return re.sub(r'\((?:laughter|applause|music)\)|\[(?:laughter|applause|music)\]', ' ', text, flags=re.I)


def align(reference, hypothesis):
    # Byte backpointers make full-clip dynamic programming bounded and auditable.
    n, m = len(reference), len(hypothesis)
    back = [bytearray(m+1) for _ in range(n+1)]
    back[0] = bytearray([2]*(m+1))
    previous = list(range(m+1))
    for i in range(1,n+1):
        row = [i]+[0]*m
        back[i][0] = 1
        for j in range(1,m+1):
            options = (previous[j-1]+(reference[i-1] != hypothesis[j-1]), previous[j]+1, row[j-1]+1)
            choice = min(range(3), key=lambda k:options[k])
            row[j], back[i][j] = options[choice], choice
        previous = row
    rows = []
    i,j = n,m
    while i or j:
        choice = back[i][j]
        if i and j and choice == 0:
            i,j = i-1,j-1
            rows.append({'operation':'equal' if reference[i] == hypothesis[j] else 'substitute', 'reference_index':i,'hypothesis_index':j})
        elif i and (choice == 1 or not j):
            i -= 1
            rows.append({'operation':'delete','reference_index':i,'hypothesis_index':None})
        else:
            j -= 1
            rows.append({'operation':'insert','reference_index':None,'hypothesis_index':j})
    rows.reverse()
    return rows


def compare(text, words):
    reference = tokenize(text)
    hypothesis = [t for w in words for t in tokenize(w['text'])]
    rows = align(reference,hypothesis)
    counts = Counter(r['operation'] for r in rows)
    errors = []
    for r in rows:
        if r['operation'] == 'equal':
            continue
        ri,hi = r['reference_index'],r['hypothesis_index']
        errors.append({**r,'reference':reference[ri] if ri is not None else None,
                       'hypothesis':hypothesis[hi] if hi is not None else None,
                       'reference_context':' '.join(reference[max(0,ri-4):ri+5]) if ri is not None else None,
                       'hypothesis_context':' '.join(hypothesis[max(0,hi-4):hi+5]) if hi is not None else None})
    return {'reference_words':len(reference),'hypothesis_words':len(hypothesis),'edit_counts':dict(counts),
            'publisher_transcript_wer':len(errors)/len(reference) if reference else None,
            'normalization':'lowercase, punctuation removed, curly apostrophe normalized; numbers/contractions NOT rewritten',
            'reference_kind':'publisher_caption_not_verbatim_audio_gold','audio_accuracy':None,
            'release_allowed':False,'errors':errors}


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('root',type=Path)
    a = p.parse_args()
    output = a.root/'publisher-comparison'
    output.mkdir(exist_ok=False)
    summary = []
    for reference in sorted((a.root/'publisher-reference').glob('*.json')):
        data = json.loads(reference.read_text(encoding='utf-8'))
        paragraphs = data['response']['data']['translation']['paragraphs']
        text = ' '.join(c['text'] for p in paragraphs for c in p['cues'])
        # Non-speech labels remain explicitly removed from the textual reference.
        text = remove_nonspeech_labels(text)
        for method,path in [('candidate',a.root/'pipeline/alignment'/reference.stem/'alignment.json'),
                            ('baseline',a.root/'baseline-asr'/reference.stem/'asr.json')]:
            words = json.loads(path.read_text(encoding='utf-8'))['words']
            report = compare(text,words)
            report.update(name=reference.stem,method=method,non_speech_parenthetical_labels_removed=True)
            (output/(reference.stem+'-'+method+'.json')).write_text(json.dumps(report,indent=2),encoding='utf-8')
            summary.append({k:v for k,v in report.items() if k != 'errors'})
    (output/'summary.json').write_text(json.dumps(summary,indent=2),encoding='utf-8')
    print(json.dumps(summary,indent=2))


if __name__ == '__main__':
    main()
