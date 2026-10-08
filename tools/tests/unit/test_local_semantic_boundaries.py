import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'validation'))
from run_local_semantic_boundaries import (windows, validate_ends, choose_cuts, units_for_cuts,
                                          BoundaryFeatures, SegmenterConfig, post)


class LocalSemanticBoundaryTests(unittest.TestCase):
    def test_complete_owned_ranges_even_at_seams(self):
        for n in (0,1,179,180,181,481):
            seen = [i for a,b,_,_ in windows(n) for i in range(a+1,b+1)]
            self.assertEqual(seen,list(range(1,n+1)))

    def test_schema_rejects_rewriting_duplicates_bool_or_unowned_cuts(self):
        for value in ({'text':'rewrite'},{'ends':[1,1]},{'ends':[True]},
                      {'ends':[4]},{'ends':[0]},{'ends':[2,1]},{'ends':[], 'other':1}):
            with self.assertRaises(ValueError):
                validate_ends(value,0,3)
        self.assertEqual(validate_ends({'ends':[1,3]},0,3),[1,3])

    def test_no_remote_transcript_upload(self):
        for url in ('https://example.com','http://localhost','http://127.0.0.1.evil.com',
                    'http://user@127.0.0.1','http://127.0.0.1/proxy'):
            with self.assertRaises(ValueError):
                post(url,'/api/chat',{})

    def test_guard_and_long_gap_and_exact_partition(self):
        words = [{'text':t,'start':i*5.,'end':i*5.+1} for i,t in enumerate(['We','are','here.','Hello.'])]
        features = [BoundaryFeatures(index=i) for i in range(5)]
        features[1].protected_by_pos_pair = True
        features[3].gap = 4
        config = SegmenterConfig(learning_soft_dependency_boundaries=True)
        cuts,guards = choose_cuts(words,features,config,[1,2])
        self.assertEqual(cuts,[0,2,3,4])
        self.assertEqual(guards['protected_rejections'],[1])
        units = units_for_cuts(words,features,config,cuts)
        self.assertEqual([i for u in units for i in range(u['word_start'],u['word_end'])],list(range(4)))
        self.assertEqual(units[0]['text'],'We are')
        self.assertEqual((units[0]['start'],units[0]['end']),(0.,6.))

    def test_context_limit_is_visible_not_hidden(self):
        words = [{'text':'word','start':i,'end':i+.5} for i in range(8)]
        features = [BoundaryFeatures(index=i) for i in range(9)]
        cuts,guards = choose_cuts(words,features,SegmenterConfig(learning_max_words=3),[])
        self.assertTrue(guards['safety_cuts'])
        self.assertTrue(all(b-a <= 3 for a,b in zip(cuts,cuts[1:])))


if __name__ == '__main__':
    unittest.main()
