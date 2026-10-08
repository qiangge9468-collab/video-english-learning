import sys
from pathlib import Path
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'versions/v2.1.0'))
import semantic_caption_segmenter_v206 as s


class AbbreviationTests(unittest.TestCase):
    def segment(self,text,gap=0):
        words=s.normalize_words([{'text':w,'start':i*.3+(gap if i else 0),'end':i*.3+.2+(gap if i else 0)} for i,w in enumerate(text.split())])
        f=s.analyze_boundaries(words)
        for x in f:
            if x.protected_by_abbreviation:
                x.sat_probability=.999
        return s.learning_sentences(words,f,s.SegmenterConfig(learning_sentence_mode=True,learning_soft_dependency_boundaries=True))[0]

    def test_titles_and_names_stay_together_even_with_high_model_score(self):
        for title in ('Mr.','Mrs.','Ms.','Dr.','Prof.','Rev.','Hon.'):
            text=f'{title} Chen has arrived. Everyone is ready.'
            self.assertEqual([x['text'] for x in self.segment(text)],[f'{title} Chen has arrived.','Everyone is ready.'])

    def test_lowercase_asr_and_initials(self):
        for text in ('dr. smith will join us.','J. R. Smith is here.'):
            self.assertEqual([x['text'] for x in self.segment(text)],[text])

    def test_country_can_finish_sentence(self):
        self.assertEqual([x['text'] for x in self.segment('I visited the U.S. Today we leave.')],['I visited the U.S.','Today we leave.'])

    def test_long_gap_still_requires_review(self):
        r=self.segment('Dr. Smith',gap=5)
        self.assertEqual(len(r),2)
        self.assertTrue(all(x['boundary_review_required'] for x in r))

    def test_display_cues_do_not_force_a_title_dot_boundary(self):
        words=s.normalize_words([{'text':w,'start':i*.3,'end':i*.3+.2} for i,w in enumerate('Welcome Dr. Singh please sit here.'.split())])
        f=s.analyze_boundaries(words)
        self.assertEqual(f[2].punctuation,'')
        self.assertTrue(f[2].protected)
