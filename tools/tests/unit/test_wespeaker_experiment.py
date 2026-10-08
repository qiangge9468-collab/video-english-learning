from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"validation"))
from run_wespeaker_experiment import windows, turns_from_windows


class WeSpeakerTests(unittest.TestCase):
    def test_complete_speech_range_coverage(self):
        result = windows([(0,4), (6,6.8)])
        self.assertEqual(result[0]['start'], 0)
        self.assertEqual(result[-2]['end'], 4)
        self.assertEqual(result[-1]['end'], 6.8)
        self.assertFalse(any(w['start'] < 6 and w['end'] > 4 for w in result))

    def test_short_speech_not_filled_with_fake_times(self):
        self.assertEqual(windows([(0,.1)]), [])
        self.assertEqual(windows([(0,.4)])[0]['end'], .4)

    def test_same_label_does_not_bridge_silence(self):
        win = windows([(0,3), (5,6)])
        turns = turns_from_windows(win, [0]*len(win))
        self.assertEqual(turns, [{'start':0, 'end':3, 'speaker':'speaker_0'},
                                {'start':5, 'end':6, 'speaker':'speaker_0'}])

    def test_turns_partition_window_range_without_overlap(self):
        win = windows([(0,5)])
        turns = turns_from_windows(win, [i%2 for i in range(len(win))])
        self.assertEqual(turns[0]['start'],0)
        self.assertEqual(turns[-1]['end'],5)
        self.assertTrue(all(a['end'] == b['start'] for a,b in zip(turns,turns[1:])))


if __name__ == '__main__':
    unittest.main()
