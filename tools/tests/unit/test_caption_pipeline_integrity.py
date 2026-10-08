import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'validation'))
from audit_pipeline_integrity import audit,translation_directory


class PipelineIntegrityTests(unittest.TestCase):
    def test_new_learning_never_implicitly_uses_old_translation(self):
        root,new,explicit = Path('old'),Path('new-learning'),Path('new-translation')
        self.assertEqual(translation_directory(root),root/'translation')
        self.assertEqual(translation_directory(root,new),new)
        self.assertEqual(translation_directory(root,new,explicit),explicit)

    def fixture(self):
        source = {'segments':[{'text':'one two'}]}
        words = [{'index':i,'source_segment_id':0,'source_token_index':i,'text':t,'start':i,'end':i+.3}
                 for i,t in enumerate(['one','two'])]
        return source, {'words':words}, [{'word_start':0,'word_end':2,'text':'one two','start':0.,'end':1.3}]

    def test_correct_ranges_do_not_hide_rewritten_text(self):
        source,aligned,units = self.fixture()
        units[0]['text'] = 'one three'
        result = audit(source,aligned,units)
        self.assertFalse(result['integrity_passed'])
        self.assertEqual(result['learning_text_not_matching_word_range'],[0])

    def test_correct_ranges_do_not_hide_changed_time(self):
        source,aligned,units = self.fixture()
        units[0]['start'] = 1.
        result = audit(source,aligned,units)
        self.assertFalse(result['integrity_passed'])
        self.assertEqual(result['learning_time_not_matching_word_range'],[0])

    def test_missing_text_or_time_is_not_success(self):
        source,aligned,units = self.fixture()
        del units[0]['text']
        units[0]['end'] = float('nan')
        result = audit(source,aligned,units)
        self.assertFalse(result['integrity_passed'])

    def test_passing_integrity_does_not_set_accuracy(self):
        r = audit(*self.fixture())
        self.assertTrue(r['integrity_passed'])
        self.assertIsNone(r['independent_accuracy'])
        self.assertFalse(r['release_allowed'])

    def test_reordering_is_not_disguised_by_preserved_token_count(self):
        source, aligned, units = self.fixture()
        aligned['words'].reverse()
        r = audit(source, aligned, units)
        self.assertFalse(r['integrity_passed'])
        self.assertEqual(r['source_order_inversion_segments'], [0])

    def test_missing_duplicate_and_long_gap_detected(self):
        source, aligned, units = self.fixture()
        aligned['words'][1] = dict(aligned['words'][0], index=1,start=10,end=10.3)
        r = audit(source,aligned,units)
        self.assertEqual(r['missing_source_tokens'],1)
        self.assertEqual(r['duplicate_source_tokens'],1)
        self.assertEqual(len(r['learning_units_crossing_long_word_gap']),1)


if __name__ == '__main__':
    unittest.main()
