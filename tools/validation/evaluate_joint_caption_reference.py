"""Fail-closed joint learning-unit gate. Legacy marginal reports are not release evidence.

Artifacts contain source_sha256, words and units (word_start, word_end, text,
translation, translation_status). Independent full-audio reviews must be bound
to the exact artifact digest. OCR/display times alone cannot approve a review.
"""
import argparse
import hashlib
import json
import math
from pathlib import Path

from evaluate_caption_reference import tokens


POLICY = "joint-learning-unit-v1"


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False,
                                    separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()


def evaluate(reference, artifact, threshold=.90, timing_tolerance=.5):
    if not 0 < threshold <= 1 or not 0 < timing_tolerance <= .5:
        raise ValueError("Invalid joint gate settings")
    words, units = artifact["words"], artifact["units"]
    cursor = 0
    for unit in units:
        start, end = unit["word_start"], unit["word_end"]
        if type(start) is not int or type(end) is not int or start != cursor or not start < end <= len(words):
            raise ValueError("Units must partition every original word exactly once")
        if tokens(unit["text"]) != tokens(" ".join(w["text"] for w in words[start:end])):
            raise ValueError("Unit text differs from its original words")
        cursor = end
    if cursor != len(words):
        raise ValueError("Unassigned source words")
    for word in words:
        if not all(math.isfinite(word[k]) for k in ("start", "end")) or not 0 <= word["start"] < word["end"]:
            raise ValueError("Invalid word timing")
    assigned, ids, rows = set(), set(), []
    for item in reference.get("items", []):
        if item["id"] in ids:
            raise ValueError("Duplicate reference id")
        ids.add(item["id"])
        mapped = item["candidate_unit_ids"]
        if any(type(i) is not int or not 0 <= i < len(units) for i in mapped) or mapped != sorted(set(mapped)):
            raise ValueError("Invalid unit mapping")
        if assigned.intersection(mapped):
            raise ValueError("A candidate unit cannot satisfy multiple reference units")
        assigned.update(mapped)
        selected = [units[i] for i in mapped]
        hypothesis = " ".join(u["text"] for u in selected)
        exact = bool(tokens(item["text"])) and tokens(item["text"]) == tokens(hypothesis)
        # A documented human judgment may accept a non-verbatim but faithful
        # transcript, never an unchecked model-generated self-assessment.
        text_ok = bool(selected) and item.get("text_pass", exact) is True
        if text_ok and not exact and not str(item.get("text_review_reason", "")).strip():
            text_ok = False
        onset = offset = None
        a, b = item["speech_start"], item["speech_end"]
        if not all(math.isfinite(x) for x in (a, b)) or not 0 <= a < b:
            raise ValueError("Invalid reference speech times")
        if selected:
            onset = abs(words[selected[0]["word_start"]]["start"] - a)
            offset = abs(words[selected[-1]["word_end"]-1]["end"] - b)
        timing_ok = onset is not None and max(onset, offset) <= timing_tolerance and item.get("no_clipping") is True
        # Multiple fragments do not become a usable learning sentence just by
        # concatenating them inside the evaluator.
        boundary_ok = len(selected) == 1 and item.get("boundary_pass") is True
        translation_ok = bool(selected) and item.get("translation_pass") is True and all(
            str(u.get("translation", "")).strip() and u.get("translation_status") not in
            (None, "english_fallback", "failed", "review_required") for u in selected)
        row = {"id": item["id"], "text_pass": text_ok, "timing_pass": timing_ok,
               "boundary_pass": boundary_ok, "translation_pass": translation_ok,
               "onset_error": onset, "offset_error": offset, "reviewed": item.get("reviewed") is True}
        row["joint_pass"] = all(row[k] is True for k in ("text_pass", "timing_pass", "boundary_pass", "translation_pass"))
        rows.append(row)
    extras = sorted(set(range(len(units))) - assigned)
    denominator = len(rows) + len(extras)
    metrics = {k + "_rate": sum(r[k] is True for r in rows)/denominator if denominator else None
               for k in ("text_pass", "timing_pass", "boundary_pass", "translation_pass", "joint_pass")}
    reasons = []
    if not rows or not all(r["reviewed"] for r in rows):
        reasons.append("incomplete_item_review")
    if reference.get("artifact_sha256") != digest(artifact):
        reasons.append("review_not_bound_to_artifact")
    if not artifact.get("source_sha256") or reference.get("source_sha256") != artifact["source_sha256"]:
        reasons.append("source_identity_mismatch")
    if not all(reference.get(k) is True for k in ("full_audio_reviewed", "complete_video_reference", "missing_speech_checked")):
        reasons.append("full_audio_reference_required")
    reviewer = str(reference.get("reviewer", "")).strip().lower()
    if reviewer in ("", "ocr", "asr", "model", "none"):
        reasons.append("independent_reviewer_required")
    passed = not reasons and metrics["joint_pass_rate"] is not None and metrics["joint_pass_rate"] >= threshold
    return {"policy": POLICY, "source_sha256": artifact.get("source_sha256"), "artifact_sha256": digest(artifact),
            "status": "insufficient_reference" if reasons else ("pass" if passed else "below_threshold"),
            "release_allowed": passed, "threshold": threshold, "timing_tolerance_seconds": timing_tolerance,
            "reference_units": len(rows), "extra_candidate_units": extras, "denominator": denominator,
            "metrics": metrics, "blocking_reasons": reasons, "items": rows}


def cohort_gate(reports, frozen_holdout):
    """Every video must pass; neither pooled scores nor one held-out video suffice."""
    entries = frozen_holdout.get("videos", [])
    expected = {r["source_sha256"]: r for r in entries}
    actual = {r.get("source_sha256"): r for r in reports}
    genres = {r.get("genre") for r in entries}
    ready = len(expected) >= 4 and len(expected) == len(entries) == len(reports) == len(actual)
    ready = ready and set(expected) == set(actual) and frozen_holdout.get("frozen_before_evaluation") is True
    ready = ready and all(r.get("previously_tuned") is False for r in entries)
    ready = ready and {"monologue", "dialogue", "counting", "noise"}.issubset(genres)
    ready = ready and all(r.get("policy") == POLICY and r.get("release_allowed") is True
                          and r.get("threshold", 0) >= .90 and r.get("timing_tolerance_seconds", 999) <= .5
                          for r in reports)
    return {"policy": POLICY, "release_allowed": bool(ready), "minimum_videos": 4,
            "reason": "pass" if ready else "four_frozen_untuned_full_video_joint_passes_required"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("reference", type=Path)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args()
    result = evaluate(json.loads(args.reference.read_text(encoding="utf-8-sig")),
                      json.loads(args.artifact.read_text(encoding="utf-8-sig")))
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    print(result["status"])
    raise SystemExit(0 if result["release_allowed"] else 2)


if __name__ == "__main__":
    main()
