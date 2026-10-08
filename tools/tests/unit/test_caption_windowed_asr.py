import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('windowed_asr',
    Path(__file__).resolve().parents[3]/'tools/versions/v2.1.0/windowed_asr.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class WindowedAsrTests(unittest.TestCase):
    def test_zero_duration_recognition_is_retained_as_unresolved(self):
        window = list(m.audio_windows(16000))[0]
        _, words, _ = m.owned_words([{'words': [
            {'text': 'one', 'start': .5, 'end': .5},
            {'text': 'two', 'start': 1., 'end': 1.}]}], window)
        self.assertEqual([w['text'] for w in words], ['one', 'two'])
        self.assertTrue(all(w['asr_timing_estimated'] for w in words))
        self.assertTrue(all(w['alignment_status'] == 'estimated_review_required' for w in words))
        self.assertEqual(words[0]['asr_original_start'], words[0]['asr_original_end'])
        self.assertLessEqual(words[-1]['end'], 1.)

    def test_all_samples_owned_exactly_once_including_tail(self):
        for samples in (0, 1, 16000, 320000, 320001, 999999):
            windows = list(m.audio_windows(samples))
            self.assertEqual(sum(w['core_end_sample']-w['core_start_sample'] for w in windows), samples)
            self.assertTrue(all(a['core_end_sample'] == b['core_start_sample'] for a,b in zip(windows, windows[1:])))
            self.assertTrue(all(0 <= w['clip_start_sample'] <= w['core_start_sample'] < w['core_end_sample'] <= w['clip_end_sample'] <= samples for w in windows))

    def test_context_not_inserted_and_repetition_preserved(self):
        window = list(m.audio_windows(100*16000))[1]
        part = {'text': 'earlier one one next', 'words': [
            {'text': 'earlier', 'start': 1, 'end': 2},
            {'text': 'one', 'start': 5, 'end': 6},
            {'text': 'one', 'start': 7, 'end': 8},
            {'text': 'next', 'start': 25, 'end': 26}]}
        segments, words, issues = m.owned_words([part], window, 2, 7)
        self.assertEqual([w['text'] for w in words], ['one', 'one'])
        self.assertEqual([w['start'] for w in words], [21, 23])
        self.assertEqual([w['index'] for w in words], [7, 8])
        self.assertEqual(segments[0]['word_end'], 9)
        self.assertFalse(issues)
        self.assertEqual(part['words'][1]['start'], 5)

    def test_exact_boundary_owned_by_next_core(self):
        windows = list(m.audio_windows(100*16000))
        part = {'words': [{'text': 'hello', 'start': 19.9, 'end': 20.1}]}
        self.assertFalse(m.owned_words([part], windows[0])[1])
        part['words'][0].update(start=3.9, end=4.1)
        selected = m.owned_words([part], windows[1])[1]
        self.assertEqual(len(selected), 1)
        self.assertTrue(selected[0]['boundary_review_required'])

    def test_out_of_window_and_invalid_times_are_audited(self):
        window = list(m.audio_windows(10*16000))[0]
        _, selected, rejected = m.owned_words([{'words': [
            {'text': 'wrong', 'start': 2, 'end': 20},
            {'text': 'nan', 'start': float('nan'), 'end': 4}]}], window)
        self.assertFalse(selected)
        self.assertEqual(len(rejected), 2)

    def test_overlong_context_rejected(self):
        with self.assertRaises(ValueError):
            list(m.audio_windows(16000, core_seconds=29, context_seconds=4))


if __name__ == '__main__':
    unittest.main()
