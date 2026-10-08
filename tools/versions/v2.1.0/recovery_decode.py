"""Bounded context retries for empty gap decodes, independent of titles/corpora.

Agreement is a safety heuristic, not independent ground truth. Original accepted
decodes are unchanged. Newly selected retry words still require alignment/review.
"""
from difflib import SequenceMatcher
import math
import re


def usable_words(parts, origin, start, end, text_allowed):
    result = []
    for part in parts:
        text = str(part.text).strip()
        words = list(getattr(part, "words", None) or [])
        logp = getattr(part, "avg_logprob", None)
        silence = getattr(part, "no_speech_prob", None)
        probabilities = [float(w.probability) for w in words if getattr(w, "probability", None) is not None]
        mean = sum(probabilities)/len(probabilities) if probabilities else 0.
        short = len(re.findall(r"[A-Za-z0-9']+", text)) <= 4 and logp is not None and logp >= -.6
        if (not text or not text_allowed(text) or logp is None or silence is None
                or not math.isfinite(logp) or not math.isfinite(silence) or not math.isfinite(mean)
                or logp < -.8 or silence > .75 or (mean < .30 and not short)):
            continue
        for word in words:
            left, right = origin+float(word.start), origin+float(word.end)
            token = re.sub(r"[^a-z0-9']", "", str(word.word).lower())
            if token and math.isfinite(left) and math.isfinite(right) and right > left and start+.02 < (left+right)/2 < end-.02:
                result.append({"token": token, "midpoint": (left+right)/2})
    return result


def agreement(left, right, tolerance=1.):
    if not left or not right:
        return 0.
    matcher = SequenceMatcher(None, [w["token"] for w in left], [w["token"] for w in right], autojunk=False)
    matches = sum(abs(left[b.a+i]["midpoint"]-right[b.b+i]["midpoint"]) <= tolerance
                  for b in matcher.get_matching_blocks() for i in range(b.size))
    return 2*matches/(len(left)+len(right))


def decode_gap(model, audio, start, end, options, text_allowed):
    """Return (parts, origin, trace), at most three decodes, never OCR prompted."""
    attempts, trace = [], {"policy": "bounded-context-consensus-v1", "attempts": [],
                           "selected_attempt": 0, "retry_selected": False, "review_required": False}
    duration = len(audio)/16000.
    for padding in (.35, 0., 1.):
        origin, stop = max(0., start-padding), min(duration, end+padding)
        if any(abs(old[1]-origin) < 1e-6 and abs(old[2]-stop) < 1e-6 for old in attempts):
            continue
        parts, _ = model.transcribe(audio[int(origin*16000):int(stop*16000)], **options)
        parts = list(parts)
        words = usable_words(parts, origin, start, end, text_allowed)
        attempts.append((parts, origin, stop, words))
        trace["attempts"].append({"clip_start": origin, "clip_end": stop, "usable_words": len(words),
            "segments": [{"text": p.text, "start": origin+float(p.start), "end": origin+float(p.end),
                          "avg_logprob": getattr(p, "avg_logprob", None),
                          "no_speech_prob": getattr(p, "no_speech_prob", None)} for p in parts]})
        if len(attempts) == 1 and words:
            return parts, origin, trace
    # Never promote a single verbose retry. Two differently framed decodes must
    # agree on ordered words AND their positions, including legitimate repeats.
    if len(attempts) == 3:
        score = agreement(attempts[1][3], attempts[2][3])
        trace["retry_agreement"] = score
        if score == 1.:
            selected = max((1, 2), key=lambda i: sum(getattr(p, "avg_logprob", -99.)
                           for p in attempts[i][0])/max(1, len(attempts[i][0])))
            trace.update(selected_attempt=selected, retry_selected=True, review_required=True)
            return attempts[selected][0], attempts[selected][1], trace
    trace["review_required"] = True
    return attempts[0][0], attempts[0][1], trace
