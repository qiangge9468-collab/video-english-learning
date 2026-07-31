import importlib.util
import sys
import unittest
from pathlib import Path


TOOLS_ROOT = Path(r"C:\tmp\video-english-learning-remote\tools")
VERSION_DIR = TOOLS_ROOT / "versions" / "v2.0.6"
SERVICE_PATH = VERSION_DIR / "service.py"
if str(VERSION_DIR) not in sys.path:
    sys.path.insert(0, str(VERSION_DIR))


def load_service():
    sys.modules.pop("durable_job_store", None)
    spec = importlib.util.spec_from_file_location("local_whisper_service_v206_quality_test", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class CaptionQualityV206Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_service()

    def test_version_isolated_and_official_compression_threshold_restored(self):
        self.assertEqual(self.service.SERVICE_VERSION, "2.0.6")
        self.assertEqual(self.service.SEGMENTER_VERSION, "semantic-viterbi-v2")
        self.assertEqual(self.service.WHISPER_COMPRESSION_RATIO_THRESHOLD, 2.4)
        self.assertIn("service_data_v2.0.6", self.service.SERVICE_DATA_DIR)
        self.assertIn("whisperx", self.service.PIPELINE_REVISION)
        self.assertTrue((TOOLS_ROOT / "versions" / "v2.0.5" / "service.py").is_file())

    def test_whisperx_is_required_on_cuda_and_runs_before_semantic_segmentation(self):
        source = SERVICE_PATH.read_text(encoding="utf-8")
        launcher = (VERSION_DIR / "start_service.ps1").read_text(encoding="utf-8")
        worker = (VERSION_DIR / "whisperx_worker.py").read_text(encoding="utf-8")
        self.assertTrue(self.service.WHISPERX_REQUIRED)
        self.assertEqual(self.service.WHISPERX_DEVICE, "cuda")
        self.assertLess(
            source.index("run_whisperx_alignment("),
            source.index("run_semantic_worker(raw_words)"),
        )
        self.assertIn('aligned_by": "whisperx"', worker)
        self.assertIn('$env:WHISPERX_REQUIRED = "1"', launcher)
        self.assertIn('$env:WHISPERX_DEVICE = "cuda"', launcher)
        self.assertIn("torch.cuda.is_available()", launcher)
        self.assertIn("m.version('whisperx') == '3.8.6'", launcher)

    def test_failed_high_temperature_fallback_is_removed_before_recovery(self):
        segments = [
            {
                "id": 0,
                "start": 1056.0,
                "end": 1059.0,
                "text": "...I fe parts.",
                "avg_logprob": -4.4598,
                "temperature": 1.0,
            },
            {
                "id": 1,
                "start": 1060.0,
                "end": 1062.0,
                "text": "Basically stuck in Gunza.",
                "avg_logprob": -0.2,
                "temperature": 0.0,
            },
        ]
        words = [
            {"segment_id": 0, "start": 1056.0, "end": 1056.2, "text": "...I", "probability": 0.01},
            {"segment_id": 0, "start": 1056.2, "end": 1056.5, "text": "fe", "probability": 0.02},
            {"segment_id": 0, "start": 1056.5, "end": 1057.0, "text": "parts.", "probability": 0.01},
            {"segment_id": 1, "start": 1060.0, "end": 1060.5, "text": "Basically", "probability": 0.96},
            {"segment_id": 1, "start": 1060.5, "end": 1061.0, "text": "stuck", "probability": 0.97},
        ]
        kept_segments, kept_words, rejected = self.service.discard_unreliable_first_pass_segments(
            segments, words
        )
        self.assertEqual([item["text"] for item in kept_segments], ["Basically stuck in Gunza."])
        self.assertEqual([item["text"] for item in rejected], ["...I fe parts."])
        self.assertTrue(all(item["text"] not in {"...I", "fe", "parts."} for item in kept_words))

    def test_known_bad_boundaries_score_as_errors(self):
        cases = [
            ([{"text": "Made"}, {"text": "It to Gyabla."}], "single-word fragment"),
            ([{"text": "But"}, {"text": "Then, somewhere along the way."}], "fixed phrase split"),
            ([{"text": "that we"}, {"text": "Are gonna progress to base camp."}], "pronoun-auxiliary split"),
            ([{"text": "Right"}, {"text": "Now, we are basically stuck."}], "fixed phrase split"),
        ]
        for segments, expected_reason in cases:
            with self.subTest(segments=segments):
                penalty, details = self.service.segmentation_quality_penalty(segments)
                self.assertGreater(penalty, 0)
                self.assertIn(expected_reason, [item["reason"] for item in details])

    def test_place_name_correction_is_scoped_to_matching_video(self):
        title = "Hiking to Kanchenjunga Base Camp in Nepal.mp4"
        self.assertEqual(
            self.service.correct_recognized_caption_text(
                "Right now, we are basically stuck in Gunza.", title
            ),
            "Right now, we are basically stuck in Ghunsa.",
        )
        self.assertEqual(
            self.service.correct_recognized_caption_text(
                "Made it to Kiabla. Right now we are stuck in Gunsa.", title
            ),
            "Made it to Gyabla. Right now we are stuck in Ghunsa.",
        )
        self.assertEqual(
            self.service.correct_recognized_caption_text("The company is in Gunza.", "Business.mp4"),
            "The company is in Gunza.",
        )


if __name__ == "__main__":
    unittest.main()
