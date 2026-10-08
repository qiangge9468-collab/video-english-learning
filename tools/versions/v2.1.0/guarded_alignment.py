"""Lossless, source-indexed forced alignment with bounded local retries.

Structural checks are not a speech accuracy metric. Failed segments retain
source timings (or explicitly estimated timings) and remain review-required.
The callable accepts one transcript segment and returns WhisperX word dicts.
"""
import math


def valid_span(word):
    try:
        start, end = float(word["start"]), float(word["end"])
        return math.isfinite(start) and math.isfinite(end) and 0 <= start < end
    except (KeyError, TypeError, ValueError):
        return False


def candidate_issues(expected, words, window):
    issues = []
    if [str(w.get("word", "")).strip() for w in words] != expected:
        return ["token_sequence_changed"]
    previous = window["start"]
    for i, word in enumerate(words):
        if not valid_span(word):
            issues.append(f"missing_or_invalid_time:{i}")
            continue
        start, end = float(word["start"]), float(word["end"])
        if start < window["start"] - .02 or end > window["end"] + .02:
            issues.append(f"outside_window:{i}")
        if start < previous - .08:
            issues.append(f"overlap:{i}")
        if end-start > 2.5:
            issues.append(f"long_word:{i}")
        score = word.get("score")
        if score is not None and (not math.isfinite(float(score)) or float(score) < .1):
            issues.append(f"low_score:{i}")
        previous = end
    return issues


def source_drift_issues(original, candidates, threshold=1.5):
    """Bound each independently timestamped word, including short utterances.

Only independently timestamped ASR words form anchors, never older WhisperX or
estimated timings. Retaining ASR on disagreement is a review fallback, not an
assertion that ASR timing is ground truth.
"""
    if len(original) != len(candidates):
        return []
    flags = []
    for i, (old, new) in enumerate(zip(original, candidates)):
        eligible = (valid_span(old) and valid_span(new) and not old.get('asr_timing_estimated')
                    and old.get('aligned_by') not in ('whisperx', 'estimate')
                    and float(old['end'])-float(old['start']) <= 1.5)
        delta = (float(new['start'])+float(new['end'])-float(old['start'])-float(old['end']))/2 if eligible else 0.
        if abs(delta) > threshold:
            flags.append(i)
    return [f'source_time_disagreement:{i}' for i in flags]


def reconcile_fallback_order(original, candidates, bad):
    """Reject CTC neighbors that cross a retained source word; never sort it away.

    A mixture of fallback and CTC can invert words even when either input alone
    was ordered. Propagate only through conflicting CTC words. Already-invalid
    source timing remains explicitly unresolved, not silently retimed.
    """
    rejected = set(bad)
    if len(original) != len(candidates):
        return rejected, []
    while True:
        selected = [old if i in rejected else new for i, (old, new) in enumerate(zip(original, candidates))]
        extra = set()
        for i, (left, right) in enumerate(zip(selected, selected[1:])):
            if not (valid_span(left) and valid_span(right)):
                continue
            if float(right['start']) < float(left['start']) or float(right['end']) < float(left['end']):
                extra.update(j for j in (i, i+1) if j not in rejected)
        if not extra:
            break
        rejected.update(extra)
    return rejected, [f'fallback_order_conflict:{i}' for i in sorted(rejected-set(bad))]


def align_guarded(source_segments, source_words, align_one, duration):
    segments, words, diagnostics = [], [], []
    for source_id, source in enumerate(source_segments):
        expected = str(source.get("text", "")).split()
        if not expected:
            continue
        window = {"start": max(0., float(source["start"])),
                  "end": min(duration, float(source["end"])),
                  "text": " ".join(expected)}
        if window["end"] <= window["start"]:
            raise ValueError(f"Invalid source segment {source_id}")
        original = [w for w in source_words if w.get("segment_id") == source.get("id", source_id)]
        if [str(w.get("text", "")).strip() for w in original] != expected:
            original = []
        def inspect(candidate, limits):
            found = candidate_issues(expected, candidate, limits)
            if 'token_sequence_changed' not in found:
                found += source_drift_issues(original, candidate)
            return found
        candidates = align_one(dict(window))
        issues = inspect(candidates, window)
        attempts = [{"window": dict(window), "issues": list(issues), "candidate_words": candidates}]
        if issues:
            # Never borrow from adjacent utterances merely to raise CTC scores.
            left = float(source_segments[source_id-1]["end"]) if source_id else 0.
            right = float(source_segments[source_id+1]["start"]) if source_id+1 < len(source_segments) else duration
            retry = {**window, "start": min(window["start"], max(left, window["start"]-.6)),
                     "end": max(window["end"], min(right, window["end"]+.6))}
            if retry != window:
                retried = align_one(dict(retry))
                retry_issues = inspect(retried, retry)
                attempts.append({"window": retry, "issues": list(retry_issues), "candidate_words": retried})
                if len(retry_issues) < len(issues):
                    candidates, issues = retried, retry_issues
        # Do not silently drop tokens or reorder repetitions by their timestamps.
        sequence_ok = [str(w.get("word", "")).strip() for w in candidates] == expected
        bad = set(range(len(expected))) if not sequence_ok else set()
        low = set()
        for issue in issues:
            if ':' not in issue:
                continue
            kind, value = issue.rsplit(':', 1)
            index = int(value)
            if kind == 'low_score':
                low.add(index)
            else:
                bad.add(index)
                if kind == 'overlap' and index:
                    bad.add(index-1)
        if sequence_ok:
            bad, conflicts = reconcile_fallback_order(original, candidates, bad)
            issues = issues + conflicts
        anchors = [i for i,w in enumerate(candidates) if sequence_ok and i not in bad | low and valid_span(w)]
        word_start = len(words)
        for index, token in enumerate(expected):
            old = original[index] if original else {}
            candidate = candidates[index] if sequence_ok else {}
            if index not in bad and valid_span(candidate):
                start, end = float(candidate["start"]), float(candidate["end"])
                status = "review_required" if index in low else "aligned"
                aligned_by = "whisperx"
            elif valid_span(old) and float(old['end']) <= duration:
                start, end = float(old["start"]), float(old["end"])
                status, aligned_by = "source_timing_fallback", old.get("aligned_by", "asr")
            else:
                # An unalignable number must not replace every good timestamp
                # in the sentence with uniform estimates. Preserve good words;
                # estimate only this unresolved run between trustworthy anchors.
                left = max((i for i in anchors if i < index), default=-1)
                right = min((i for i in anchors if i > index), default=len(expected))
                first = float(candidates[left]['end']) if left >= 0 else window['start']
                last = float(candidates[right]['start']) if right < len(expected) else window['end']
                if last > first:
                    step = (last-first)/(right-left-1)
                    start, end = first+(index-left-1)*step, first+(index-left)*step
                else:
                    end = min(duration, max(0., first)+.01)
                    start = max(0., end-.01)
                status, aligned_by = "estimated_review_required", "estimate"
            asr_probability = old.get("asr_probability", old.get("probability") if old.get("aligned_by") != "whisperx" else None)
            words.append({**old, "index": len(words), "segment_id": len(segments),
                          "source_segment_id": source_id, "source_token_index": index,
                          "start": start, "end": end, "text": token,
                          "probability": asr_probability, "asr_probability": asr_probability,
                          "alignment_score": candidate.get("score") if status in ("aligned", "review_required") else None,
                          "aligned_by": aligned_by, "alignment_status": status})
        member = words[word_start:]
        segments.append({**source, "id": len(segments), "source_segment_id": source_id,
                         "start": min(w["start"] for w in member), "end": max(w["end"] for w in member),
                         "text": " ".join(expected), "word_start": word_start, "word_end": len(words),
                         "translation": "", "alignment_review_required": bool(issues)})
        diagnostics.append({"source_segment_id": source_id, "attempts": attempts,
                            "remaining_issues": issues, "word_count": len(expected)})
    moved = order_artifacts_chronologically(segments, words)
    return segments, words, {"alignment": "whisperx", "quality_guard": True,
                            "alignment_policy": "bounded-source-disagreement-v4",
                            "source_token_count": sum(len(str(s.get("text", "")).split()) for s in source_segments),
                            "word_count": len(words), "segment_count": len(segments),
                            "chronologically_reordered_words": moved,
                            "review_required_segments": sum(bool(d["remaining_issues"]) for d in diagnostics),
                            "audio_alignment_accuracy": None, "segments": diagnostics}


def order_artifacts_chronologically(segments, words):
    """In-place ordering only; source identity, scores and review status survive."""
    # Recovery segments may overlap older ASR segments. Keep playback order
    # chronological WITHOUT deduplicating equal counts from distinct sources.
    words.sort(key=lambda w: (w["start"], w["end"], w["index"]))
    moved = 0
    for index, word in enumerate(words):
        moved += word["index"] != index
        word["index"] = index
    for segment in segments:
        indexes = [w["index"] for w in words if w["source_segment_id"] == segment["source_segment_id"]]
        segment["word_indices"] = indexes
        segment["word_start"], segment["word_end"] = min(indexes), max(indexes)+1
        segment["word_range_contiguous"] = indexes == list(range(min(indexes), max(indexes)+1))
    return moved
