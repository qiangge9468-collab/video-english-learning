import sys
import unittest
from pathlib import Path


VERSION_DIR = Path(r"C:\tmp\video-english-learning-remote\tools\versions\v2.0.6")
if str(VERSION_DIR) not in sys.path:
    sys.path.insert(0, str(VERSION_DIR))

from semantic_caption_segmenter_v206 import (
    BoundaryFeatures,
    SegmenterConfig,
    analyze_boundaries,
    normalize_words,
    optimize_segments,
)


def words_with_times(items):
    return normalize_words(
        [
            {
                "index": index,
                "start": start,
                "end": end,
                "text": text,
                "probability": 0.95,
            }
            for index, (text, start, end) in enumerate(items)
        ]
    )


class SemanticCaptionSegmenterV206Tests(unittest.TestCase):
    def test_fake_whisper_gap_does_not_force_made_it_split(self):
        words = words_with_times(
            [
                ("Made", 755.94, 756.16),
                ("it", 760.98, 761.12),
                ("to", 761.12, 761.30),
                ("Gyabla.", 761.30, 762.10),
            ]
        )
        features = analyze_boundaries(
            words,
            config=SegmenterConfig(min_seconds=0.1, target_seconds=5.0),
        )
        self.assertGreater(features[1].gap, 4.0)
        self.assertFalse(features[1].forced_silence)
        segments, _debug = optimize_segments(
            words,
            features,
            SegmenterConfig(min_seconds=0.1, target_seconds=5.0),
        )
        self.assertEqual([item["text"] for item in segments], ["Made it to Gyabla."])

    def test_fake_whisper_gap_does_not_force_but_then_split(self):
        words = words_with_times(
            [
                ("But", 860.35, 860.87),
                ("then,", 866.91, 867.18),
                ("somewhere", 867.18, 867.70),
                ("along", 867.70, 868.00),
                ("the", 868.00, 868.20),
                ("way.", 868.20, 868.70),
            ]
        )
        features = analyze_boundaries(
            words,
            config=SegmenterConfig(min_seconds=0.1, target_seconds=6.0),
        )
        self.assertFalse(features[1].forced_silence)
        self.assertTrue(features[1].protected)
        segments, _debug = optimize_segments(
            words,
            features,
            SegmenterConfig(min_seconds=0.1, target_seconds=6.0),
        )
        self.assertFalse(any(item["text"] == "But" for item in segments))
        self.assertTrue(any(item["text"].startswith("But then") for item in segments))

    def test_verified_acoustic_silence_remains_a_hard_boundary(self):
        words = words_with_times(
            [
                ("Before", 0.0, 0.4),
                ("silence.", 0.5, 1.0),
                ("After", 4.0, 4.4),
                ("silence.", 4.5, 5.0),
            ]
        )
        words[2]["acoustic_silence_before"] = True
        features = analyze_boundaries(
            words,
            config=SegmenterConfig(min_seconds=0.1, target_seconds=3.0),
        )
        self.assertTrue(features[2].forced_silence)

    def test_pronoun_auxiliary_boundary_is_strongly_protected(self):
        words = words_with_times(
            [
                ("that", 0.0, 0.3),
                ("we", 0.3, 0.6),
                ("are", 0.6, 0.9),
                ("gonna", 0.9, 1.2),
                ("progress", 1.2, 1.6),
                ("to", 1.6, 1.8),
                ("base", 1.8, 2.1),
                ("camp.", 2.1, 2.5),
            ]
        )
        features = [BoundaryFeatures(index=index, sat_probability=0.5) for index in range(len(words) + 1)]
        features[2].protected_by_dependency = True
        segments, _debug = optimize_segments(
            words,
            features,
            SegmenterConfig(min_seconds=0.1, target_seconds=0.7, max_seconds=2.5),
        )
        texts = [item["text"].lower() for item in segments]
        self.assertFalse(any(text.endswith(" we") for text in texts))
        self.assertFalse(any(text.startswith("are ") for text in texts))


if __name__ == "__main__":
    unittest.main()
