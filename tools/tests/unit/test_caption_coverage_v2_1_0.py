import importlib.util
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
VERSION_DIR = ROOT / "tools" / "versions" / "v2.1.0"
SERVICE_PATH = VERSION_DIR / "service.py"


def load_service():
    sys.modules.pop("durable_job_store", None)
    sys.path.insert(0, str(VERSION_DIR))
    spec = importlib.util.spec_from_file_location("caption_coverage_v210", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def word(start, text, probability=0.95):
    return SimpleNamespace(start=start, end=start + 0.2, word=text, probability=probability)


class CaptionCoverageV210Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_service()

    def test_short_count_with_good_segment_score_is_not_rejected(self):
        segments = [{"id": 0, "start": 540.8, "end": 541.1, "text": "Two.",
                     "avg_logprob": -0.096, "temperature": 0.0}]
        words = [{"segment_id": 0, "start": 540.8, "end": 541.1,
                  "text": "Two.", "probability": 0.075}]
        kept_segments, kept_words, rejected = self.service.discard_unreliable_first_pass_segments(segments, words)
        self.assertEqual(rejected, [])
        self.assertEqual(kept_segments[0]["text"], "Two.")
        self.assertEqual(kept_words[0]["text"], "Two.")

    def test_vad_interval_difference_finds_short_and_edge_speech_only(self):
        words = [{"start": 1.0, "end": 1.2, "text": "hello"},
                 {"start": 2.0, "end": 2.2, "text": "again"}]
        speech = [(0.0, 0.9), (1.4, 1.9), (2.5, 3.4)]
        gaps = self.service.find_uncovered_speech_gaps(words, speech, 3.4)
        self.assertEqual(gaps, [(0.0, 0.8), (2.5, 3.4)])

    def test_full_audio_count_pass_adds_counts_and_rejects_runaway_repetition(self):
        valid = SimpleNamespace(start=20.0, end=22.0, text="one two three", avg_logprob=-0.2,
            no_speech_prob=0.05, compression_ratio=1.0,
            words=[word(20.0, "one"), word(20.7, "two"), word(21.4, "three")])
        repeated = SimpleNamespace(start=30.0, end=32.0,
            text=" ".join("one" for _ in range(13)), avg_logprob=-0.1,
            no_speech_prob=0.01, compression_ratio=3.0,
            words=[word(30.0 + index * 0.1, "one") for index in range(13)])
        model = SimpleNamespace(transcribe=lambda *args, **kwargs: (iter([valid, repeated]), None))
        segments = [{"id": 0, "start": 5.0, "end": 6.0, "text": "Ready.", "avg_logprob": -0.1}]
        words = [{"segment_id": 0, "start": 5.0, "end": 5.5, "text": "Ready.", "probability": 0.95}]
        for index, text in enumerate(("one", "two", "three", "four", "five", "one", "two", "three"), start=1):
            words.append({"segment_id": 0, "start": 5.0 + index * 0.1,
                          "end": 5.05 + index * 0.1, "text": text, "probability": 0.95})
        _segments, merged, debug = self.service.recover_missing_spoken_counts(
            model, "unused.m4a", segments, words, "en", "Exercise tutorial.mp4")
        recovered = [item for item in merged if item.get("recovery_source")]
        self.assertEqual([item["text"] for item in recovered], ["one", "two", "three"])
        self.assertEqual(len(debug["rejected_repetitions"]), 1)

    def test_count_recovery_runs_before_whisperx_and_semantic_segmentation(self):
        source = SERVICE_PATH.read_text(encoding="utf-8")
        pipeline = source[source.index("def transcribe("):]
        self.assertLess(pipeline.index("recover_missing_spoken_counts("), pipeline.index("run_whisperx_alignment("))
        self.assertLess(pipeline.index("run_whisperx_alignment("), pipeline.index("run_semantic_worker(raw_words)"))
        self.assertIn("speech-coverage-3", self.service.PIPELINE_REVISION)


if __name__ == "__main__":
    unittest.main()