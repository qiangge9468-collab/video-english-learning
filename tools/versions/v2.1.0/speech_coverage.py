"""Pure policies for post-alignment coverage repair; no text invention."""


def expand_to_word_gaps(ranges, words, duration, max_seconds=17.3):
    """Include quiet syllables between existing words, not entire music gaps.

    Returned ranges exclude padding. Callers may add acoustic context, but may
    insert candidate words only inside these uncovered ranges.
    """
    result = []
    for start, end in sorted(ranges):
        before = [float(w["end"]) for w in words if float(w["end"]) <= start]
        after = [float(w["start"]) for w in words if float(w["start"]) >= end]
        left, right = max(before, default=0.), min(after, default=duration)
        if 0 < right-left <= max_seconds:
            start, end = left, right
        if result and start <= result[-1][1]:
            result[-1][1] = max(result[-1][1], end)
        else:
            result.append([start, end])
    return result
