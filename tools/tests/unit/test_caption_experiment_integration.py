import importlib.util
from contextlib import nullcontext
import os
from pathlib import Path
import tempfile
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[3]


class ExperimentIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        # Other versioned services use the same bare module name in this suite.
        # Load this version explicitly without polluting tests for older releases.
        segmenter_spec = importlib.util.spec_from_file_location("semantic_caption_segmenter_v206",
            ROOT/"tools/versions/v2.1.0/semantic_caption_segmenter_v206.py")
        segmenter = importlib.util.module_from_spec(segmenter_spec)
        modules = patch.dict(sys.modules, {"semantic_caption_segmenter_v206": segmenter})
        modules.start()
        self.addCleanup(modules.stop)
        segmenter_spec.loader.exec_module(segmenter)
        with patch.dict(os.environ, {"VIDEO_ENGLISH_DATA_DIR": self.temp.name,
                                    "WHISPER_RUNTIME_CONFIG": str(Path(self.temp.name)/"config.json"),
                                    "WHISPER_RUNTIME_STATUS": str(Path(self.temp.name)/"status.json")}):
            spec = importlib.util.spec_from_file_location("caption_experiment_service", ROOT/"tools/versions/v2.1.0/service.py")
            self.service = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.service)

    def test_opt_in_config_does_not_reuse_normal_cache(self):
        s = self.service
        metadata = {"revision": s.PIPELINE_REVISION}
        with patch.object(s.JOB_STORE, "load_artifact", return_value=metadata), patch.dict(os.environ, {
            "SUBTITLE_LEARNING_SENTENCES_EXPERIMENT": "1", "WHISPERX_QUALITY_GUARD_EXPERIMENT": "0"}):
            self.assertFalse(s.cache_revision_is_current("audio"))
            self.assertTrue(s.semantic_segmenter_config().learning_sentence_mode)
            metadata["caption_experiments"] = s.caption_experiment_config()
            self.assertTrue(s.cache_revision_is_current("audio"))

    def test_normal_mode_rejects_experiment_cache(self):
        s = self.service
        with patch.object(s.JOB_STORE, "load_artifact", return_value={"revision": s.PIPELINE_REVISION,
            "caption_experiments": {"SUBTITLE_LEARNING_SENTENCES_EXPERIMENT": True}}), patch.dict(os.environ, {
            "SUBTITLE_LEARNING_SENTENCES_EXPERIMENT": "0", "WHISPERX_QUALITY_GUARD_EXPERIMENT": "0"}):
            self.assertFalse(s.cache_revision_is_current("audio"))

    def test_padding_keeps_word_identity_and_unpadded_display_cues(self):
        source = {"start": 1, "end": 5, "text": "We are going.", "word_start": 0, "word_end": 3,
                  "learning_sentence_id": 0, "display_cues": [{"start": 1, "end": 5, "text": "We are going."}]}
        result = self.service.finalize_english_segments([source])[0]
        self.assertEqual(result["word_end"], 3)
        self.assertEqual(result["display_cues"], source["display_cues"])
        self.assertEqual(source["start"], 1)

    def test_translator_receives_complete_sentence_not_display_fragments(self):
        s = self.service
        source = {"start": 1, "end": 15, "text": "We are going to the village tomorrow.",
                  "learning_sentence_id": 0, "display_cues": [{"text": "We are going"}, {"text": "to the village tomorrow."}]}
        with patch.object(s, "TRANSLATION_PROVIDER", "transformers"), patch.object(s, "translate_texts", return_value=["我们明天去村里。"] ) as translate:
            result = s.translate_segments([source])
        self.assertEqual(translate.call_args.args[0], [source["text"]])
        self.assertEqual(result[0]["learning_sentence_id"], 0)
        self.assertEqual(result[0]["translation"], "我们明天去村里。")

    def test_context_metadata_survives_without_changing_source(self):
        s = self.service
        source = {"text": "Only $5000.", "start": 1., "end": 3., "word_start": 0, "word_end": 2}
        metadata = {"translation": "只有50美元。", "translation_status": "review_required",
                    "translation_warnings": ["numeric_mismatch"], "translation_provider": "local_context"}
        with patch.object(s, "TRANSLATION_PROVIDER", "transformers"), patch.object(s, "translate_texts",
                return_value=s.TranslationResults([metadata])):
            result = s.translate_segments([source])[0]
        for k, v in source.items():
            self.assertEqual(result[k], v)
        self.assertEqual(result["translation_warnings"], ["numeric_mismatch"])
        self.assertEqual(result["translation_status"], "review_required")

    def test_context_unavailable_falls_back_to_existing_translator(self):
        s = self.service
        backend = SimpleNamespace(translate=lambda *args: (_ for _ in ()).throw(OSError('offline')), close=lambda: None)
        with patch.dict(os.environ, {"TRANSLATION_CONTEXT_MODE": "auto"}), \
                patch.object(s, "_context_translator", backend), \
                patch.object(s, "_translate_texts_legacy", return_value=["你好"]) as fallback:
            self.assertEqual(s.translate_texts(["Hello"]), ["你好"])
        fallback.assert_called_once()

    def test_context_configuration_invalidates_old_cache(self):
        s = self.service
        with patch.dict(os.environ, {"TRANSLATION_CONTEXT_MODE": "off"}):
            old = s.caption_experiment_config()
        with patch.dict(os.environ, {"TRANSLATION_CONTEXT_MODE": "auto"}):
            self.assertNotEqual(old, s.caption_experiment_config())

    def test_alignment_can_expose_speech_hidden_by_wide_asr_word(self):
        before = [{"start": 10, "end": 20, "text": "Hello."}]
        after = [{"start": 10, "end": 11, "text": "Hello."}]
        speech = [(14, 17)]
        self.assertEqual(self.service.find_uncovered_speech_gaps(before, speech, 30), [])
        self.assertEqual(self.service.find_uncovered_speech_gaps(after, speech, 30), [(14, 17)])

    def test_translation_output_is_not_automatically_verified(self):
        s = self.service
        self.assertEqual(s.caption_translation_status("We are here.", "我们在这里。"), "generated_unreviewed")
        self.assertEqual(s.caption_translation_status("We are here.", "We are here."), "english_fallback")
        self.assertEqual(s.caption_translation_status("One, two, three.", "1、2、3。"), "deterministic")
        self.assertEqual(s.caption_translation_status("We are here.", "我们在这里，"), "review_required")
        self.assertEqual(s.caption_translation_status("We are here.", ""), "missing")

    def test_generic_translation_does_not_rewrite_topic_or_inject_fixed_answers(self):
        s = self.service
        with patch.object(s, "TRANSLATION_STYLE", "generic"):
            for text in ("This is the lost way around Africa.", "The crow flies over a tree.",
                         "DCF is our company name.", "Let's do it.", "One, two, one, two."):
                self.assertEqual(s.prepare_caption_for_translation(text), text)
            self.assertEqual(s.polish_caption_translation("The crow flies.", "The crow flies.", "乌鸦飞过树梢。"), "乌鸦飞过树梢。")
            self.assertEqual(s.polish_caption_translation("Let's do it.", "Let's do it.", "让我们这样做。"), "让我们这样做。")
            self.assertEqual(s.caption_experiment_config()["translation_style"], "generic")
        with patch.dict(os.environ, {"SUBTITLE_LEARNING_SENTENCES_EXPERIMENT": "1"}):
            for title in ("A new lecture", "Switzerland hiking gear", "Nepal base camp"):
                source = "The lost way around Africa with the, with the Gunza exhibit."
                self.assertEqual(s.correct_recognized_caption_text(source, title), source)
                prompt, hotwords = s.build_transcription_context(title)
                self.assertNotIn("Dyneema", hotwords or "")
                self.assertNotIn("outdoor", prompt or "")

    def test_translation_failure_preserves_source_with_explicit_status(self):
        s = self.service
        source = {"text": "We are here.", "word_start": 0, "word_end": 3}
        with patch.object(s, "TRANSLATION_PROVIDER", "transformers"), patch.object(s, "translate_texts", side_effect=RuntimeError("offline")):
            result = s.translate_segments([source])
        self.assertEqual(result[0]["translation_status"], "failed")
        self.assertEqual(result[0]["word_end"], 3)
        self.assertNotIn("translation_status", source)

    def test_trailing_clause_punctuation_triggers_incomplete_review(self):
        self.assertTrue(self.service.translation_is_incomplete("The engineer built a tunnel for people to travel.", "工程师建了一条隧道，"))
        self.assertFalse(self.service.translation_is_incomplete("When we arrived,", "当我们到达时，"))
        self.assertTrue(self.service.translation_is_incomplete(
            'The guide will explain how everyone can follow safely', '导游会解释，'))
        self.assertFalse(self.service.translation_is_incomplete('Please wait', '请稍候'))

    def test_oversize_translation_does_not_silently_truncate_or_fail_other_items(self):
        calls = []
        class Tensor:
            def to(self, device):
                return self
        class Tokenizer:
            def __call__(self, texts, **options):
                calls.append(options)
                if options.get("return_tensors"):
                    return {"input_ids": Tensor()}
                return {"input_ids": [[1]*len(text) for text in texts]}
            def batch_decode(self, *args, **kwargs):
                return ["你好。"]
        tokenizer = Tokenizer()
        model = SimpleNamespace(config=SimpleNamespace(model_type="test"),
            to=lambda *a, **kw: None, eval=lambda: None, generate=lambda **kw: [[1]])
        auto_tokenizer, auto_model = object(), object()
        transformer = SimpleNamespace(AutoTokenizer=auto_tokenizer, AutoModelForSeq2SeqLM=auto_model)
        torch = SimpleNamespace(inference_mode=nullcontext)
        s = self.service
        with patch.dict(sys.modules, {"transformers": transformer, "torch": torch}), \
             patch.object(s, "load_pretrained", side_effect=lambda cls, path: tokenizer if cls is auto_tokenizer else model), \
             patch.object(s, "TRANSLATION_DEVICE", "cpu"):
            translate = s.build_transformers_translator()
            source = "unusuallylongtoken"*50
            self.assertEqual(translate([source, "Hello."]), [source, "你好。"])
        self.assertTrue(calls)
        self.assertTrue(all(c.get("truncation") is False for c in calls))

    def test_post_recovery_expands_gap_but_never_inserts_context_words(self):
        class Options:
            def __init__(self, threshold=.5, neg_threshold=None, **kwargs):
                self.threshold = threshold
        def word(text, start, end):
            return SimpleNamespace(word=text, start=start, end=end, probability=.95)
        part = SimpleNamespace(start=.1, end=10, text="Hello. We are ready. Next.", avg_logprob=-.2,
            no_speech_prob=.1, compression_ratio=1., temperature=0., words=[word("Hello.", .1, .2),
            word("We", 1, 1.5), word("are", 2, 2.5), word("ready.", 3, 3.5), word("Next.", 9.5, 10)])
        calls = []
        def transcribe(audio, **kwargs):
            calls.append((len(audio), kwargs))
            return [part], None
        words = [{"text": "Hello.", "start": 10, "end": 11, "segment_id": 0},
                 {"text": "Next.", "start": 20, "end": 21, "segment_id": 1}]
        segments = [dict(w, id=i) for i,w in enumerate(words)]
        with patch.dict(sys.modules, {
            "faster_whisper.audio": SimpleNamespace(decode_audio=lambda *a, **kw: [0.]*480000),
            "faster_whisper.vad": SimpleNamespace(VadOptions=Options,
                get_speech_timestamps=lambda *a: [{"start": 14*16000, "end": 16*16000}])}):
            _, result, debug = self.service.recover_uncovered_speech(SimpleNamespace(transcribe=transcribe),
                "test-audio", segments, words, "en", "test", whole_word_gap=True)
        self.assertFalse(debug["error"])
        self.assertEqual([w["text"] for w in result], ["Hello.", "We", "are", "ready.", "Next."])
        self.assertEqual(debug["candidates"], [{"start": 11., "end": 20.}])
        self.assertIsNone(calls[0][1]["hotwords"])
        self.assertFalse(calls[0][1]["vad_filter"])

    def test_lossless_rebuild_does_not_delete_overlapping_count(self):
        _, words = self.service.rebuild_raw_transcription_artifacts([], [
            {"text": "one", "start": 1, "end": 2}, {"text": "one", "start": 1.5, "end": 2.5}], deduplicate=False)
        self.assertEqual(len(words), 2)


if __name__ == "__main__":
    unittest.main()
