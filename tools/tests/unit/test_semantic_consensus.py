import sys
from pathlib import Path
import unittest
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'validation'))
from replay_semantic_consensus import consensus_cuts, BoundaryFeatures, SegmenterConfig


class SemanticConsensusTests(unittest.TestCase):
    def setUp(self):
        self.words = [{'text':'word','start':i,'end':i+.5} for i in range(6)]
        self.features = [BoundaryFeatures(index=i) for i in range(7)]
        self.config = SegmenterConfig(learning_speaker_boundaries=True)

    def test_speaker_and_two_model_consensus_are_retained(self):
        self.features[2].acoustic_speaker_change = True
        self.features[4].sat_probability = .95
        self.features[4].restored_terminal_probability = .85
        cuts,guards = consensus_cuts(self.words,self.features,self.config,{2,4,6},[])
        self.assertEqual(cuts,[0,2,4,6])
        self.assertEqual(guards['restored_independent_consensus'],[2,4])

    def test_new_llm_cut_needs_independent_support(self):
        self.features[4].sat_probability = .2
        cuts,_ = consensus_cuts(self.words,self.features,self.config,{6},[2,4])
        self.assertEqual(cuts,[0,4,6])

    def test_failed_window_keeps_baseline_not_fabricated_llm_cuts(self):
        cuts,_ = consensus_cuts(self.words,self.features,self.config,{2,6},[3],[(0,4)])
        self.assertEqual(cuts,[0,2,6])


if __name__ == '__main__':
    unittest.main()
