import importlib.util
import queue
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock


ROOT = Path(__file__).resolve().parents[3]
VERSION_DIR = ROOT / "tools" / "versions" / "v2.1.0"
SERVICE_PATH = VERSION_DIR / "service.py"


def load_service():
    sys.modules.pop("durable_job_store", None)
    sys.path.insert(0, str(VERSION_DIR))
    spec = importlib.util.spec_from_file_location("timeline_quality_v210", SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def make_words(segment_id, text):
    return [
        {
            "segment_id": segment_id,
            "start": index * 0.2,
            "end": index * 0.2 + 0.15,
            "text": token,
            "probability": 0.95,
        }
        for index, token in enumerate(text.split())
    ]


class TimelineQualityV210Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.service = load_service()

    def tearDown(self):
        self.service._models.clear()
        self.service._translator = None
        self.service._models_last_used_at = 0.0
        while True:
            try:
                self.service._job_queue.get_nowait()
                self.service._job_queue.task_done()
            except queue.Empty:
                break

    def test_repeated_whisper_loop_is_rejected_even_with_high_confidence(self):
        prefix = "quotes came in each was more expensive than the last"
        loop = " and we're going to do it" * 8
        text = prefix + loop
        segment = {
            "id": 0, "start": 370.0, "end": 400.0, "text": text,
            "avg_logprob": -0.13, "compression_ratio": 2.36, "temperature": 0.8,
        }
        kept, words, rejected = self.service.discard_unreliable_first_pass_segments(
            [segment], make_words(0, text)
        )
        self.assertEqual(kept, [])
        self.assertEqual(words, [])
        self.assertEqual(rejected[0]["reason"], "pathological repeated phrase loop")
        self.assertGreaterEqual(rejected[0]["repeated_phrase"]["occurrences"], 3)

    def test_legitimate_exercise_count_repetition_is_not_a_phrase_loop(self):
        text = ("one two three four five " * 6).strip()
        self.assertIsNone(self.service.pathological_repeated_phrase(text))

    def test_long_numeric_recovery_hallucination_is_detected(self):
        self.assertTrue(self.service.implausible_count_sequence(
            "11, 12, 13, 14, 15, 16, 17, 18, 19, 20, 21, 22, 23, 24"
        ))
        self.assertFalse(self.service.implausible_count_sequence("$4,000, $5,000 and $6,000"))
        self.assertFalse(self.service.implausible_count_sequence("one two three four five"))

    def test_primary_long_audio_decode_does_not_condition_on_previous_text(self):
        source = SERVICE_PATH.read_text(encoding="utf-8")
        primary = source[source.index("segments, info = model.transcribe("):]
        primary = primary[:primary.index("duration = float(")]
        self.assertIn("condition_on_previous_text=False", primary)
        self.assertNotIn("condition_on_previous_text=True", primary)

    def test_idle_release_unloads_whisper_and_drops_translation_closure(self):
        backend = SimpleNamespace(model_is_loaded=True)
        def unload_model():
            backend.model_is_loaded = False
        backend.unload_model = unload_model
        self.service._models["large"] = SimpleNamespace(model=backend)
        self.service._translator = lambda texts: texts
        self.service._models_last_used_at = 10.0
        with mock.patch.object(self.service, "write_runtime_status") as status:
            released = self.service.release_idle_models(now=10.0 + self.service.MODEL_IDLE_TIMEOUT_SECONDS + 1)
        self.assertTrue(released)
        self.assertFalse(backend.model_is_loaded)
        self.assertIsNone(self.service._translator)
        status.assert_called_once()

    def test_idle_release_waits_for_warm_timeout_and_empty_queue(self):
        backend = SimpleNamespace(model_is_loaded=True, unload_model=mock.Mock())
        self.service._models["large"] = SimpleNamespace(model=backend)
        self.service._models_last_used_at = 100.0
        self.assertFalse(self.service.release_idle_models(now=101.0))
        self.service._job_queue.put("next")
        self.assertFalse(self.service.release_idle_models(force=False, now=1000.0))
        backend.unload_model.assert_not_called()

    def test_cached_whisper_backend_reloads_after_idle_unload(self):
        backend = SimpleNamespace(model_is_loaded=False, load_model=mock.Mock())
        wrapper = SimpleNamespace(model=backend)
        self.service._models["large"] = wrapper
        with mock.patch.dict(self.service.os.environ, {"WHISPER_MODEL": "large"}):
            self.assertIs(self.service.get_whisper_model(), wrapper)
        backend.load_model.assert_called_once()


if __name__ == "__main__":
    unittest.main()
