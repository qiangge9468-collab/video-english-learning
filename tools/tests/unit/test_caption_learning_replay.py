import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'validation'))
from replay_learning_threshold import restore_features


class LearningReplayTests(unittest.TestCase):
    def test_debug_omits_only_outer_sentinels(self):
        self.assertEqual([f.index for f in restore_features([{'index':1},{'index':2}],3)],[0,1,2,3])

    def test_missing_internal_feature_is_not_silently_replaced(self):
        with self.assertRaises(ValueError):
            restore_features([{'index':1},{'index':3}],4)


if __name__ == '__main__':
    unittest.main()
