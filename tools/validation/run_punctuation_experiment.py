"""Independent, local-only punctuation evidence over complete aligned transcripts.

Does not rewrite recognized words or times. Uses first-subtoken labels, as in
simpletransformers NER, and overlapping context without tokenizer truncation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sys
import time

LABELS = ['OU', 'OO', '.O', '!O', ',O', '.U', '!U', ',U', ':O', ';O', ':U', "'O", '-O', '?O', '?U']


def clean_token(text):
    text = text.strip().lower()
    while text and not text[0].isalnum():
        text = text[1:]
    while text and not text[-1].isalnum():
        text = text[:-1]
    return text


def analysis_words(words, predictions, threshold=.8):
    """Punctuation-only analysis view; never replaces the persisted ASR words."""
    import re
    if len(words) != len(predictions):
        raise ValueError('Prediction count mismatch')
    result = []
    for index, (word, prediction) in enumerate(zip(words, predictions)):
        if prediction['word_index'] != index or prediction['text'] != word['text']:
            raise ValueError('Prediction/source mismatch')
        text = word['text']
        if not re.search(r'[,.!?;:][\"\u201d\u2019\)\]]*$',text):
            probabilities = prediction['probabilities']
            punct = max('.!?',key=lambda p:probabilities[p])
            if prediction['terminal_probability'] >= threshold:
                text += punct
            elif probabilities[','] >= threshold:
                text += ','
        result.append({**word,'text':text})
    return result


def token_windows(lengths, core_words=96, context_words=24, max_tokens=510):
    """Every word is a core exactly once; context may overlap, never truncate."""
    if core_words < 1 or context_words < 0 or any(n < 1 or n > max_tokens for n in lengths):
        raise ValueError('Invalid token/window length')
    core_start = 0
    while core_start < len(lengths):
        core_end = min(len(lengths), core_start + core_words)
        while sum(lengths[core_start:core_end]) > max_tokens:
            core_end -= 1
        left, right = core_start, core_end
        budget = max_tokens - sum(lengths[left:right])
        for _ in range(context_words):
            if left > 0 and lengths[left-1] <= budget:
                left -= 1
                budget -= lengths[left]
            if right < len(lengths) and lengths[right] <= budget:
                budget -= lengths[right]
                right += 1
        yield left, right, core_start, core_end
        core_start = core_end


def predict(words, tokenizer, model, device):
    import torch
    # A punctuation-only ASR token stays in the source; use UNK only in the
    # model input so every original word still has a traceable evidence record.
    tokens = [clean_token(w['text']) or tokenizer.unk_token for w in words]
    lengths = [len(tokenizer.encode(t, add_special_tokens=False)) for t in tokens]
    records = [None] * len(words)
    for left, right, start, end in token_windows(lengths):
        encoded = tokenizer(tokens[left:right], is_split_into_words=True,
                            return_tensors='pt', truncation=False)
        if encoded['input_ids'].shape[1] > 512:
            raise ValueError('Token budget mismatch; refusing silent truncation')
        word_ids = encoded.word_ids()
        with torch.inference_mode():
            probs = model(**{k:v.to(device) for k,v in encoded.items()}).logits[0].float().softmax(-1).cpu()
        seen = set()
        for token_index, local_word in enumerate(word_ids):
            if local_word is None or local_word in seen:
                continue
            seen.add(local_word)
            index = left + local_word
            if not start <= index < end:
                continue
            row = probs[token_index].tolist()
            label = LABELS[max(range(len(row)), key=row.__getitem__)]
            records[index] = {'word_index': index, 'text': words[index]['text'],
                              'label': label, 'terminal_probability': sum(p for l,p in zip(LABELS,row) if l[0] in '.!?'),
                              'probabilities': {p: sum(v for l,v in zip(LABELS,row) if l[0] == p) for p in 'O.!?,:;\'-'},
                              'context_word_start': left, 'context_word_end': right}
    if any(x is None for x in records):
        raise ValueError('Missing prediction; refusing partial evidence')
    return records


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('manifest', type=Path)
    parser.add_argument('alignment', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--model', type=Path, required=True)
    parser.add_argument('--device', default='cuda', choices=['cuda','cpu'])
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError('Preserve previous experiments')
    import torch
    from transformers import AutoTokenizer, AutoModelForTokenClassification
    torch.set_num_threads(4)
    labels = json.loads((args.model/'model_args.json').read_text())['labels_list']
    if labels != LABELS:
        raise ValueError('Unexpected label mapping')
    tokenizer = AutoTokenizer.from_pretrained(args.model, use_fast=True, local_files_only=True, trust_remote_code=False)
    model = AutoModelForTokenClassification.from_pretrained(args.model, local_files_only=True,
                                                           trust_remote_code=False, weights_only=True).to(args.device).eval()
    args.output.mkdir(parents=True)
    freeze = {'model_sha256': hashlib.sha256((args.model/'pytorch_model.bin').read_bytes()).hexdigest(),
              'script_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
              'core_words':96, 'context_words':24, 'scope':'complete_cached_aligned_transcripts',
              'changed_source_words':False, 'accuracy':None, 'release_allowed':False}
    (args.output/'freeze.json').write_text(json.dumps(freeze, indent=2))
    for item in json.loads(args.manifest.read_text(encoding='utf-8-sig')):
        started = time.monotonic()
        source = args.alignment/item['name']/'alignment.json'
        words = json.loads(source.read_text(encoding='utf-8'))['words']
        records = predict(words, tokenizer, model, args.device)
        target = args.output/item['name']
        target.mkdir()
        result = {'input_sha256': hashlib.sha256(source.read_bytes()).hexdigest(), 'predictions': records,
                  'input_words':len(words), 'elapsed_seconds':time.monotonic()-started}
        (target/'punctuation.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'name':item['name'],'words':len(words),'seconds':result['elapsed_seconds']}),flush=True)


if __name__ == '__main__':
    main()
