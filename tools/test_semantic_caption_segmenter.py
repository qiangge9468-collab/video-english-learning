import unittest

from semantic_caption_segmenter import (
    BoundaryFeatures,
    SegmenterConfig,
    filter_orphan_function_words,
    normalize_words,
    optimize_segments,
    words_to_text,
)


def timed_words(text, step=0.35, probabilities=None):
    words = []
    cursor = 0.0
    for index, token in enumerate(text.split()):
        words.append(
            {
                "index": index,
                "start": cursor,
                "end": cursor + step * 0.8,
                "text": token,
                "probability": (
                    probabilities[index] if probabilities is not None else 0.95
                ),
            }
        )
        cursor += step
    return normalize_words(words)


class SemanticCaptionSegmenterTests(unittest.TestCase):
    def test_text_spacing(self):
        words = timed_words("This beautiful river, is clear.")
        self.assertEqual(words_to_text(words), "This beautiful river, is clear.")

    def test_protected_noun_phrase_is_not_split(self):
        words = timed_words(
            "So you get a lot of variety on the trek so right now "
            "we are walking alongside this beautiful river like it has jungly vibes"
        )
        features = [BoundaryFeatures(index=i) for i in range(len(words) + 1)]
        beautiful = next(i for i, word in enumerate(words) if word["text"] == "beautiful")
        features[beautiful + 1].sat_probability = 0.99
        features[beautiful + 1].protected_by_noun_chunk = True
        river = beautiful + 1
        features[river + 1].sat_probability = 0.90

        segments, _debug = optimize_segments(
            words,
            features,
            SegmenterConfig(max_seconds=8.0, max_words=22, max_chars=125),
        )
        texts = [segment["text"] for segment in segments]
        self.assertFalse(any(text.endswith("beautiful") for text in texts))
        self.assertTrue(any("beautiful river" in text for text in texts))

    def test_low_confidence_isolated_the_is_removed(self):
        segments = [
            {
                "start": 384.75,
                "end": 385.39,
                "text": "The",
                "_avg_word_probability": 0.31,
            },
            {
                "start": 408.35,
                "end": 410.90,
                "text": "Next morning things started to feel real.",
                "_avg_word_probability": 0.98,
            },
        ]
        kept, removed = filter_orphan_function_words(segments)
        self.assertEqual([item["text"] for item in kept], ["Next morning things started to feel real."])
        self.assertEqual([item["text"] for item in removed], ["The"])

    def test_high_confidence_isolated_word_is_not_deleted(self):
        segments = [
            {
                "start": 10.0,
                "end": 10.7,
                "text": "The",
                "_avg_word_probability": 0.96,
            }
        ]
        kept, removed = filter_orphan_function_words(segments)
        self.assertEqual(len(kept), 1)
        self.assertEqual(removed, [])

    def test_absolute_silence_cannot_be_crossed(self):
        words = timed_words("Before silence after silence", step=0.5)
        words[2]["start"] = 5.0
        words[2]["end"] = 5.4
        words[3]["start"] = 5.5
        words[3]["end"] = 5.9
        features = [BoundaryFeatures(index=i) for i in range(len(words) + 1)]
        features[2].gap = 4.1
        features[2].forced_silence = True
        segments, _debug = optimize_segments(
            words,
            features,
            SegmenterConfig(min_seconds=0.1, target_seconds=2.0),
        )
        self.assertEqual([segment["text"] for segment in segments], ["Before silence", "after silence"])

    def test_explicit_sentence_punctuation_cannot_be_crossed(self):
        words = timed_words("Perfect weather. I'm just so glad to be out here.", step=0.45)
        features = [BoundaryFeatures(index=i) for i in range(len(words) + 1)]
        features[2].punctuation = "."
        features[len(words)].punctuation = "."
        segments, _debug = optimize_segments(
            words,
            features,
            SegmenterConfig(min_seconds=0.1, target_seconds=4.0),
        )
        texts = [segment["text"] for segment in segments]
        self.assertEqual(texts[0], "Perfect weather.")
        self.assertFalse(any(". I'm" in text for text in texts))

    def test_weak_function_word_ending_is_avoided(self):
        words = timed_words("Today as we go on a camping and hiking trip", step=0.45)
        features = [BoundaryFeatures(index=i) for i in range(len(words) + 1)]
        segments, _debug = optimize_segments(
            words,
            features,
            SegmenterConfig(min_seconds=0.1, target_seconds=3.0),
        )
        self.assertFalse(any(segment["text"].lower().endswith(" as we") for segment in segments))

    def test_short_conjunction_is_merged_into_next_segment(self):
        segments = [
            {
                "start": 60.16,
                "end": 60.97,
                "text": "And",
                "_avg_word_probability": 0.97,
                "_word_start": 0,
            },
            {
                "start": 62.47,
                "end": 67.68,
                "text": "pretty quickly we realized there is not much easing into it.",
                "_avg_word_probability": 0.98,
                "_word_start": 1,
            },
        ]
        kept, removed = filter_orphan_function_words(segments)
        self.assertEqual(len(kept), 1)
        self.assertEqual(
            kept[0]["text"],
            "And pretty quickly we realized there is not much easing into it.",
        )
        self.assertEqual(removed, [])

    def test_short_discourse_marker_is_merged_across_pause_within_limits(self):
        segments = [
            {"start": 10.16, "end": 11.01, "text": "So", "_avg_word_probability": 0.96},
            {
                "start": 15.13,
                "end": 19.43,
                "text": "we are kicking things off with a bit of elevation gain.",
                "_avg_word_probability": 0.98,
            },
        ]
        kept, removed = filter_orphan_function_words(segments)
        self.assertEqual(len(kept), 1)
        self.assertTrue(kept[0]["text"].startswith("So we are"))
        self.assertEqual(removed, [])


if __name__ == "__main__":
    unittest.main()
