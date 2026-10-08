import sys
from pathlib import Path
import unittest
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'validation'))
sys.path.insert(0,str(ROOT/'versions/v2.1.0'))
from run_punctuation_experiment import token_windows, clean_token
from audit_publisher_boundaries import audit, reference_boundaries
from semantic_caption_segmenter_v206 import normalize_words, analyze_boundaries, SegmenterConfig, learning_sentences


class PunctuationEvidenceTests(unittest.TestCase):
    def test_context_windows_cover_every_word_once_without_truncation(self):
        for lengths in ([1]*340,[5]*340,[510,1,2],[2]):
            core = []
            for left,right,start,end in token_windows(lengths):
                self.assertLessEqual(sum(lengths[left:right]),510)
                self.assertLessEqual(left,start)
                self.assertGreaterEqual(right,end)
                core.extend(range(start,end))
            self.assertEqual(core,list(range(len(lengths))))

    def test_invalid_large_token_fails_not_truncated(self):
        with self.assertRaises(ValueError):
            list(token_windows([511]))

    def test_normalization_only_for_model_input(self):
        self.assertEqual(clean_token('"Don\'t!"'),"don't")
        self.assertEqual(clean_token('...'),'')

    def test_optional_evidence_default_is_disabled(self):
        words=normalize_words([{'text':w,'start':i,'end':i+.5} for i,w in enumerate('Everyone arrived everyone left'.split())])
        features=analyze_boundaries(words)
        features[2].restored_terminal_probability=.95
        result,_=learning_sentences(words,features,SegmenterConfig(learning_sentence_mode=True))
        self.assertEqual(len(result),1)
        result,_=learning_sentences(words,features,SegmenterConfig(learning_sentence_mode=True,learning_punctuation_threshold=.8))
        self.assertEqual([r['text'] for r in result],['Everyone arrived','everyone left'])
        self.assertEqual([(r['word_start'],r['word_end']) for r in result],[(0,2),(2,4)])

    def test_evidence_cannot_split_abbreviation_or_pronoun_auxiliary(self):
        for text in ('Dr. Brown arrives','we are ready'):
            words=normalize_words([{'text':w,'start':i,'end':i+.5} for i,w in enumerate(text.split())])
            features=analyze_boundaries(words)
            features[1].restored_terminal_probability=.999
            result,_=learning_sentences(words,features,SegmenterConfig(learning_sentence_mode=True,learning_punctuation_threshold=.8))
            self.assertEqual(len(result),1)

    def test_reference_protects_titles_not_countries(self):
        self.assertEqual(reference_boundaries('Dr. Chen arrived. We visited the U.S. Today we leave.'),{3,8})

    def test_object_pronoun_can_end_when_both_models_agree(self):
        words=normalize_words([{'text':w,'start':i,'end':i+.5} for i,w in enumerate('We learn from it next everyone practises'.split())])
        features=analyze_boundaries(words)
        features[4].previous_dependency='pobj'
        features[4].next_pos='ADV'
        features[4].sat_probability=.9
        features[4].restored_terminal_probability=.95
        config=SegmenterConfig(learning_sentence_mode=True,learning_punctuation_threshold=.8)
        result,_=learning_sentences(words,features,config)
        self.assertEqual(result[0]['text'],'We learn from it')
        features[4].previous_dependency='nsubj'
        result,_=learning_sentences(words,features,config)
        self.assertEqual(len(result),1)

    def test_object_full_stop_not_mistaken_for_subject_auxiliary(self):
        words=normalize_words([{'text':w,'start':i,'end':i+.5} for i,w in enumerate("We can do this. We're ready.".split())])
        features=analyze_boundaries(words)
        features[4].previous_dependency='dobj'
        features[4].protected_by_pos_pair=True
        features[4].sat_probability=.999
        result,_=learning_sentences(words,features,SegmenterConfig(learning_sentence_mode=True))
        self.assertEqual([s['text'] for s in result],["We can do this.","We're ready."])

    def test_parser_dot_does_not_replace_lexical_dependency(self):
        words=normalize_words([{'text':w,'start':i,'end':i+.5} for i,w in enumerate('We saw it. They left.'.split())])
        tokens=[]
        for idx,pos,dep in [(0,'PRON','nsubj'),(3,'VERB','ROOT'),(7,'PRON','dobj'),
                            (9,'PUNCT','punct'),(11,'PRON','nsubj'),(16,'VERB','ROOT'),(20,'PUNCT','punct')]:
            t=SimpleNamespace(idx=idx,pos_=pos,dep_=dep)
            t.head=t
            tokens.append(t)
        class Doc(list):
            noun_chunks=[]
            ents=[]
        features=analyze_boundaries(words,spacy_nlp=lambda text:Doc(tokens))
        self.assertEqual(features[3].previous_pos,'PRON')
        self.assertEqual(features[3].previous_dependency,'dobj')

    def test_boundary_audit_counts_missing_and_extra(self):
        words=[{'text':w} for w in 'He arrived she left'.split()]
        good=audit('He arrived. She left.',words,[{'word_end':2},{'word_end':4}])
        bad=audit('He arrived. She left.',words,[{'word_end':1},{'word_end':4}])
        self.assertEqual(good['f1'],1)
        self.assertEqual(bad['f1'],0)
        self.assertEqual(len(bad['errors']),2)

    def test_unalignable_boundary_is_not_credited(self):
        words=[{'text':w} for w in 'He arrived uh she left'.split()]
        r=audit('He arrived. She left.',words,[{'word_end':3},{'word_end':5}])
        self.assertEqual(r['correct_boundaries'],0)
        self.assertEqual(r['reference_boundaries'],1)

    def test_duplicate_punctuation_only_boundaries_count_as_extra(self):
        words=[{'text':w} for w in 'He arrived . she left'.split()]
        r=audit('He arrived. She left.',words,[{'word_end':2},{'word_end':3},{'word_end':5}])
        self.assertEqual(r['correct_boundaries'],1)
        self.assertEqual(r['predicted_boundaries'],2)
        self.assertEqual(r['precision'],.5)


if __name__=='__main__':
    unittest.main()
