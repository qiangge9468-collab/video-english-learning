import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'validation'))
from run_context_translation_experiment import validate_translation
from retry_context_translation import required_schema,validate_keyed


class ContextTranslationTests(unittest.TestCase):
    def test_schema_requires_each_target_id(self):
        schema = required_schema([2,7])
        self.assertEqual(schema['required'],['2','7'])
        self.assertFalse(schema['additionalProperties'])
        with self.assertRaises(ValueError):
            validate_keyed({'2':'你好'},{2:'Hello',7:'Goodbye'})
        found,_ = validate_keyed({'2':'你好','7':'再见'},{2:'Hello',7:'Goodbye'})
        self.assertEqual(found,{2:'你好',7:'再见'})

    def test_preserves_identity_even_if_model_reorders(self):
        value = {'items':[{'id':2,'translation':'再见'},{'id':1,'translation':'你好'}]}
        found,warnings = validate_translation(value,{1:'Hello',2:'Goodbye'})
        self.assertEqual(found[1],'你好')
        self.assertFalse(warnings)

    def test_missing_extra_and_duplicate_items_fail_closed(self):
        for items in ([],[{'id':2,'translation':'你好'}],
                      [{'id':1,'translation':'你好'},{'id':1,'translation':'您好'}]):
            with self.assertRaises(ValueError):
                validate_translation({'items':items},{1:'Hello'})

    def test_numbers_and_english_fallback_are_not_success(self):
        _,warning = validate_translation({'items':[{'id':0,'translation':'只有50美元'},{'id':1,'translation':'Hello'}]},
                                         {0:'Only $5,000',1:'Hello'})
        self.assertIn('numeric_mismatch',warning[0])
        self.assertIn('no_chinese_or_english_fallback',warning[1])

    def test_number_group_separator_does_not_change_value(self):
        _,warning = validate_translation({'items':[{'id':0,'translation':'5000美元'}]},{0:'$5,000'})
        self.assertFalse(warning)


if __name__ == '__main__':
    unittest.main()
