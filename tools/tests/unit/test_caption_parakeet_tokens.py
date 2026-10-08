from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'validation'))
from run_parakeet_asr_experiment import token_words


class ParakeetTokenTests(unittest.TestCase):
    def test_currency_spacing_uses_original_bpe_boundaries(self):
        result = token_words(dict(text='extra$2', tokens=[' extra', ' ', '$', '2'],
                                  timestamps=[0, .2, .2, .3], durations=[.2, 0, .1, .1]))
        self.assertEqual([w['text'] for w in result], ['extra', '$2'])

    def test_piece_mapping_preserves_repeated_counts_and_zero_duration_punctuation(self):
        raw = dict(text='One one, 8.', tokens=[' O', 'ne', ' one', ',', ' ', '8', '.'],
                   timestamps=[0, .1, .3, .5, .6, .6, .7], durations=[.1, .2, .2, 0, 0, .1, 0])
        result = token_words(raw)
        self.assertEqual([w['text'] for w in result], ['One', 'one,', '8.'])
        self.assertAlmostEqual(result[0]['end'], .3)
        self.assertEqual(result[1]['start'], .3)
        self.assertEqual(result[2]['start'], .6)

    def test_text_token_mismatch_is_not_silently_repaired(self):
        with self.assertRaises(ValueError):
            token_words(dict(text='Two', tokens=['One'], timestamps=[0], durations=[1]))

    def test_missing_token_times_fail(self):
        with self.assertRaises(ValueError):
            token_words(dict(text='One', tokens=['One'], timestamps=[], durations=[]))

    def test_empty_audio_transcript_remains_empty(self):
        self.assertEqual(token_words(dict(text='', tokens=[], timestamps=[], durations=[])), [])


if __name__ == '__main__':
    unittest.main()
