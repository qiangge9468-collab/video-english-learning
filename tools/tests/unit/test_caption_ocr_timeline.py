from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'validation'))
from audit_ocr_timeline import audit


def words(text, start):
    return [dict(text=t, start=start+i*.2, end=start+(i+1)*.2) for i,t in enumerate(text.split())]


class OcrTimelineTests(unittest.TestCase):
    def test_exact_unique_phrase_detects_large_shift_outside_old_search_window(self):
        cue = dict(text='The weather is very nice.', start=100, end=103)
        result = audit([cue], words(cue['text'], 61))
        row = result['items'][0]
        self.assertEqual(row['status'], 'large_display_disagreement')
        self.assertAlmostEqual(row['onset_delta_from_display'], -39)
        self.assertFalse(result['release_allowed'])
        self.assertIsNone(result['speech_timing_accuracy'])

    def test_no_fuzzy_match_to_common_words(self):
        result = audit([dict(text='The weather is very nice.', start=10, end=13)],
                       words('The room is nice but the weather is bad.', 10))
        self.assertEqual(result['items'][0]['status'], 'no_exact_match')

    def test_repeated_spoken_phrase_not_assigned_to_arbitrary_occurrence(self):
        text = 'One two three four five.'
        result = audit([dict(text=text, start=10, end=13)], words(text, 10)+words(text, 30))
        self.assertEqual(result['items'][0]['status'], 'ambiguous_repetition')

    def test_repeated_ocr_reference_is_ambiguous(self):
        text = 'One two three four five.'
        cues = [dict(text=text, start=t, end=t+3) for t in (10, 30)]
        result = audit(cues, words(text, 10))
        self.assertEqual(result['counts'], {'ambiguous_repetition': 2})

    def test_display_padding_is_not_assumed_speech_error(self):
        text = 'We are going home.'
        result = audit([dict(text=text, start=10, end=14)], words(text, 11))
        self.assertEqual(result['items'][0]['status'], 'anchor_found')
        self.assertIsNone(result['speech_timing_accuracy'])

    def test_missing_and_short_cues_remain_in_denominator_without_mutation(self):
        cues = [dict(text='Thank you.', start=0, end=1), dict(text='We are going home.', start=2, end=4)]
        result = audit(cues, [])
        self.assertEqual(result['cue_count'], 2)
        self.assertEqual(result['counts'], {'insufficient_text': 1, 'no_exact_match': 1})
        self.assertNotIn('status', cues[0])

    def test_invalid_ranges_rejected(self):
        with self.assertRaises(ValueError):
            audit([dict(text='We are going home.', start=2, end=1)], [])


if __name__ == '__main__':
    unittest.main()
