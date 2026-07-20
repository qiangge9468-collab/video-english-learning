import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path
from unittest import mock


SERVICE_PATH = Path(__file__).with_name("local_whisper_service.py")


def load_service():
    module_name = "local_whisper_service_under_test"
    spec = importlib.util.spec_from_file_location(module_name, SERVICE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ModelRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.service = load_service()

    def test_project_local_nllb_is_the_default(self):
        expected = str(SERVICE_PATH.parent.parent / "models" / "nllb-200-distilled-600M")
        self.assertEqual(os.path.normcase(os.path.abspath(self.service.DEFAULT_TRANSLATION_MODEL)), os.path.normcase(expected))

    def test_translation_auto_device_selects_cuda(self):
        torch_module = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: True))
        self.assertEqual(self.service.resolve_translation_device(torch_module, "auto"), "cuda")

    def test_translation_auto_device_falls_back_to_cpu(self):
        torch_module = types.SimpleNamespace(cuda=types.SimpleNamespace(is_available=lambda: False))
        self.assertEqual(self.service.resolve_translation_device(torch_module, "auto"), "cpu")

    def test_whisper_auto_device_selects_cuda(self):
        fake_ctranslate2 = types.SimpleNamespace(get_cuda_device_count=lambda: 1)
        with mock.patch.dict(sys.modules, {"ctranslate2": fake_ctranslate2}):
            self.assertEqual(self.service.resolve_whisper_device("auto"), "cuda")

    def test_large_v3_auto_compute_uses_int8_float16(self):
        model = str(SERVICE_PATH.parent.parent / "models" / "faster-whisper-large-v3")
        self.assertEqual(self.service.resolve_whisper_compute_type("auto", "cuda", model), "int8_float16")
        self.assertEqual(self.service.resolve_whisper_compute_type("auto", "cpu", model), "int8")

    def test_large_v3_is_the_default_english_model(self):
        expected = str(SERVICE_PATH.parent.parent / "models" / "faster-whisper-large-v3")
        with mock.patch.dict(os.environ, {"WHISPER_ENGLISH_MODEL": "large-v3"}):
            selected = self.service.choose_transcription_model("en")
        self.assertEqual(os.path.normcase(os.path.abspath(selected)), os.path.normcase(expected))

    def test_nllb_translation_uses_target_language_and_gpu(self):
        class FakeTensor:
            def __init__(self):
                self.device = None

            def to(self, device):
                self.device = device
                return self

        class FakeTokenizer:
            unk_token_id = 0
            src_lang = None

            @classmethod
            def from_pretrained(cls, *_args, **_kwargs):
                return cls()

            def convert_tokens_to_ids(self, token):
                return 256047 if token == "zho_Hans" else self.unk_token_id

            def __call__(self, texts, **_kwargs):
                self.last_texts = texts
                return {"input_ids": FakeTensor()}

            def batch_decode(self, _generated, **_kwargs):
                return ["你好"]

        class FakeModel:
            config = types.SimpleNamespace(model_type="m2m_100")

            def __init__(self):
                self.device = None
                self.dtype = None
                self.generate_options = None

            @classmethod
            def from_pretrained(cls, *_args, **_kwargs):
                instance = cls()
                fake_transformers.model = instance
                return instance

            def to(self, device=None, dtype=None):
                self.device = device
                self.dtype = dtype
                return self

            def eval(self):
                return self

            def generate(self, **kwargs):
                self.generate_options = kwargs
                return [[1]]

        class InferenceMode:
            def __enter__(self):
                return None

            def __exit__(self, *_args):
                return False

        fake_torch = types.SimpleNamespace(
            cuda=types.SimpleNamespace(is_available=lambda: True),
            float16="float16",
            inference_mode=InferenceMode,
        )
        fake_transformers = types.SimpleNamespace(
            AutoTokenizer=FakeTokenizer,
            AutoModelForSeq2SeqLM=FakeModel,
            model=None,
        )

        with mock.patch.dict(sys.modules, {"torch": fake_torch, "transformers": fake_transformers}):
            translator = self.service.build_transformers_translator()
            self.assertEqual(translator(["Hello"]), ["你好"])

        model = fake_transformers.model
        self.assertEqual(model.device, "cuda")
        self.assertEqual(model.dtype, "float16")
        self.assertEqual(model.generate_options["forced_bos_token_id"], 256047)
        self.assertEqual(model.generate_options["input_ids"].device, "cuda")

    def test_dynamic_context_uses_video_title_and_outdoor_terms(self):
        prompt, hotwords = self.service.build_transcription_context(
            "Hiking to Kanchenjunga Base Camp.mp4"
        )
        self.assertIn("Kanchenjunga Base Camp", prompt)
        self.assertIn("Dyneema", hotwords)
        self.assertNotIn("long way around Africa", hotwords)

    def test_word_timestamps_are_split_into_readable_subtitles(self):
        tokens = (
            "to eight times the strength to weight ratio in comparison to steel "
            "but it is still lighter than DCF I love this pack so much and honestly "
            "I really have so much to say about it but I think my favorite thing is "
            "the running vest style straps in the front"
        ).split()
        words = []
        cursor = 0.0
        for index, token in enumerate(tokens):
            start = cursor
            end = start + 0.28
            words.append({"start": start, "end": end, "text": token})
            cursor = end + (0.48 if index in {10, 17, 29} else 0.08)

        segments = self.service.words_to_sentence_segments(words)

        self.assertGreaterEqual(len(segments), 3)
        for segment in segments:
            duration = segment["end"] - segment["start"]
            self.assertLessEqual(duration, self.service.MAX_SUBTITLE_SECONDS + 0.01)
            self.assertLessEqual(len(segment["text"].split()), self.service.MAX_SUBTITLE_WORDS)
            self.assertLessEqual(len(segment["text"]), self.service.MAX_SUBTITLE_CHARS)

    def test_segment_text_restores_terminal_punctuation_missing_from_words(self):
        words = [{"start": 0.0, "end": 0.5, "text": "Manaslu"}]
        self.service.preserve_segment_terminal_punctuation(words, 0, "Everest Base Camp, Manaslu.")
        self.assertEqual(words[-1]["text"], "Manaslu.")
        self.assertTrue(words[-1]["segment_complete"])

    def test_sentence_punctuation_remains_a_strong_boundary(self):
        words = [
            {"start": 0.0, "end": 0.3, "text": "I"},
            {"start": 0.4, "end": 0.8, "text": "agree."},
            {"start": 1.0, "end": 1.3, "text": "This"},
            {"start": 1.4, "end": 1.8, "text": "helps."},
        ]
        segments = self.service.words_to_sentence_segments(words)
        self.assertEqual([item["text"] for item in segments], ["I agree.", "This helps."])

    def test_transcription_keeps_previous_window_context(self):
        source = SERVICE_PATH.read_text(encoding="utf-8")
        self.assertIn("condition_on_previous_text=True", source)
        self.assertIn("prompt_reset_on_temperature=0.5", source)

    def test_pause_after_auxiliary_does_not_create_a_fragment(self):
        tokens = ["Yeah,", "like", "I", "said,", "the", "snow", "is", "deep.", "It's", "unpredictable."]
        words = []
        cursor = 0.0
        for token in tokens:
            words.append({"start": cursor, "end": cursor + 0.32, "text": token})
            cursor += 0.32 + (0.82 if token == "is" else 0.08)

        segments = self.service.words_to_sentence_segments(words)
        self.assertEqual(
            [item["text"].lower() for item in segments],
            ["yeah, like i said, the snow is deep.", "it's unpredictable."],
        )

    def test_continuation_word_blocks_a_pause_split(self):
        current = [
            {"start": 0.0, "end": 1.0, "text": "And"},
            {"start": 1.1, "end": 2.1, "text": "somehow"},
            {"start": 2.2, "end": 3.2, "text": "that"},
            {"start": 3.3, "end": 4.3, "text": "is"},
            {"start": 4.4, "end": 5.9, "text": "exactly"},
        ]
        next_word = {"start": 6.75, "end": 7.1, "text": "What"}
        self.assertFalse(self.service.should_break_after_word(current, next_word))

    def test_modal_pause_waits_for_the_question_ending(self):
        tokens = ["Brain", "goes", "like,", "could", "this", "be", "the", "one?"]
        words = []
        cursor = 0.0
        for token in tokens:
            words.append({"start": cursor, "end": cursor + 0.7, "text": token})
            cursor += 0.7 + (0.85 if token == "could" else 0.08)
        segments = self.service.words_to_sentence_segments(words)
        self.assertEqual([item["text"].lower() for item in segments], ["brain goes like, could this be the one?"])

    def test_caption_cleanup_and_translation_glossary(self):
        cleaned = self.service.correct_recognized_caption_text(
            "i use it with the, with the old knees."
        )
        self.assertEqual(cleaned, "I use it with the old knees.")
        prepared = self.service.prepare_caption_for_translation(
            "DCF has a high strength to weight ratio."
        )
        self.assertIn("Dyneema Composite Fabric", prepared)
        self.assertIn("strength-to-weight ratio", prepared)

    def test_subtitle_chinese_normalization(self):
        normalized = self.service.normalize_subtitle_chinese(
            "\u6293\u4f4f\u4f60\u7684\u80cc\u5305, \u5305\u88c5\u718a\u55b7\u96fe."
        )
        self.assertEqual(normalized, "\u5e26\u4e0a\u4f60\u7684\u80cc\u5305\uff0c\u5e26\u4e0a\u9632\u718a\u55b7\u96fe\u3002")

    def test_ing_phrase_is_not_preferred_as_a_subtitle_ending(self):
        self.assertTrue(self.service.weak_subtitle_ending("We went hiking"))



if __name__ == "__main__":
    unittest.main()
