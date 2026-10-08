"""Quality-aware English subtitle segmentation for the v2.1.0 computer service.

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

# Prefix titles are not sentence ends. Do not blanket-protect e.g. U.S. or
# etc., which can legitimately finish a sentence.
TITLE_ABBREVIATIONS = {"mr.", "mrs.", "ms.", "dr.", "prof.", "rev.", "hon."}


def abbreviation_continues(left: str, right: str) -> bool:
    left = left.strip().strip('\"\u201c\u201d(\'')
    right = right.strip().lstrip('\"\u201c\u201d(\'')
    if not right or not re.match(r"[A-Za-z]", right):
        return False
    if left.lower() in TITLE_ABBREVIATIONS:
        return True
    return bool(re.fullmatch(r"[A-HJ-Z]\.", left) and re.match(r"[A-Z]", right))

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
    orphan_merge_gap_seconds: float = 8.0
    analysis_chunk_words: int = 180
    # Experimental, opt-in until independent full-video reference gates pass.
    learning_sentence_mode: bool = False
    learning_max_words: int = 100
    learning_boundary_probability: float = 0.75
    # Playback/translation safety, not proof of a linguistic sentence end.
    learning_max_join_gap_seconds: float = 4.0
    # Separate experiment: broad parser arcs can span two unpunctuated clauses.
    # Concrete phrase/subject/object links still protect their word boundaries.
    learning_soft_dependency_boundaries: bool = False
    # Independent punctuation is optional evidence, not an ASR text rewrite.
    learning_punctuation_threshold: float | None = None
    learning_speaker_boundaries: bool = False


@dataclass
class BoundaryFeatures:
    index: int
    gap: float = 0.0
    sat_probability: float = 0.0
    punctuation: str = ""
    sat_recommended: bool = False
    protected_by_noun_chunk: bool = False
    protected_by_entity: bool = False
    protected_by_dependency: bool = False
    protected_by_pos_pair: bool = False
    previous_pos: str = ""
    next_pos: str = ""
    previous_dependency: str = ""
    next_dependency: str = ""
    forced_silence: bool = False
    protected_by_abbreviation: bool = False
    restored_terminal_probability: float | None = None
    acoustic_speaker_change: bool = False

    @property
    def protected(self) -> bool:
        return (
            self.protected_by_noun_chunk
            or self.protected_by_entity
            or self.protected_by_dependency
            or self.protected_by_pos_pair
            or self.protected_by_abbreviation
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
        **raw,
        "index": int(raw.get("index", index)),
        "segment_id": raw.get("segment_id"),
        "start": start,
        "end": end,
        "text": text,
        # Alignment scores are NOT recognition probabilities. Older caches
        # used the same key for both; never feed those scores to word deletion.
        "probability": raw.get("asr_probability") if raw.get("aligned_by") == "whisperx" else probability,
        "segment_end": bool(raw.get("segment_end", False)),
        "segment_complete": bool(raw.get("segment_complete", False)),
        "acoustic_silence_before": bool(raw.get("acoustic_silence_before", False)),
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
    chunk_start: int = 0,
) -> None:
    for boundary_index in range(1, len(offsets)):
        boundary_char = offsets[boundary_index - 1][1]
        if start_char < boundary_char < end_char:
            setattr(features[chunk_start + boundary_index], attribute, True)


def _pos_pair_is_protected(left_pos: str, right_pos: str) -> bool:
    pair = (left_pos, right_pos)
    return pair in {
        ("DET", "NOUN"), ("DET", "PROPN"), ("ADJ", "NOUN"), ("ADJ", "PROPN"),
        ("PRON", "AUX"), ("PRON", "VERB"), ("AUX", "VERB"), ("PART", "VERB"),
        ("CCONJ", "ADV"), ("ADP", "DET"), ("ADP", "NOUN"),
        ("ADP", "PROPN"), ("NUM", "NOUN"), ("PROPN", "PROPN"),
    }


def _lexical_pair(left: str, right: str) -> tuple[str, str]:
    return _last_lexical_word(left), _first_lexical_word(right)


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
        if abbreviation_continues(previous_text, words[index]["text"]):
            features[index].protected_by_abbreviation = True
            features[index].punctuation = ""
        # Whisper word timestamps can place a segment's first word several
        # seconds early. A timestamp gap alone is therefore evidence, not a
        # hard acoustic boundary. Only a separately verified VAD marker may
        # make the boundary uncrossable.
        features[index].forced_silence = bool(words[index].get("acoustic_silence_before"))

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

            # wtpsplit 2.2+ provides its own length-constrained Viterbi
            # segmentation. Treat those boundaries as strong recommendations
            # while retaining word timing hard limits in our final optimizer.
            try:
                recommended = sat_model.split(
                    text,
                    max_length=config.max_chars,
                    prior_type="gaussian",
                    prior_kwargs={
                        "target_length": min(config.preferred_max_chars, config.max_chars),
                        "spread": max(12, config.max_chars // 4),
                    },
                    algorithm="viterbi",
                )
                cursor = 0
                char_boundaries = []
                for part in list(recommended)[:-1]:
                    cursor += len(part)
                    char_boundaries.append(cursor)
                for char_boundary in char_boundaries:
                    nearest = min(
                        range(1, len(offsets)),
                        key=lambda local: abs(offsets[local - 1][1] - char_boundary),
                    )
                    features[chunk_start + nearest].sat_recommended = True
            except Exception as exc:
                features[chunk_start].previous_dependency += f"|sat-split-error:{type(exc).__name__}:{exc}"

        # These fixed expressions are reliable even if the optional spaCy
        # model is unavailable, so protect them independently of POS parsing.
        protected_phrases = {
            ("right", "now"),
            ("but", "then"),
        }
        for local_index in range(1, len(chunk_words)):
            left = chunk_words[local_index - 1]["text"]
            right = chunk_words[local_index]["text"]
            if _lexical_pair(left, right) in protected_phrases:
                features[chunk_start + local_index].protected_by_pos_pair = True

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
                        chunk_start,
                    )
                for entity in getattr(doc, "ents", []):
                    _mark_span_boundaries(
                        features,
                        offsets,
                        int(entity.start_char),
                        int(entity.end_char),
                        "protected_by_entity",
                        chunk_start,
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
                    if str(token.pos_) == 'PUNCT':
                        # "it." maps both a pronoun and '.' to the same ASR
                        # word. Keep the lexical dependency, not the last dot.
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
            cost_parts["grammar_protection"] = 110.0
        # A selected boundary contributes log((1-p)/p), which is the
        # non-constant part of the Bernoulli/Viterbi path cost. Unlike the old
        # -11*p reward, a near-zero SaT probability now strongly rejects cuts
        # such as "right | now" and "we | are".
        probability = min(1.0 - 1e-6, max(1e-6, boundary.sat_probability))
        cost_parts["sat_log_odds"] = 6.0 * math.log((1.0 - probability) / probability)
        if boundary.sat_recommended:
            cost_parts["sat_viterbi_reward"] = -45.0
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
            # A single ASR token may itself exceed a display limit (bad timing,
            # a URL, etc.). Keep it and report it rather than making the entire
            # film's path impossible and silently falling back to legacy cuts.
            if end > start + 1 and (duration > config.max_seconds or len(text) > config.max_chars):
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
        "algorithm": "semantic-viterbi-v2",
        "config": asdict(config),
        "decisions": decisions,
        "boundaries": [asdict(feature) for feature in features[1:-1]],
        "oversize_tokens": [
            {"index": i, "text": word["text"], "start": word["start"], "end": word["end"]}
            for i, word in enumerate(words)
            if word["end"] - word["start"] > config.max_seconds
            or len(word["text"]) > config.max_chars
        ],
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
        is_orphan_fragment = (
            len(lexical) == 1
            and not SENTENCE_END_RE.search(text)
            and duration < config.min_seconds
        )
        is_orphan_function_word = is_orphan_fragment and lexical[0] in (FUNCTION_WORDS | {"so"})

        if is_orphan_fragment and next_segment is not None:
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
            **{key: value for key, value in segment.items() if not key.startswith("_")},
            "start": float(segment["start"]),
            "end": float(segment["end"]),
            "text": " ".join(str(segment["text"]).split()),
            "translation": str(segment.get("translation", "")),
        }
        for segment in segments
        if str(segment.get("text", "")).strip()
    ]


def learning_boundary_protected(feature, config):
    if feature.protected_by_abbreviation:
        return True
    if not config.learning_soft_dependency_boundaries:
        return feature.protected
    if feature.protected_by_noun_chunk or feature.protected_by_entity or feature.protected_by_pos_pair:
        return True
    if not feature.protected_by_dependency:
        return False
    # Do not interpret any arc crossing this point as an unbreakable phrase.
    # Retain concrete complements and subject/predicate links; a semantic model
    # may override the other, softer arcs in unpunctuated conversational ASR.
    return (feature.next_dependency in {'dobj', 'obj', 'iobj', 'pobj', 'aux', 'auxpass', 'neg', 'prt', 'compound'}
            or (feature.previous_dependency in {'nsubj', 'nsubjpass', 'csubj'}
                and feature.next_pos in {'VERB', 'AUX'}))


def apply_speaker_evidence(words, features, speaker, config):
    """Project already validated evidence; ungated embedding-only models need text support."""
    rejected = []
    for boundary in speaker['boundaries']:
        index = boundary['word_boundary']
        if type(index) is not int or not 0 < index < len(words):
            raise ValueError('Invalid speaker word boundary')
        if speaker.get('requires_semantic_support'):
            last = _last_lexical_word(words[index-1]['text'])
            weak = last in (FUNCTION_WORDS | {'i','you','we','they','he','she','it'})
            # A lexical verb can finish a question even if the same spelling
            # also serves as an auxiliary. Require three independent signals:
            # acoustic turn, high sentence probability and restored punctuation.
            f = features[index]
            if (f.previous_pos == 'VERB' and f.previous_dependency == 'ROOT'
                    and f.sat_probability >= .9
                    and (f.restored_terminal_probability or 0) >= .8):
                weak = False
            if features[index].sat_probability < .1 or weak or learning_boundary_protected(features[index], config):
                rejected.append(index)
                continue
        features[index].acoustic_speaker_change = True
    return rejected


def learning_sentences(words, features, config):
    """Keep translation/practice units independent of display length limits.

    All input words are conserved in source order. Display cues carry word
    ranges, never independently translated fragments or inferred word times.
    """
    pronouns = {"i", "you", "we", "they", "he", "she", "it"}
    weak_ends = FUNCTION_WORDS | pronouns
    cuts = [0]
    warnings = []
    review_boundaries = set()
    for index in range(1, len(words)):
        feature = features[index]
        previous = _last_lexical_word(words[index-1]["text"])
        following = _first_lexical_word(words[index]["text"])
        incomplete = previous in weak_ends or learning_boundary_protected(feature, config)
        # Standalone "It!" etc. is possible: preservation wins; a high model
        # probability can override a lexical heuristic, but not a protected pair.
        strong = bool(feature.punctuation and feature.punctuation in ".!?")
        model_boundary = feature.sat_probability >= config.learning_boundary_probability
        restored_boundary = (
            config.learning_punctuation_threshold is not None
            and feature.restored_terminal_probability is not None
            and feature.restored_terminal_probability >= config.learning_punctuation_threshold
        )
        if (restored_boundary and feature.sat_probability >= config.learning_boundary_probability
                and feature.previous_dependency in {'dobj', 'obj', 'pobj', 'attr'}
                and feature.next_pos not in {'AUX', 'VERB', 'ADP', 'PART'}
                and not learning_boundary_protected(feature, config)):
            # An object pronoun can complete a clause ("learn from it.").
            # A subject followed by an auxiliary ("we are") remains protected.
            incomplete = False
        if (strong and model_boundary and feature.previous_dependency in {'dobj', 'obj', 'pobj', 'attr'}
                and not feature.protected_by_entity and not feature.protected_by_abbreviation):
            # POS adjacency is not a subject link across an explicit full stop:
            # "We can do this. We're ready." must not become a single sentence.
            incomplete = False
        # Dependency arcs sometimes span punctuation in noisy ASR text. Do not
        # merge two complete sentences merely because the parser spans them
        # (e.g. "more than that. Yeah, ..."). Protect a broken pronoun/auxiliary
        # or entity, but allow a normal multiword sentence ending in "that".
        strong_boundary = strong and not feature.protected_by_entity and (
            not incomplete or (model_boundary and not feature.protected_by_pos_pair) or (
                index-cuts[-1] >= 4 and not feature.protected_by_pos_pair
                and previous not in pronouns
            )
        )
        if feature.protected_by_abbreviation:
            strong_boundary = False
        long_gap = feature.gap >= config.learning_max_join_gap_seconds
        if long_gap and not feature.forced_silence:
            review_boundaries.add(index)
            warnings.append({'kind': 'long_word_gap_boundary', 'word_boundary': index,
                             'gap_seconds': feature.gap,
                             'reason': 'bounded learning unit; word gap is not verified silence'})
        speaker_boundary = config.learning_speaker_boundaries and feature.acoustic_speaker_change
        if speaker_boundary:
            # Even strong local audio evidence is still a model prediction.
            # Preserve a review flag instead of claiming a verified turn.
            review_boundaries.add(index)
            warnings.append({'kind': 'acoustic_speaker_boundary', 'word_boundary': index,
                             'semantic_conflict': bool(incomplete)})
        should_cut = speaker_boundary or feature.forced_silence or long_gap or (
            strong_boundary or ((model_boundary or restored_boundary) and not incomplete)
        )
        if should_cut:
            cuts.append(index)
        elif index - cuts[-1] >= config.learning_max_words:
            # Translation-model context safety, not a 12-second display limit.
            # Choose a clause boundary and explicitly report the forced split.
            candidates = list(range(cuts[-1]+1, index+1))
            safe = [i for i in candidates if not features[i].protected
                    and _last_lexical_word(words[i-1]["text"]) not in weak_ends]
            candidates = safe or candidates
            selected = max(candidates, key=lambda i: (
                features[i].sat_probability + (.25 if features[i].punctuation else 0)
                + min(max(features[i].gap, 0), 1) * .1,
                i,
            ))
            cuts.append(selected)
            warnings.append({"kind": "learning_context_limit", "word_boundary": selected})
    cuts.append(len(words))
    sentences = []
    for sentence_id, (start, end) in enumerate(zip(cuts, cuts[1:])):
        selected = words[start:end]
        local_features = [BoundaryFeatures(**asdict(item)) for item in features[start:end+1]]
        cues, cue_debug = optimize_segments(selected, local_features, config)
        display = [{"start": cue["start"], "end": cue["end"], "text": cue["text"],
                    "word_start": start + cue["_word_start"],
                    "word_end": start + cue["_word_end"],
                    "learning_sentence_id": sentence_id} for cue in cues]
        warnings.extend({**item, "kind": "oversize_token"} for item in cue_debug["oversize_tokens"])
        unresolved = sum(word.get("alignment_status", "aligned") != "aligned" for word in selected)
        text_review = sum(bool(word.get("recovered") or word.get("recovery_review_required")) for word in selected)
        sentences.append({"start": selected[0]["start"], "end": max(word["end"] for word in selected),
                          "text": words_to_text(selected), "translation": "",
                          "learning_sentence_id": sentence_id,
                          "boundary_review_required": start in review_boundaries or end in review_boundaries,
                          "alignment_review_required": bool(unresolved),
                          "alignment_review_word_count": unresolved,
                          "text_review_required": bool(text_review), "text_review_word_count": text_review,
                          "word_start": start, "word_end": end, "display_cues": display})
    return sentences, {"algorithm": "learning-sentence-experiment-v2", "config": asdict(config),
                       "word_count": len(words), "segment_count": len(sentences),
                       "warnings": warnings, "cuts": cuts,
                       "boundaries": [asdict(f) for f in features[1:-1]],
                       "removed_orphans": []}


def segment_words(
    raw_words: Iterable[dict[str, Any]],
    sat_model: Any = None,
    spacy_nlp: Any = None,
    config: SegmenterConfig | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    config = config or SegmenterConfig()
    words = normalize_words(raw_words)
    if not words:
        return [], {"algorithm": "semantic-viterbi-v2", "error": "no words"}
    features = analyze_boundaries(words, sat_model=sat_model, spacy_nlp=spacy_nlp, config=config)
    if config.learning_sentence_mode:
        return learning_sentences(words, features, config)
    segments, debug = optimize_segments(words, features, config)
    segments, removed = filter_orphan_function_words(segments, config)
    debug["removed_orphans"] = removed
    debug["word_count"] = len(words)
    debug["segment_count"] = len(segments)
    return clean_segments(segments), debug
