import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'validation'))
from run_independent_gap_probe import uncovered
from expand_gap_probe_inventory import whole_gaps


class GapProbeTests(unittest.TestCase):
    def test_empty_transcript_still_requires_checking_speech(self):
        self.assertEqual(uncovered([[1,2]], [], 3), [[1,2]])

    def test_long_or_estimated_words_cannot_hide_missing_speech(self):
        for word in [{'start':0,'end':9}, {'start':1,'end':2,'alignment_status':'estimated_review_required'}]:
            self.assertEqual(uncovered([[1,2]],[word],10), [[1,2]])

    def test_real_word_coverage_not_double_counted(self):
        words = [{'start':1,'end':1.5}, {'start':1.2,'end':1.8}]
        self.assertEqual(uncovered([[0,3]], words, 3), [[0,.9],[1.9000000000000001,3]])

    def test_long_gap_split_without_losing_audio_or_exceeding_duration(self):
        self.assertEqual(uncovered([[0,25]], [], 20, maximum=8), [[0,8],[8,16],[16,20]])

    def test_fragmented_vad_retries_full_word_gap_once(self):
        inventory = {'duration':20,'uncovered_ranges':[[4,4.8],[6.5,7.2]]}
        words = [{'start':2,'end':3},{'start':9,'end':10}]
        self.assertEqual(whole_gaps(inventory,words),[[3,9]])

    def test_gap_expansion_does_not_swallow_long_music_interval(self):
        inventory = {'duration':100,'uncovered_ranges':[[45,46]]}
        words = [{'start':2,'end':3},{'start':90,'end':91}]
        self.assertEqual(whole_gaps(inventory,words),[[45,46]])


if __name__ == '__main__':
    unittest.main()
