import copy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'validation'))
from summarize_local_semantic_experiment import pooled_boundaries, translation_comparison


class LocalSemanticSummaryTests(unittest.TestCase):
    def test_micro_f1_uses_counts_not_average(self):
        result = pooled_boundaries([
            dict(name='a', correct_boundaries=1, predicted_boundaries=1, reference_boundaries=1),
            dict(name='b', correct_boundaries=0, predicted_boundaries=9, reference_boundaries=9),
        ])
        self.assertAlmostEqual(result['micro_f1'], .1)

    def test_missing_duplicate_reports_are_rejected(self):
        with self.assertRaises(ValueError):
            pooled_boundaries([])
        row = dict(name='a', correct_boundaries=1, predicted_boundaries=1, reference_boundaries=1)
        with self.assertRaises(ValueError):
            pooled_boundaries([row, row])

    def test_source_mutation_is_not_translation_improvement(self):
        before = [dict(text='Go.', start=1., end=2., translation='Go.', translation_status='english_fallback')]
        after = copy.deepcopy(before)
        after[0].update(translation='走吧。', translation_status='generated_unreviewed')
        result = translation_comparison(before, after)
        self.assertIsNone(result['semantic_accuracy'])
        after[0]['start'] = 3.
        with self.assertRaises(ValueError):
            translation_comparison(before, after)
        with self.assertRaises(ValueError):
            translation_comparison(before, [])


if __name__ == '__main__':
    unittest.main()
