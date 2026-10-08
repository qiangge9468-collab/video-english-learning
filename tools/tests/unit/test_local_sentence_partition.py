import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'validation'))
from run_local_sentence_partition import partition_ends,unpunctuated_view,lex


class SentencePartitionTests(unittest.TestCase):
    def words(self,text):
        return [{'text':w} for w in text.split()]

    def test_analysis_view_preserves_digits_contractions_and_word_identity(self):
        original = self.words("We paid $4,000.50, didn't we? Two-word labels!")
        self.assertEqual(lex(unpunctuated_view(original)),lex(' '.join(w['text'] for w in original)))

    def test_only_case_punctuation_changes_become_original_indices(self):
        words = self.words('i am here are you ready')
        self.assertEqual(partition_ends({'sentences':['I am here.','Are you ready?']},words),[3,6])

    def test_no_added_deleted_or_changed_words(self):
        words = self.words('I I am ready')
        for sentences in (['I am ready'],['I I was ready'],['I I am ready now']):
            with self.assertRaises(ValueError):
                partition_ends({'sentences':sentences},words)

    def test_do_not_split_inside_hyphenated_original_token(self):
        with self.assertRaises(ValueError):
            partition_ends({'sentences':['two','word']},self.words('two-word'))

    def test_contractions_are_not_expanded(self):
        with self.assertRaises(ValueError):
            partition_ends({'sentences':['I do not know']},self.words("I don't know"))

    def test_ambiguous_punctuation_only_word_is_rejected(self):
        with self.assertRaises(ValueError):
            partition_ends({'sentences':['Hello.','Yes.']},self.words('hello . yes'))


if __name__ == '__main__':
    unittest.main()
