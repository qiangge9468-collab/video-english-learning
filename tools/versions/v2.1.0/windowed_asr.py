"""Experimental absolute-clock ASR windows; no title/OCR-specific corrections.

Each core owns words by midpoint; surrounding audio provides decoding context.
All discarded context remains in the caller's raw log. Boundary ownership can
still miss/duplicate speech when ASR times disagree: explicitly flag its edges.
This bounds propagation of long-form timestamp drift, not recognition error.
"""
import math


def audio_windows(samples, sample_rate=16000, core_seconds=20., context_seconds=4.):
    if samples < 0 or sample_rate <= 0 or core_seconds <= 0 or context_seconds < 0:
        raise ValueError('Invalid window settings')
    if not math.isfinite(core_seconds+context_seconds) or core_seconds+2*context_seconds > 30:
        raise ValueError('Decoded windows must fit the 30-second model context')
    step, pad = round(core_seconds*sample_rate), round(context_seconds*sample_rate)
    if step < 1:
        raise ValueError('Core must contain samples')
    for index, start in enumerate(range(0, samples, step)):
        end = min(samples, start+step)
        yield {'index': index, 'core_start_sample': start, 'core_end_sample': end,
               'clip_start_sample': max(0, start-pad), 'clip_end_sample': min(samples, end+pad),
               'core_start': start/sample_rate, 'core_end': end/sample_rate,
               'clip_start': max(0, start-pad)/sample_rate, 'clip_end': min(samples, end+pad)/sample_rate}


def owned_words(parts, window, first_segment=0, first_word=0):
    segments, words, rejected = [], [], []
    for part_index, part in enumerate(parts):
        member = []
        for token_index, word in enumerate(part.get('words', [])):
            start, end = window['clip_start']+float(word['start']), window['clip_start']+float(word['end'])
            token = str(word['text']).strip()
            if not token or not math.isfinite(start+end) or end < start:
                rejected.append({'part': part_index, 'token': token_index, 'reason': 'invalid_word'})
                continue
            if start < window['clip_start']-.02 or end > window['clip_end']+.02:
                rejected.append({'part': part_index, 'token': token_index, 'reason': 'outside_decoded_audio'})
                continue
            midpoint = (start+end)/2
            last_point = midpoint == window['core_end'] == window['clip_end']
            if not (window['core_start'] <= midpoint < window['core_end'] or last_point):
                continue
            original_start, original_end = start, end
            zero_duration = end == start
            if zero_duration:
                # Retain recognizer text even when it supplied no duration.
                # This tiny support span is explicitly an estimate, not aligned
                # speech; the next acoustic alignment must resolve or flag it.
                end = min(window['clip_end'], start+.01)
                start = max(window['clip_start'], end-.01)
            member.append({**word, 'text': token, 'start': start, 'end': end,
                           'asr_original_start': original_start, 'asr_original_end': original_end,
                           'asr_timing_estimated': zero_duration,
                           'alignment_status': 'estimated_review_required' if zero_duration else 'asr_unverified',
                           'index': first_word+len(words)+len(member),
                           'segment_id': first_segment+len(segments),
                           'asr_probability': word.get('probability'),
                           'asr_window_index': window['index'], 'asr_local_segment': part_index,
                           'asr_local_token': token_index,
                           'boundary_review_required': min(midpoint-window['core_start'],
                                                           window['core_end']-midpoint) < .25})
        if member:
            segments.append({**{k:v for k,v in part.items() if k not in ('words', 'text', 'start', 'end')},
                'id': first_segment+len(segments), 'start': min(w['start'] for w in member),
                'end': max(w['end'] for w in member), 'text': ' '.join(w['text'] for w in member),
                'word_start': member[0]['index'], 'word_end': member[-1]['index']+1,
                'asr_window_index': window['index']})
            words.extend(member)
    return segments, words, rejected
