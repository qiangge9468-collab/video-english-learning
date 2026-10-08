"""Read-only timestamp/coverage diagnostics. Never deletes or repairs words.

    A clean structural check does not prove alignment to the waveform. Such a
    claim requires independent reference timings and/or human audio review.
"""
from __future__ import annotations

from collections import Counter
import math
import re


def tokens(text):
    return re.findall(r"[a-z]+(?:'[a-z]+)?|\d+", str(text).lower().replace("’", "'"))


def audit_words(words, source_text=None):
    issues = []
    previous_start = None
    previous_end = None
    token_count = 0
    for index, word in enumerate(words):
        text = word.get("text", word.get("word", ""))
        token_count += len(tokens(text))
        try:
            start, end = float(word["start"]), float(word["end"])
        except (KeyError, ValueError, TypeError):
            issues.append({"index": index, "kind": "missing_timing", "text": text})
            continue
        if not math.isfinite(start) or not math.isfinite(end) or start < 0 or end <= start:
            issues.append({"index": index, "kind": "invalid_duration", "text": text})
        if previous_start is not None and start < previous_start:
            issues.append({"index": index, "kind": "backward_timestamp", "text": text})
        if previous_end is not None and start < previous_end - .08:
            issues.append({"index": index, "kind": "overlap_over_80ms", "text": text})
        if end - start > 2.5:
            issues.append({"index": index, "kind": "long_word_review", "text": text})
        score = word.get("alignment_score")
        if score is None and word.get("aligned_by") == "whisperx":
            score = word.get("probability")  # legacy cache compatibility, never ASR confidence
        if score is not None and float(score) < .1:
            issues.append({"index": index, "kind": "low_alignment_score_review", "text": text})
        previous_start, previous_end = start, end
    covered = None
    if source_text is not None:
        source = Counter(tokens(source_text))
        actual = Counter(t for word in words for t in tokens(word.get("text", word.get("word", ""))))
        covered = sum((source & actual).values()) / max(1, sum(source.values()))
    return {"word_count": len(words), "lexical_token_count": token_count,
            "issues": issues, "issue_count": len(issues),
            "source_token_multiset_coverage": covered,
            "audio_alignment_accuracy": None, "independent_reference_required": True}
