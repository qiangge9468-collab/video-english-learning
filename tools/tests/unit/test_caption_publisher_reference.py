import importlib.util
from pathlib import Path
import unittest

spec = importlib.util.spec_from_file_location('publisher_reference', Path(__file__).resolve().parents[2]/'validation/compare_publisher_reference.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class PublisherReferenceTest(unittest.TestCase):
    def test_all_errors_counted(self):
        r = module.compare('one two three four',[{'text':'one too four five'}])
        self.assertEqual(r['publisher_transcript_wer'], .75)
        self.assertEqual(sum(v for k,v in r['edit_counts'].items() if k != 'equal'),3)

    def test_repetitions_preserved(self):
        r = module.compare('one two one two',[{'text':'one two'}])
        self.assertEqual(r['edit_counts']['delete'],2)

    def test_empty_hypothesis(self):
        self.assertEqual(module.compare('one two',[])['publisher_transcript_wer'],1)

    def test_editorial_numbers_not_silently_fixed(self):
        r = module.compare('30 days',[{'text':'thirty days'}])
        self.assertEqual(r['edit_counts']['substitute'],1)
        self.assertIsNone(r['audio_accuracy'])
        self.assertFalse(r['release_allowed'])

    def test_parenthetical_speech_not_removed(self):
        self.assertEqual(module.remove_nonspeech_labels('Yes (really) (Laughter)'), 'Yes (really)  ')
