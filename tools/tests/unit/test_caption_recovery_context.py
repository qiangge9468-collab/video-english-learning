"""Content-independent coverage: silence, repeats, context, and contradictions."""
import importlib.util
from pathlib import Path
from types import SimpleNamespace as NS
import unittest

PATH = Path(__file__).resolve().parents[2]/"versions/v2.1.0/recovery_decode.py"
spec = importlib.util.spec_from_file_location("recovery_decode_test", PATH)
policy = importlib.util.module_from_spec(spec)
spec.loader.exec_module(policy)


def part(text, start=1., logp=-.2):
    words = [NS(word=t, start=start+i*.3, end=start+i*.3+.2, probability=.9)
             for i,t in enumerate(text.split())]
    return NS(text=text, start=start, end=start+len(words)*.3, words=words,
              avg_logprob=logp, no_speech_prob=.1)


class ContextRetryTests(unittest.TestCase):
    def run_case(self, outputs, start=2, end=5):
        calls = []
        def transcribe(audio, **options):
            calls.append((len(audio), options))
            return iter(outputs[len(calls)-1]), None
        result = policy.decode_gap(NS(transcribe=transcribe), [0.]*160000,
                                  start, end, {"initial_prompt": None}, lambda text: "subscribe" not in text)
        return result, calls

    def test_reliable_first_pass_is_not_replaced_or_redecoded(self):
        (parts, _, trace), calls = self.run_case([[part("Good morning.")]])
        self.assertEqual(len(calls), 1)
        self.assertEqual(parts[0].text, "Good morning.")
        self.assertFalse(trace["retry_selected"])

    def test_context_only_decode_retries_bounded_windows(self):
        (parts, _, trace), calls = self.run_case([[part("prior", 0)],
            [part("We are ready.", .5)], [part("We are ready.", 1.5)]])
        self.assertEqual(len(calls), 3)
        self.assertEqual(parts[0].text, "We are ready.")
        self.assertTrue(trace["retry_selected"])
        self.assertTrue(trace["review_required"])

    def test_silence_is_not_filled(self):
        (parts, _, trace), calls = self.run_case([[], [], []])
        self.assertEqual(parts, [])
        self.assertEqual(len(calls), 3)
        self.assertFalse(trace["retry_selected"])

    def test_one_verbose_retry_is_not_proof_of_missing_speech(self):
        (_, _, trace), _ = self.run_case([[], [part("We are ready.", .5)], []])
        self.assertFalse(trace["retry_selected"])

    def test_negation_disagreement_is_not_promoted(self):
        (_, _, trace), _ = self.run_case([[], [part("Do it.", .5)], [part("Do not do it.", 1.5)]])
        self.assertFalse(trace["retry_selected"])

    def test_repeated_training_counts_are_preserved(self):
        (parts, _, trace), _ = self.run_case([[], [part("one two one two", .3)], [part("one two one two", 1.3)]])
        self.assertTrue(trace["retry_selected"])
        self.assertEqual(parts[0].text, "one two one two")

    def test_matching_text_at_different_times_is_not_agreement(self):
        a = [{"token": "one", "midpoint": 2.}]
        b = [{"token": "one", "midpoint": 4.}]
        self.assertEqual(policy.agreement(a, b), 0.)

    def test_rejected_boilerplate_is_not_promoted(self):
        (_, _, trace), _ = self.run_case([[], [part("subscribe", .5)], [part("subscribe", 1.5)]])
        self.assertFalse(trace["retry_selected"])

    def test_short_genuine_utterance_can_be_recovered(self):
        (parts, _, trace), _ = self.run_case([[], [part("Yes.", .5)], [part("Yes.", 1.5)]])
        self.assertTrue(trace["retry_selected"])
        self.assertEqual(parts[0].text, "Yes.")

    def test_nonfinite_confidence_is_rejected(self):
        self.assertEqual(policy.usable_words([part("Hello.", logp=float("nan"))], 1, 2, 5, lambda _: True), [])

    def test_video_start_duplicate_window_is_not_an_independent_vote(self):
        (_, _, trace), calls = self.run_case([[], []], start=0, end=10)
        self.assertEqual(len(calls), 1)
        self.assertFalse(trace["retry_selected"])


if __name__ == "__main__":
    unittest.main()
