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
        self.assertEqual(os.path.normcase(os.path.relpath(self.service.DEFAULT_TRANSLATION_MODEL)),os.path.normcase(expected))

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


if __name__ == "__main__":
    unittest.main()
