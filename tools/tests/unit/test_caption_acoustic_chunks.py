import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('acoustic_chunks',
    Path(__file__).resolve().parents[3]/'tools/versions/v2.1.0/acoustic_chunks.py')
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)


class AcousticChunksTests(unittest.TestCase):
    def test_does_not_compress_silence_or_cross_long_pauses(self):
        chunks = m.merge_speech([(10, 12), (12.5, 13), (19, 20)])
        self.assertEqual([(c['start'], c['end']) for c in chunks], [(10, 13), (19, 20)])
        self.assertEqual(chunks[0]['segments'], [(10., 12.), (12.5, 13.)])

    def test_short_counts_remain_and_chunk_limit_holds(self):
        ranges = [(i*.6, i*.6+.1) for i in range(100)]
        chunks = m.merge_speech(ranges)
        self.assertEqual([r for c in chunks for r in c['segments']], ranges)
        self.assertTrue(all(c['end']-c['start'] <= 20 for c in chunks))

    def test_invalid_spans_rejected_and_empty_input_supported(self):
        self.assertEqual(m.merge_speech([]), [])
        for ranges in ([(0, 21)], [(1, 2), (1.5, 3)], [(float('nan'), 1)]):
            with self.assertRaises(ValueError):
                m.merge_speech(ranges)


if __name__ == '__main__':
    unittest.main()
