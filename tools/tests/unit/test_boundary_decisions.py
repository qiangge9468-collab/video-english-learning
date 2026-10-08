import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'validation'))
from run_boundary_decision_experiment import decision_schema,validate_decisions


class BoundaryDecisionTests(unittest.TestCase):
    def test_all_ids_required_and_only_two_choices(self):
        schema = decision_schema([4,12])
        self.assertEqual(schema['required'],['4','12'])
        self.assertEqual(schema['properties']['4']['enum'],['cut','join'])
        self.assertEqual(validate_decisions({'4':'join','12':'cut'},[4,12]),[12])

    def test_no_omitted_fabricated_or_unknown_decisions(self):
        for value in ({'4':'cut'},{'4':'cut','12':'maybe'},{'4':'cut','12':'join','13':'cut'}):
            with self.assertRaises(ValueError):
                validate_decisions(value,[4,12])


if __name__ == '__main__':
    unittest.main()
