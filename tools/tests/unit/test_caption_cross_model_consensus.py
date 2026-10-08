import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'validation'))
from cross_model_gap_consensus import consensus


class CrossModelTests(unittest.TestCase):
    def row(self, tokens=('one','two'), offset=0):
        return {'index':0,'window':{'gap':[0,5],'clip':[0,6]},'inside_gap':[
            {'text':t,'start':i*.5+offset,'end':i*.5+.3+offset,'probability':.9} for i,t in enumerate(tokens)]}

    def test_agreement_never_claims_verified_or_inserts(self):
        accepted,_ = consensus(self.row(),self.row(),[])
        self.assertEqual(len(accepted),2)
        self.assertTrue(all(w['review_required'] and not w['inserted'] for w in accepted))

    def test_equal_words_at_wrong_time_rejected(self):
        accepted,rejected = consensus(self.row(),self.row(offset=2),[])
        self.assertFalse(accepted)
        self.assertEqual(rejected[0]['reason'],'time_disagreement')

    def test_repeated_counts_are_not_deduplicated(self):
        accepted,_ = consensus(self.row(('one','one')),self.row(('one','one')),[])
        self.assertEqual(len(accepted),2)

    def test_existing_words_and_singletons_not_inserted(self):
        accepted,_ = consensus(self.row(),self.row(),[{'start':0,'end':.3}])
        self.assertFalse(accepted)
        accepted,_ = consensus(self.row(('hello',)),self.row(('hello',)),[])
        self.assertFalse(accepted)

    def test_different_context_is_not_same_window_agreement(self):
        row = self.row()
        row['index'] = 1
        with self.assertRaises(ValueError):
            consensus(self.row(),row,[])


if __name__ == '__main__':
    unittest.main()
