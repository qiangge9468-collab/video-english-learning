"""Absolute-time speech chunks for experimental WhisperX ASR.

Unlike concatenating speech samples, each chunk keeps the original audio clock.
ASR chunk boundaries are NOT learning-sentence boundaries.
"""
import math


def merge_speech(ranges, maximum=20., max_pause=1.):
    if not math.isfinite(maximum+max_pause) or maximum <= 0 or max_pause < 0:
        raise ValueError('Invalid chunk limits')
    chunks = []
    previous = 0.
    for start, end in ranges:
        start, end = float(start), float(end)
        if not math.isfinite(start+end) or start < previous or end <= start or end-start > maximum+.001:
            raise ValueError('Speech ranges must be valid, ordered and bounded')
        previous = end
        if chunks and start-chunks[-1]['end'] <= max_pause and end-chunks[-1]['start'] <= maximum:
            chunks[-1]['end'] = end
            chunks[-1]['segments'].append((start, end))
        else:
            chunks.append({'start': start, 'end': end, 'segments': [(start, end)]})
    return chunks
