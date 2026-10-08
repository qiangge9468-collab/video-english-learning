import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]


def load(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT/path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


gate = load("reference_gate", "tools/validation/evaluate_caption_reference.py")
audit = load("timeline_audit", "tools/validation/audit_cached_timeline_quality.py")
quality = load("alignment_audit", "tools/versions/v2.1.0/alignment_quality.py")
ocr = load("ocr_proposals", "tools/validation/compare_ocr_proposals.py")
recovery = load("post_gap_recovery", "tools/validation/recover_post_alignment_gaps.py")


class ReferenceGateTests(unittest.TestCase):
    def test_fragmented_vad_retries_complete_short_word_gap(self):
        words = [{"start": 258, "end": 261.49}, {"start": 269.62, "end": 274}]
        result = recovery.windows([(261.69, 263.368)], 300, padding=.35, words=words)
        self.assertAlmostEqual(result[0][0], 261.14)
        self.assertAlmostEqual(result[0][1], 269.97)

    def test_long_music_gap_is_not_expanded_to_whole_song(self):
        words = [{"start": 0, "end": 1}, {"start": 200, "end": 201}]
        self.assertEqual(recovery.windows([(50, 51)], 300, padding=.35, words=words), [[49.65, 51.35]])

    def test_no_burned_subtitle_reference_is_unknown_not_zero_accuracy(self):
        result = ocr.compare([], [{"text": "Hello", "start": 0, "end": 1}])
        self.assertIsNone(result["ocr_word_recall"])
        self.assertFalse(result["release_allowed"])

    def test_one_good_video_is_not_a_release(self):
        self.assertFalse(gate.cohort_gate([{"source_sha256": "a", "held_out": True,
                                           "release_allowed": True}])["release_allowed"])

    def test_four_duplicates_are_not_four_videos(self):
        reports = [{"source_sha256": "a", "held_out": True, "release_allowed": True}] * 4
        self.assertFalse(gate.cohort_gate(reports)["release_allowed"])

    def test_one_failed_video_blocks_release(self):
        reports = [{"source_sha256": str(i), "held_out": i==3, "release_allowed": i!=2} for i in range(4)]
        self.assertFalse(gate.cohort_gate(reports)["release_allowed"])

    def test_four_verified_videos_with_holdout_pass(self):
        reports = [{"source_sha256": str(i), "held_out": i==3, "release_allowed": True} for i in range(4)]
        self.assertTrue(gate.cohort_gate(reports)["release_allowed"])

    def reference(self):
        return {"reviewer": "independent reviewer", "full_audio_reviewed": True,
                "complete_video_reference": True,
                "items": [{"id": 0, "candidate_word_start": 0, "candidate_word_end": 1,
                    "text": "Hello", "speech_start": 1, "speech_end": 2,
                    "reviewed": True, "boundary_pass": True, "translation_pass": True}]}

    def test_unreviewed_ocr_cannot_pass_even_with_exact_text(self):
        ref = self.reference()
        ref["reviewer"] = "ocr"
        result = gate.evaluate(ref, [{"text": "Hello", "start": 1, "end": 2}])
        self.assertEqual(result["status"], "insufficient_reference")

    def test_partial_video_cannot_pass(self):
        ref = self.reference()
        ref["complete_video_reference"] = False
        self.assertFalse(gate.evaluate(ref, [{"text": "Hello", "start": 1, "end": 2}])["release_allowed"])

    def test_missing_caption_counts_as_error(self):
        ref = self.reference()
        ref["items"][0]["candidate_word_end"] = 0
        result = gate.evaluate(ref, [])
        self.assertEqual(result["metrics"]["text_accuracy"], 0)
        self.assertFalse(result["release_allowed"])

    def test_unmapped_hallucination_is_counted_not_hidden(self):
        result = gate.evaluate(self.reference(), [{"text": "Hello", "start": 1, "end": 2},
                                                 {"text": "Thanks for watching", "start": 5, "end": 6}])
        self.assertEqual(result["unmapped_candidate_insertions"], 3)
        self.assertEqual(result["metrics"]["text_accuracy"], 0)

    def test_overlapping_candidate_ranges_cannot_double_count(self):
        ref = self.reference()
        ref["items"].append(dict(ref["items"][0], id=1))
        with self.assertRaises(ValueError):
            gate.evaluate(ref, [{"text": "Hello", "start": 1, "end": 2}])

    def test_good_text_bad_timing_cannot_be_averaged_away(self):
        result = gate.evaluate(self.reference(), [{"text": "Hello", "start": 5, "end": 6}])
        self.assertEqual(result["status"], "below_threshold")
        self.assertEqual(result["metrics"]["text_accuracy"], 1)

    def test_empty_reference_does_not_mean_perfect(self):
        self.assertFalse(gate.evaluate({"items": []}, [])["release_allowed"])

    def test_actual_final_issues_are_counted(self):
        service = SimpleNamespace(pathological_repeated_phrase=lambda _: None,
                                  implausible_count_sequence=lambda _: False)
        with tempfile.TemporaryDirectory() as folder, patch.object(audit, "load_service", return_value=service):
            cache = Path(folder)/"hash"
            cache.mkdir()
            (cache/"whisper_segments.json").write_text(json.dumps([{"text": "x", "start": 1, "end": 2}]))
            (cache/"english.json").write_text(json.dumps([{"text": "x", "start": 2, "end": 1}]))
            self.assertEqual(audit.audit(Path(folder), "hash")["issues_after_quality_gates"], 1)

    def test_alignment_checks_do_not_claim_waveform_accuracy(self):
        result = quality.audit_words([{"text": "x", "start": 0, "end": 0}])
        self.assertIsNone(result["audio_alignment_accuracy"])
        self.assertEqual(result["issues"][0]["kind"], "invalid_duration")


if __name__ == "__main__":
    unittest.main()
