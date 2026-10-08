import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('drift_audit',
    Path(__file__).resolve().parents[3]/'tools/validation/audit_transcript_drift.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


def words(text, offset=0):
    return [{'text': text, 'start': offset+i, 'end': offset+i+.5}
            for i, text in enumerate(text.split())]


class TranscriptDriftTests(unittest.TestCase):
    def test_multitoken_shift_flagged_not_automatically_corrected(self):
        original = words('Mix the flour with water then stir it slowly')
        before = [dict(w) for w in original]
        report = module.audit(original, words('Mix the flour with water then stir it slowly', 18))
        self.assertEqual(report['status'], 'review_required')
        self.assertEqual(report['flags'][0]['median_delta_seconds'], 18)
        self.assertEqual(original, before)
        self.assertFalse(report['release_allowed'])

    def test_one_bad_word_does_not_flag_whole_phrase(self):
        original = words('Check the voltage before connecting wires')
        peer = words('Check the voltage before connecting wires')
        peer[2].update(start=20, end=20.5)
        self.assertEqual(module.audit(original, peer)['flagged_phrase_anchors'], 0)

    def test_repeat_ambiguity_skipped_not_deduplicated(self):
        text = 'one two three four five one two three four five'
        source = words(text)
        report = module.audit(source, words(text, 20))
        self.assertGreater(report['ambiguous_phrase_keys_skipped'], 0)
        self.assertFalse(any(f['phrase'] == 'one two three four five' for f in report['flags']))
        self.assertEqual(len(source), 10)

    def test_no_common_reference_is_unknown_not_pass(self):
        report = module.audit(words('hello there'), words('a different recording'))
        self.assertEqual(report['status'], 'insufficient_overlap')
        self.assertIsNone(report['accuracy'])
        self.assertFalse(report['release_allowed'])

    def test_agreeing_times_are_not_verified_accuracy(self):
        text = 'After lunch we listened to music'
        report = module.audit(words(text), words(text, .2))
        self.assertEqual(report['status'], 'no_large_disagreement_found')
        self.assertIsNone(report['accuracy'])
        self.assertFalse(report['release_allowed'])

    def test_invalid_times_and_threshold_rejected(self):
        with self.assertRaises(ValueError):
            module.audit([{'text': 'one', 'start': float('nan'), 'end': 1}], [])
        with self.assertRaises(ValueError):
            module.audit([], [], threshold=float('nan'))


if __name__ == '__main__':
    unittest.main()
