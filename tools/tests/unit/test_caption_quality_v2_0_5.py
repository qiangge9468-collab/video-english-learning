import importlib.util
import os
import unittest
from pathlib import Path
from unittest import mock


SERVICE_PATH = Path(__file__).resolve().parents[2] / "versions" / "v2.0.5" / "service.py"


def load_service():
    import sys
    sys.modules.pop("durable_job_store", None)
    spec = importlib.util.spec_from_file_location("local_whisper_service_v205_quality_test", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaptionQualityFixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_service()

    def test_non_outdoor_title_is_keywords_only(self):
        prompt, hotwords = self.service.build_transcription_context(
            "How to AIRFLARE 20 Minutes FOLLOW ALONG Tutorial.mp4"
        )
        self.assertEqual(prompt, "Clear English captions.")
        self.assertIn("AIRFLARE", hotwords)
        self.assertNotIn("How to AIRFLARE 20 Minutes FOLLOW ALONG Tutorial", hotwords)
        self.assertNotIn("travel", prompt.lower())
        self.assertNotIn("hiking", prompt.lower())

    def test_outdoor_title_enables_outdoor_context_without_full_title_echo(self):
        prompt, hotwords = self.service.build_transcription_context(
            "Hiking to Kanchenjunga Base Camp.mp4"
        )
        self.assertIn("outdoor", prompt.lower())
        self.assertIn("Kanchenjunga", hotwords)
        self.assertIn("Dyneema", hotwords)
        self.assertNotIn("The video title is", prompt)

    def test_vad_speech_gap_is_detected_between_words(self):
        words = [
            {"start": 48.36, "end": 52.26, "text": "routine."},
            {"start": 62.38, "end": 62.50, "text": "and"},
        ]
        gaps = self.service.find_uncovered_speech_gaps(words, [(0.0, 87.67)])
        self.assertEqual(len(gaps), 1)
        self.assertAlmostEqual(gaps[0][0], 52.26, places=2)
        self.assertAlmostEqual(gaps[0][1], 62.38, places=2)

    def test_video_title_echo_is_rejected(self):
        title = "How to AIRFLARE 20 Minutes FOLLOW ALONG Tutorial.mp4"
        self.assertTrue(self.service.looks_like_prompt_echo(
            "How to AIRFLARE 20 Minutes FOLLOW ALONG Tutorial", title
        ))
        self.assertFalse(self.service.looks_like_prompt_echo(
            "You can still practice this routine but do not push too hard.", title
        ))

    def test_numeric_countdowns_and_urls_are_deterministic(self):
        self.assertEqual(self.service.deterministic_caption_translation("1, 2, 3,"), "1\u30012\u30013")
        self.assertEqual(self.service.deterministic_caption_translation("Three, two, one."), "3\u30012\u30011\u3002")
        self.assertEqual(self.service.deterministic_caption_translation("www.airflare.com"), "www.airflare.com")
        self.assertIsNone(self.service.deterministic_caption_translation("1, Let's go."))

    def test_degenerate_translation_is_detected(self):
        repeated = "\u4e00\u3001\u4e8c\u3001\u4e09\u3001" + "\u4e09\u3001" * 90
        self.assertTrue(self.service.translation_is_degenerate("1, 2, 3,", repeated))
        self.assertTrue(self.service.translation_is_degenerate("www.airflare.com", "\u7f51\u5740\u7f51\u5740\u7f51\u5740" * 30))
        self.assertFalse(self.service.translation_is_degenerate("Ready?", "\u51c6\u5907\u597d\u4e86\u5417\uff1f"))

    def test_incomplete_clause_and_missing_numbers_are_detected(self):
        first_source = (
            "It actually does remind me a lot of the Annapurna circuit because also "
            "with that trek you start at a very low elevation"
        )
        second_source = (
            "Compare that to the Annapurna circuit which sees around 15 to 20 thousand"
        )
        self.assertTrue(self.service.translation_is_incomplete(
            first_source, "\u5b83\u786e\u5b9e\u8ba9\u6211\u60f3\u8d77\u4e86\u5b89\u7eb3\u666e\u5c14\u7eb3\u8d5b\u9053\uff0c"
        ))
        self.assertTrue(self.service.translation_is_incomplete(
            second_source, "\u4e0e\u5b89\u7eb3\u666e\u5c14\u7eb3\u7535\u8def\u76f8\u6bd4\u3002"
        ))
        self.assertFalse(self.service.translation_is_incomplete(
            first_source,
            "\u5b83\u786e\u5b9e\u8ba9\u6211\u60f3\u8d77\u4e86\u5b89\u7eb3\u666e\u5c14\u7eb3\u73af\u7ebf\uff0c"
            "\u56e0\u4e3a\u90a3\u6761\u5f92\u6b65\u8def\u7ebf\u4e5f\u662f\u4ece\u5f88\u4f4e\u7684\u6d77\u62d4\u5f00\u59cb\u3002",
        ))

    def test_thousand_range_is_expanded_before_translation(self):
        source = (
            "Compare that to the Annapurna circuit which sees around 15 to 20 thousand"
        )
        prepared = self.service.prepare_caption_for_translation(source)
        self.assertIn("15,000 to 20,000", prepared)

    def test_numeric_only_batch_skips_model(self):
        with mock.patch.object(self.service, "get_translator", side_effect=AssertionError("model should not load")):
            result = self.service.translate_texts(["1, 2, 3,", "3, 2, 1."])
        self.assertEqual(result, ["1\u30012\u30013", "3\u30012\u30011\u3002"])

    def test_bad_model_output_falls_back_without_cache_poisoning(self):
        translator = lambda texts: ["\u91cd\u590d" * 100 for _ in texts]
        with mock.patch.object(self.service, "get_translator", return_value=translator):
            result = self.service.translate_texts(["Ready for the next exercise?"])
        self.assertEqual(result, ["Ready for the next exercise?"])

    def test_incomplete_model_output_falls_back_without_cache_poisoning(self):
        source = (
            "Compare that to the Annapurna circuit which sees around 15 to 20 thousand"
        )
        translator = lambda texts: ["\u4e0e\u5b89\u7eb3\u666e\u5c14\u7eb3\u7535\u8def\u76f8\u6bd4\u3002" for _ in texts]
        with mock.patch.object(self.service, "get_translator", return_value=translator):
            result = self.service.translate_texts([source])
        self.assertEqual(result, [source])

    def test_old_cache_revision_is_not_reused(self):
        store = mock.Mock()
        store.load_artifact.return_value = {"revision": "older"}
        with mock.patch.object(self.service, "JOB_STORE", store):
            self.assertFalse(self.service.cache_revision_is_current("a" * 64))
        store.load_artifact.return_value = {"revision": self.service.PIPELINE_REVISION}
        with mock.patch.object(self.service, "JOB_STORE", store):
            self.assertTrue(self.service.cache_revision_is_current("a" * 64))


if __name__ == "__main__":
    unittest.main()
