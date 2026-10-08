"""Independent-reference release gate; do not confuse OCR agreement with accuracy.

Reference JSON must contain independently reviewed word, timing and sentence
boundary annotations. OCR proposals remain unreviewed until a human checks
them against the frame/audio, including OCR omissions. A video with partial
image coverage cannot pass the full-video gate. No thresholds are learned from
the held-out set. Burned display-cue boundaries are NOT sentence boundaries.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re


def tokens(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?|\d+", text.lower().replace("’", "'"))


def edit_distance(left, right):
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        new = [i]
        for j, b in enumerate(right, 1):
            new.append(min(new[-1]+1, row[j]+1, row[j-1]+(a != b)))
        row = new
    return row[-1]


def evaluate(reference, candidates, threshold=.95, timing_tolerance=.5):
    if not 0 < threshold <= 1 or timing_tolerance <= 0:
        raise ValueError("Invalid gate settings")
    results = []
    assigned = set()
    for item in reference.get("items", []):
        # Explicit word-range correspondence must be reviewed, never inferred
        # just by picking the nearest/fuzziest successful candidate.
        start, end = item["candidate_word_start"], item["candidate_word_end"]
        if not isinstance(start, int) or not isinstance(end, int) or start < 0 or end < start or end > len(candidates):
            raise ValueError("Invalid reviewed candidate word range")
        indexes = set(range(start, end))
        if assigned & indexes:
            raise ValueError("Candidate words cannot be reused to satisfy multiple reference cues")
        assigned.update(indexes)
        hypothesis = candidates[start:end]
        source_tokens = tokens(item["text"])
        actual_tokens = tokens(" ".join(w["text"] for w in hypothesis))
        errors = edit_distance(source_tokens, actual_tokens)
        onset = abs(float(hypothesis[0]["start"]) - item["speech_start"]) if hypothesis else None
        offset = abs(float(hypothesis[-1]["end"]) - item["speech_end"]) if hypothesis else None
        results.append({"id": item["id"], "reference_words": len(source_tokens), "word_errors": errors,
                        "timing_pass": onset is not None and offset is not None
                            and max(onset, offset) <= timing_tolerance,
                        "onset_error": onset, "offset_error": offset,
                        "boundary_pass": item.get("boundary_pass"),
                        "translation_pass": item.get("translation_pass"),
                        "reviewed": item.get("reviewed") is True})
    total_words = sum(r["reference_words"] for r in results)
    def rate(key):
        return sum(r[key] is True for r in results) / len(results) if results else None
    # Otherwise an evaluator could ignore all hallucinated/unmatched output
    # and obtain a perfect score from a few selected successful matches.
    unmapped_insertions = sum(len(tokens(w["text"])) for i,w in enumerate(candidates) if i not in assigned)
    text_accuracy = max(0, 1-(sum(r["word_errors"] for r in results)+unmapped_insertions)/total_words) if total_words else None
    metrics = {"text_accuracy": text_accuracy, "timing_pass_rate": rate("timing_pass"),
               "boundary_pass_rate": rate("boundary_pass"),
               "translation_pass_rate": rate("translation_pass")}
    ready = bool(results) and all(r["reviewed"] for r in results) and reference.get("full_audio_reviewed") is True
    ready = ready and reference.get("complete_video_reference") is True
    ready = ready and reference.get("reviewer") not in (None, "", "ocr", "asr")
    ready = ready and all(r["boundary_pass"] is not None and r["translation_pass"] is not None for r in results)
    passed = ready and all(value is not None and value >= threshold for value in metrics.values())
    return {"status": "pass" if passed else ("below_threshold" if ready else "insufficient_reference"),
            "threshold": threshold, "timing_tolerance_seconds": timing_tolerance,
            "unmapped_candidate_insertions": unmapped_insertions,
            "metrics": metrics, "release_allowed": passed, "items": results}


def cohort_gate(reports):
    """All four metrics must pass on EACH video, including an untuned holdout."""
    identities = {r.get("source_sha256") for r in reports if r.get("source_sha256")}
    enough = len(identities) >= 4 and len(identities) == len(reports)
    holdout = any(r.get("held_out") is True for r in reports)
    all_pass = bool(reports) and all(r.get("release_allowed") is True for r in reports)
    return {"release_allowed": enough and holdout and all_pass,
            "distinct_videos": len(identities), "minimum_videos": 4,
            "has_held_out_video": holdout,
            "reason": "pass" if enough and holdout and all_pass else "four_complete_independent_references_required"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("words", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    report = evaluate(json.loads(args.reference.read_text(encoding="utf-8-sig")),
                      json.loads(args.words.read_text(encoding="utf-8-sig")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(report["status"])
    raise SystemExit(0 if report["release_allowed"] else 2)


if __name__ == "__main__":
    main()
