"""Semantic English subtitle segmentation for the v2.0.3 computer service.

The module deliberately does not import spaCy or wtpsplit at import time.  The
service can therefore fall back to the legacy segmenter when an optional model
cannot be loaded.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import math
import re
from typing import Any, Iterable


SENTENCE_END_RE = re.compile(r"[.!?][\"')\]]*$")
SOFT_END_RE = re.compile(r"[,;:][\"')\]]*$")
WORD_RE = re.compile(r"[A-Za-z']+")

FUNCTION_WORDS = {
    "a", "an", "the", "to", "of", "with", "for", "from", "into", "on", "in",
    "at", "by", "and", "but", "or", "because", "that", "which", "who", "whom",
    "whose", "when", "if", "as", "my", "your", "his", "her", "our", "their",
    "am", "is", "are", "was", "were", "be", "been", "being", "have", "has",
    "had", "do", "does", "did", "can", "could", "will", "would", "shall",
    "should", "may", "might", "must",
}

CONTINUATION_STARTERS = {
    "of", "to", "from", "for", "with", "without", "than", "that", "which", "who",
    "whom", "whose", "what", "where", "when", "why", "how",
}

DEPENDENCY_LABELS_TO_PROTECT = {
    "amod", "det", "compound", "poss", "case", "aux", "auxpass", "prt",
    "prep", "pobj", "dobj", "attr", "nummod", "neg",
}


@dataclass(frozen=True)
class SegmenterConfig:
    min_seconds: float = 1.2
    target_seconds: float = 5.8
    preferred_max_seconds: float = 8.5
    max_seconds: float = 12.0
    preferred_max_words: int = 24
    max_words: int = 30
    preferred_max_chars: int = 140
    max_chars: int = 160
    soft_silence_seconds: float = 0.32
    silence_break_seconds: float = 0.75
    absolute_silence_seconds: float = 1.2
    orphan_probability_threshold: float = 0.58
    orphan_merge_gap_seconds: float = 5.0
    analysis_chunk_words: int = 180


@dataclass
class BoundaryFeatures:
    index: int
    gap: float = 0.0
    sat_probability: float = 0.0
    punctuation: str = ""
    protected_by_noun_chunk: bool = False
    protected_by_entity: bool = False
    protected_by_dependency: bool = False
    protected_by_pos_pair: bool = False
    previous_pos: str = ""
    next_pos: str = ""
    previous_dependency: str = ""
    next_dependency: str = ""
    forced_silence: bool = False

    @property
    def protected(self) -> bool:
        return (
            self.protected_by_noun_chunk
            or self.protected_by_entity
            or self.protected_by_dependency
            or self.protected_by_pos_pair
        )


def normalized_word(raw: dict[str, Any], index: int) -> dict[str, Any] | None:
    text = " ".join(str(raw.get("text", "")).strip().split())
    if not text:
        return None
    start = float(raw["start"])
    end = max(float(raw["end"]), start + 0.01)
    probability = raw.get("probability")
    try:
        probability = float(probability) if probability is not None else None
    except (TypeError, ValueError):
        probability = None
    return {
        "index": int(raw.get("index", index)),
        "segment_id": raw.get("segment_id"),
        "start": start,
        "end": end,
        "text": text,
        "probability": probability,
        "segment_end": bool(raw.get("segment_end", False)),
        "segment_complete": bool(raw.get("segment_complete", False)),
    }


def normalize_words(words: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    result = []
    for index, raw in enumerate(words):
        word = normalized_word(raw, index)
        if word is not None:
            result.append(word)
    return result


def words_to_text(words: list[dict[str, Any]]) -> str:
    text = " ".join(word["text"].strip() for word in words if word["text"].strip())
    text = re.sub(r"\s+([,.!?;:%])", r"\1", text)
    text = re.sub(r"\s+-\s*", "-", text)
    text = re.sub(r"\s+(['’]s\b)", r"\1", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+n't\b", "n't", text, flags=re.IGNORECASE)
    return " ".join(text.split())


def _joined_text_and_offsets(words: list[dict[str, Any]]) -> tuple[str, list[tuple[int, int]]]:
    parts: list[str] = []
    offsets: list[tuple[int, int]] = []
    cursor = 0
    for word in words:
        if parts:
            parts.append(" ")
            cursor += 1
        text = word["text"].strip()
        start = cursor
        parts.append(text)
        cursor += len(text)
        offsets.append((start, cursor))
    return "".join(parts), offsets


def _flatten_probabilities(value: Any, expected_length: int) -> list[float]:
    if hasattr(value, "tolist"):
        value = value.tolist()
    while isinstance(value, (list, tuple)) and len(value) == 1 and isinstance(value[0], (list, tuple)):
        value = value[0]
    if not isinstance(value, (list, tuple)):
        return [0.0] * expected_length

    result: list[float] = []
    for item in value:
        if isinstance(item, (list, tuple)):
            if len(item) == 1:
                item = item[0]
            elif item:
                item = item[-1]
        try:
            number = float(item)
        except (TypeError, ValueError):
            number = 0.0
        if not math.isfinite(number):
            number = 0.0
        result.append(min(1.0, max(0.0, number)))
    if len(result) < expected_length:
        result.extend([0.0] * (expected_length - len(result)))
    return result[:expected_length]


def _word_index_for_character(offsets: list[tuple[int, int]], position: int) -> int | None:
    for index, (start, end) in enumerate(offsets):
        if start <= position < end or (position == end and index == len(offsets) - 1):
            return index
    return None


def _mark_span_boundaries(
    features: list[BoundaryFeatures],
    offsets: list[tuple[int, int]],
    start_char: int,
    end_char: int,
    attribute: str,
) -> None:
    for boundary_index in range(1, len(offsets)):
        boundary_char = offsets[boundary_index - 1][1]
        if start_char < boundary_char < end_char:
            setattr(features[boundary_index], attribute, True)


def _pos_pair_is_protected(left_pos: str, right_pos: str) -> bool:
    pair = (left_pos, right_pos)
    return pair in {
        ("DET", "NOUN"), ("DET", "PROPN"), ("ADJ", "NOUN"), ("ADJ", "PROPN"),
        ("AUX", "VERB"), ("PART", "VERB"), ("ADP", "DET"), ("ADP", "NOUN"),
        ("ADP", "PROPN"), ("NUM", "NOUN"), ("PROPN", "PROPN"),
    }


def analyze_boundaries(
    words: list[dict[str, Any]],
    sat_model: Any = None,
    spacy_nlp: Any = None,
    config: SegmenterConfig | None = None,
) -> list[BoundaryFeatures]:
    config = config or SegmenterConfig()
    features = [BoundaryFeatures(index=index) for index in range(len(words) + 1)]
    for index in range(1, len(words)):
        gap = float(words[index]["start"]) - float(words[index - 1]["end"])
        previous_text = words[index - 1]["text"].strip()
        punctuation_match = re.search(r"([,.!?;:])[\"')\]]*$", previous_text)
        features[index].gap = gap
        features[index].punctuation = punctuation_match.group(1) if punctuation_match else ""
        features[index].forced_silence = gap >= config.absolute_silence_seconds

    chunk_start = 0
    while chunk_start < len(words):
        chunk_end = min(len(words), chunk_start + config.analysis_chunk_words)
        for index in range(chunk_start + 1, chunk_end):
            if features[index].forced_silence:
                chunk_end = index
                break
        if chunk_end <= chunk_start:
            chunk_end = chunk_start + 1

        chunk_words = words[chunk_start:chunk_end]
        text, offsets = _joined_text_and_offsets(chunk_words)
        if sat_model is not None and text:
            try:
                raw_probabilities = sat_model.predict_proba(text)
                probabilities = _flatten_probabilities(raw_probabilities, len(text))
                for local_index in range(1, len(chunk_words)):
                    char_index = max(0, offsets[local_index - 1][1] - 1)
                    features[chunk_start + local_index].sat_probability = probabilities[char_index]
            except Exception as exc:
                features[chunk_start].previous_dependency = f"sat-error:{type(exc).__name__}:{exc}"

        if spacy_nlp is not None and text:
            try:
                doc = spacy_nlp(text)
                for chunk in getattr(doc, "noun_chunks", []):
                    _mark_span_boundaries(
                        features,
                        offsets,
                        int(chunk.start_char),
                        int(chunk.end_char),
                        "protected_by_noun_chunk",
                    )
                for entity in getattr(doc, "ents", []):
                    _mark_span_boundaries(
                        features,
                        offsets,
                        int(entity.start_char),
                        int(entity.end_char),
                        "protected_by_entity",
                    )

                token_word_indices: dict[int, int] = {}
                tokens = list(doc)
                for token_index, token in enumerate(tokens):
                    mapped = _word_index_for_character(offsets, int(token.idx))
                    if mapped is not None:
                        token_word_indices[token_index] = mapped

                for token_index, token in enumerate(tokens):
                    local_index = token_word_indices.get(token_index)
                    if local_index is None:
                        continue
                    global_index = chunk_start + local_index
                    if global_index > chunk_start:
                        features[global_index].next_pos = str(token.pos_)
                        features[global_index].next_dependency = str(token.dep_)
                    if global_index + 1 <= len(words):
                        features[global_index + 1].previous_pos = str(token.pos_)
                        features[global_index + 1].previous_dependency = str(token.dep_)

                    head_local = _word_index_for_character(offsets, int(token.head.idx))
                    if (
                        head_local is not None
                        and head_local != local_index
                        and str(token.dep_) in DEPENDENCY_LABELS_TO_PROTECT
                        and abs(head_local - local_index) <= 6
                    ):
                        left = min(local_index, head_local)
                        right = max(local_index, head_local)
                        for boundary in range(left + 1, right + 1):
                            features[chunk_start + boundary].protected_by_dependency = True

                for local_index in range(1, len(chunk_words)):
                    feature = features[chunk_start + local_index]
                    if _pos_pair_is_protected(feature.previous_pos, feature.next_pos):
                        feature.protected_by_pos_pair = True
            except Exception as exc:
                features[chunk_start].next_dependency = f"spacy-error:{type(exc).__name__}:{exc}"

        chunk_start = chunk_end
    return features


def _first_lexical_word(text: str) -> str:
    match = WORD_RE.search(text.lower())
    return match.group(0) if match else ""


def _last_lexical_word(text: str) -> str:
    matches = WORD_RE.findall(text.lower())
    return matches[-1] if matches else ""


def _segment_cost(
    words: list[dict[str, Any]],
    start: int,
    end: int,
    boundary: BoundaryFeatures,
    config: SegmenterConfig,
) -> tuple[float, dict[str, float]]:
    segment_words = words[start:end]
    text = words_to_text(segment_words)
    duration = float(segment_words[-1]["end"]) - float(segment_words[0]["start"])
    word_count = len(segment_words)
    char_count = len(text)
    cost_parts: dict[str, float] = {}

    cost_parts["duration"] = abs(duration - config.target_seconds) * 1.6
    if duration > config.preferred_max_seconds:
        cost_parts["preferred_duration"] = (duration - config.preferred_max_seconds) * 2.0
    if word_count > config.preferred_max_words:
        cost_parts["preferred_words"] = (word_count - config.preferred_max_words) * 0.45
    if char_count > config.preferred_max_chars:
        cost_parts["preferred_chars"] = (char_count - config.preferred_max_chars) * 0.15
    if duration < config.min_seconds:
        cost_parts["too_short"] = (config.min_seconds - duration) * 24.0
    if word_count <= 2:
        cost_parts["orphan_length"] = 90.0 if word_count == 1 else 55.0
    elif word_count == 3:
        cost_parts["short_fragment"] = 16.0

    last_word = _last_lexical_word(text)
    first_word = _first_lexical_word(text)
    if last_word in FUNCTION_WORDS or last_word.endswith("ing"):
        cost_parts["weak_ending"] = 55.0
    if first_word in CONTINUATION_STARTERS:
        cost_parts["continuation_start"] = 35.0

    if end < len(words):
        if boundary.protected:
            cost_parts["grammar_protection"] = 75.0
        cost_parts["sat_reward"] = -11.0 * boundary.sat_probability
        if boundary.punctuation and boundary.punctuation in ".!?":
            cost_parts["sentence_punctuation_reward"] = -28.0
        elif boundary.punctuation and boundary.punctuation in ",;:":
            cost_parts["soft_punctuation_reward"] = -9.0
        if boundary.gap >= config.absolute_silence_seconds:
            cost_parts["absolute_silence_reward"] = -30.0
        elif boundary.gap >= config.silence_break_seconds:
            cost_parts["silence_reward"] = -15.0
        elif boundary.gap >= config.soft_silence_seconds:
            cost_parts["soft_silence_reward"] = -5.0
        if segment_words[-1].get("segment_complete"):
            cost_parts["whisper_complete_reward"] = -12.0
        elif segment_words[-1].get("segment_end"):
            cost_parts["whisper_segment_reward"] = -2.0

    return sum(cost_parts.values()), cost_parts


def optimize_segments(
    words: list[dict[str, Any]],
    features: list[BoundaryFeatures],
    config: SegmenterConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = config or SegmenterConfig()
    count = len(words)
    best = [float("inf")] * (count + 1)
    previous: list[int | None] = [None] * (count + 1)
    chosen_costs: list[dict[str, float] | None] = [None] * (count + 1)
    best[0] = 0.0

    for start in range(count):
        if not math.isfinite(best[start]):
            continue
        for end in range(start + 1, min(count, start + config.max_words) + 1):
            candidate_words = words[start:end]
            text = words_to_text(candidate_words)
            duration = float(candidate_words[-1]["end"]) - float(candidate_words[0]["start"])
            if duration > config.max_seconds or len(text) > config.max_chars:
                break
            if any(features[index].forced_silence for index in range(start + 1, end)):
                break
            # Never carry words from the next sentence across an explicit strong
            # punctuation mark. A short complete sentence is preferable to
            # fragments such as "Perfect weather. I'm".
            if any(
                features[index].punctuation
                and features[index].punctuation in ".!?"
                for index in range(start + 1, end)
            ):
                break
            segment_cost, parts = _segment_cost(words, start, end, features[end], config)
            total = best[start] + segment_cost
            if total < best[end]:
                best[end] = total
                previous[end] = start
                chosen_costs[end] = parts

    if previous[count] is None:
        raise ValueError("semantic segmenter could not satisfy subtitle hard limits")

    ranges: list[tuple[int, int]] = []
    cursor = count
    while cursor > 0:
        start = previous[cursor]
        if start is None:
            raise ValueError("semantic segmenter path is incomplete")
        ranges.append((start, cursor))
        cursor = start
    ranges.reverse()

    segments = []
    decisions = []
    for start, end in ranges:
        selected_words = words[start:end]
        probability_values = [
            word["probability"] for word in selected_words if word.get("probability") is not None
        ]
        segment = {
            "start": float(selected_words[0]["start"]),
            "end": float(selected_words[-1]["end"]),
            "text": words_to_text(selected_words),
            "translation": "",
            "_word_start": start,
            "_word_end": end,
            "_avg_word_probability": (
                sum(probability_values) / len(probability_values) if probability_values else None
            ),
        }
        segments.append(segment)
        decisions.append(
            {
                "word_start": start,
                "word_end": end,
                "text": segment["text"],
                "cost": chosen_costs[end] or {},
                "boundary": asdict(features[end]),
            }
        )

    return segments, {
        "algorithm": "semantic-dp-v1",
        "config": asdict(config),
        "decisions": decisions,
        "boundaries": [asdict(feature) for feature in features[1:-1]],
    }


def filter_orphan_function_words(
    segments: list[dict[str, Any]],
    config: SegmenterConfig | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    config = config or SegmenterConfig()
    kept: list[dict[str, Any]] = []
    removed: list[dict[str, Any]] = []
    index = 0
    while index < len(segments):
        segment = segments[index]
        text = str(segment.get("text", "")).strip()
        lexical = WORD_RE.findall(text.lower())
        duration = float(segment["end"]) - float(segment["start"])
        probability = segment.get("_avg_word_probability")
        has_next = index + 1 < len(segments)
        next_segment = segments[index + 1] if has_next else None
        next_gap = (
            float(next_segment["start"]) - float(segment["end"])
            if next_segment is not None
            else float("inf")
        )
        is_orphan_function_word = (
            len(lexical) == 1
            and lexical[0] in (FUNCTION_WORDS | {"so"})
            and duration < config.min_seconds
        )

        if is_orphan_function_word and next_segment is not None:
            merged_text = words_to_text(
                [{"text": text}, {"text": str(next_segment.get("text", "")).strip()}]
            )
            merged_duration = float(next_segment["end"]) - float(segment["start"])
            merged_word_count = len(WORD_RE.findall(merged_text))
            if (
                next_gap <= config.orphan_merge_gap_seconds
                and merged_duration <= config.max_seconds
                and merged_word_count <= config.max_words
                and len(merged_text) <= config.max_chars
            ):
                merged = dict(next_segment)
                merged["start"] = float(segment["start"])
                merged["text"] = merged_text
                merged["_word_start"] = segment.get(
                    "_word_start", next_segment.get("_word_start")
                )
                probabilities = [
                    float(value)
                    for value in (probability, next_segment.get("_avg_word_probability"))
                    if value is not None
                ]
                merged["_avg_word_probability"] = (
                    sum(probabilities) / len(probabilities) if probabilities else None
                )
                kept.append(merged)
                index += 2
                continue

        should_remove = (
            is_orphan_function_word
            and has_next
            and next_gap >= config.absolute_silence_seconds
            and probability is not None
            and float(probability) < config.orphan_probability_threshold
        )
        if should_remove:
            removed.append(
                {
                    "text": text,
                    "start": segment["start"],
                    "end": segment["end"],
                    "probability": probability,
                    "next_gap": next_gap,
                    "reason": "low-confidence isolated function word before long silence",
                }
            )
        else:
            kept.append(segment)
        index += 1
    return kept, removed


def clean_segments(segments: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": " ".join(str(segment["text"]).split()),
            "translation": str(segment.get("translation", "")),
        }
        for segment in segments
        if str(segment.get("text", "")).strip()
    ]


def segment_words(
    raw_words: Iterable[dict[str, Any]],
    sat_model: Any = None,
    spacy_nlp: Any = None,
    config: SegmenterConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = config or SegmenterConfig()
    words = normalize_words(raw_words)
    if not words:
        return [], {"algorithm": "semantic-dp-v1", "error": "no words"}
    features = analyze_boundaries(words, sat_model=sat_model, spacy_nlp=spacy_nlp, config=config)
    segments, debug = optimize_segments(words, features, config)
    segments, removed = filter_orphan_function_words(segments, config)
    debug["removed_orphans"] = removed
    debug["word_count"] = len(words)
    debug["segment_count"] = len(segments)
    return clean_segments(segments), debug
