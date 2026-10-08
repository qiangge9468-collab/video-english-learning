"""Conservative experimental speaker-turn evidence; never changes ASR words/times."""
import math


def overlap(a, b, c, d):
    return max(0., min(b, d)-max(a, c))


def boundary_evidence(words, exclusive_turns, overlapping_speech=(), minimum_coverage=.8):
    if not .5 < minimum_coverage <= 1:
        raise ValueError("Invalid speaker coverage threshold")
    turns = sorted(exclusive_turns, key=lambda t: t["start"])
    for i, turn in enumerate(turns):
        if not all(math.isfinite(turn[k]) for k in ("start", "end")) or not 0 <= turn["start"] < turn["end"]:
            raise ValueError("Invalid speaker interval")
        if not turn.get("speaker") or i and turn["start"] < turns[i-1]["end"]:
            raise ValueError("Expected exclusive nonoverlapping speaker turns")
    labels = []
    for word in words:
        a, b = word["start"], word["end"]
        if not all(math.isfinite(x) for x in (a, b)) or not 0 <= a < b:
            raise ValueError("Invalid word interval")
        scores = {}
        for turn in turns:
            duration = overlap(a, b, turn["start"], turn["end"])
            scores[turn["speaker"]] = scores.get(turn["speaker"], 0) + duration
        speaker = max(scores, key=scores.get) if scores else None
        coverage = scores.get(speaker, 0)/(b-a)
        conflicting = any(overlap(a, b, x["start"], x["end"]) > 0 for x in overlapping_speech)
        labels.append({"speaker": speaker if coverage >= minimum_coverage and not conflicting else None,
                       "coverage": coverage, "overlap": conflicting})
    evidence = []
    for index in range(1, len(words)):
        left, right = labels[index-1], labels[index]
        if not left["speaker"] or not right["speaker"] or left["speaker"] == right["speaker"]:
            continue
        # Do not interpret timing fallback as evidence of an acoustic turn.
        if any(w.get("alignment_status", "aligned") != "aligned" for w in words[index-1:index+1]):
            continue
        a, b = words[index-1]["end"], words[index]["start"]
        if b < a:
            continue
        matching = [(l, r) for l, r in zip(turns, turns[1:])
                    if l["speaker"] == left["speaker"] and r["speaker"] == right["speaker"]
                    and abs(l["end"]-a) <= .35 and abs(r["start"]-b) <= .35
                    and min(l["end"]-l["start"], r["end"]-r["start"]) >= .35]
        if len(matching) != 1:
            continue
        l, r = matching[0]
        if any(overlap(min(a,l["end"]), max(b,r["start"]), x["start"], x["end"]) > 0 for x in overlapping_speech):
            continue
        evidence.append({"word_boundary": index, "left_speaker": left["speaker"], "right_speaker": right["speaker"],
                         "left_coverage": left["coverage"], "right_coverage": right["coverage"],
                         "speaker_turn_start": r["start"], "reviewed": False})
    return {"word_labels": labels, "boundaries": evidence, "accuracy": None}
