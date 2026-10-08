import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"validation"))
import evaluate_joint_caption_reference as gate
import stabilize_ocr_reference as ocr


class JointGateTests(unittest.TestCase):
    def fixture(self, count=10):
        artifact = {"source_sha256": "source", "words": [], "units": []}
        ref = {"source_sha256": "source", "reviewer": "independent human",
               "full_audio_reviewed": True, "complete_video_reference": True,
               "missing_speech_checked": True, "items": []}
        for i in range(count):
            artifact["words"].append({"text": "Hello", "start": i*2, "end": i*2+1})
            artifact["units"].append({"word_start": i, "word_end": i+1, "text": "Hello",
                                      "translation": "你好", "translation_status": "generated_unreviewed"})
            ref["items"].append({"id": i, "candidate_unit_ids": [i], "text": "Hello",
                                 "speech_start": i*2, "speech_end": i*2+1, "reviewed": True,
                                 "no_clipping": True, "boundary_pass": True, "translation_pass": True})
        ref["artifact_sha256"] = gate.digest(artifact)
        return ref, artifact

    def test_marginal_ninety_does_not_mean_joint_ninety(self):
        ref, artifact = self.fixture()
        ref["items"][0]["text_pass"] = False
        ref["items"][1]["no_clipping"] = False
        ref["items"][2]["boundary_pass"] = False
        ref["items"][3]["translation_pass"] = False
        report = gate.evaluate(ref, artifact)
        for key in ("text", "timing", "boundary", "translation"):
            self.assertEqual(report["metrics"][key+"_pass_rate"], .9)
        self.assertEqual(report["metrics"]["joint_pass_rate"], .6)
        self.assertFalse(report["release_allowed"])

    def test_exact_joint_ninety_passes(self):
        ref, artifact = self.fixture()
        ref["items"][0]["translation_pass"] = False
        self.assertTrue(gate.evaluate(ref, artifact)["release_allowed"])

    def test_artifact_change_invalidates_old_review(self):
        ref, artifact = self.fixture()
        artifact["units"][0]["translation"] = "再见"
        self.assertEqual(gate.evaluate(ref, artifact)["status"], "insufficient_reference")

    def test_fallback_cannot_pass_even_if_review_flag_true(self):
        ref, artifact = self.fixture(1)
        artifact["units"][0]["translation_status"] = "english_fallback"
        ref["artifact_sha256"] = gate.digest(artifact)
        self.assertEqual(gate.evaluate(ref, artifact)["metrics"]["joint_pass_rate"], 0)

    def test_extra_units_and_missing_reference_are_in_denominator(self):
        ref, artifact = self.fixture(1)
        ref["items"][0]["candidate_unit_ids"] = []
        report = gate.evaluate(ref, artifact)
        self.assertEqual(report["denominator"], 2)
        self.assertEqual(report["extra_candidate_units"], [0])
        self.assertEqual(report["metrics"]["joint_pass_rate"], 0)

    def test_no_speech_coverage_review_blocks(self):
        ref, artifact = self.fixture()
        ref["missing_speech_checked"] = False
        self.assertFalse(gate.evaluate(ref, artifact)["release_allowed"])

    def test_word_loss_rejected(self):
        ref, artifact = self.fixture()
        artifact["units"].pop()
        with self.assertRaises(ValueError):
            gate.evaluate(ref, artifact)

    def test_candidate_reuse_rejected(self):
        ref, artifact = self.fixture()
        ref["items"][1]["candidate_unit_ids"] = [0]
        with self.assertRaises(ValueError):
            gate.evaluate(ref, artifact)

    def test_single_holdout_no_longer_suffices(self):
        reports, entries = [], []
        for i, genre in enumerate(("monologue", "dialogue", "counting", "noise")):
            ref, artifact = self.fixture(1)
            artifact["source_sha256"] = ref["source_sha256"] = str(i)
            ref["artifact_sha256"] = gate.digest(artifact)
            reports.append(gate.evaluate(ref, artifact))
            entries.append({"source_sha256": str(i), "genre": genre, "previously_tuned": False})
        frozen = {"frozen_before_evaluation": True, "videos": entries}
        self.assertTrue(gate.cohort_gate(reports, frozen)["release_allowed"])
        entries[0]["previously_tuned"] = True
        self.assertFalse(gate.cohort_gate(reports, frozen)["release_allowed"])


class OcrConsensusTests(unittest.TestCase):
    def cue(self, i, text, n=1):
        return {"id": i, "text": text, "start": i, "end": i+1,
                "observations": n, "variants": {text: n}}

    def test_full_partial_full_keeps_all_evidence(self):
        full = "The reason for this meeting is to tell you what a good job"
        cues = [self.cue(0, full, 2), self.cue(1, "tell you what a good job"), self.cue(2, full, 3)]
        result = ocr.stabilize(cues)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["raw_ids"], [0, 1, 2])
        self.assertEqual(result[0]["observations"], 6)
        self.assertFalse(result[0]["reviewed"])

    def test_shared_line_cannot_bridge_unrelated_captions(self):
        cues = [self.cue(0, "I will tell you what a good job", 2),
                self.cue(1, "what a good job"),
                self.cue(2, "what a good job you did yesterday", 2)]
        self.assertEqual(len(ocr.stabilize(cues)), 2)

    def test_blank_gap_prevents_merge(self):
        cues = [self.cue(0, "I will tell you what a good job", 2), self.cue(2, "what a good job")]
        self.assertEqual(len(ocr.stabilize(cues)), 2)

    def test_single_full_reading_is_not_consensus(self):
        cues = [self.cue(0, "I will tell you what a good job"), self.cue(1, "what a good job")]
        self.assertEqual(len(ocr.stabilize(cues)), 2)

    def test_later_repeated_full_reading_confirms_initial_partial(self):
        full = "The reason for this meeting is to tell you what a good job"
        cues = [self.cue(0, full), self.cue(1, "tell you what a good job"), self.cue(2, full, 2)]
        cues[1]["start"] += .02
        cues[1]["end"] += .02
        cues[2]["start"] += .04
        cues[2]["end"] += .04
        self.assertEqual(len(ocr.stabilize(cues, frame_tolerance=.04)), 1)

    def test_actual_caption_change_not_fuzzy_merged(self):
        cues = [self.cue(0, "I will tell you what a good job", 2), self.cue(1, "I will tell you what a bad job", 2)]
        self.assertEqual(len(ocr.stabilize(cues)), 2)


if __name__ == "__main__":
    unittest.main()
