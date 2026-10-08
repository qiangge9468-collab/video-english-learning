import importlib.util
from pathlib import Path
import sys
import unittest
import random
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[3]
VERSION = ROOT / "tools" / "versions" / "v2.1.0"
spec = importlib.util.spec_from_file_location("caption_quality_segmenter", VERSION / "semantic_caption_segmenter_v206.py")
segmenter = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = segmenter
spec.loader.exec_module(segmenter)


class CaptionQualityTests(unittest.TestCase):
    def test_soft_parser_arc_can_yield_to_semantic_clause_boundary(self):
        words = segmenter.normalize_words([{'text':t,'start':i*.3,'end':i*.3+.2}
                   for i,t in enumerate('the plan failed the experiment succeeded'.split())])
        features = segmenter.analyze_boundaries(words)
        features[3].sat_probability = .65
        features[3].protected_by_dependency = True
        features[3].next_dependency = 'det'
        result,_ = segmenter.learning_sentences(words,features,segmenter.SegmenterConfig(
            learning_sentence_mode=True,learning_boundary_probability=.25,learning_soft_dependency_boundaries=True))
        self.assertEqual([s['text'] for s in result],['the plan failed','the experiment succeeded'])

    def test_soft_dependency_mode_keeps_concrete_phrase_links(self):
        config = segmenter.SegmenterConfig(learning_sentence_mode=True,learning_soft_dependency_boundaries=True)
        for label in ('dobj','pobj','aux','neg','prt'):
            feature = segmenter.BoundaryFeatures(index=1,protected_by_dependency=True,next_dependency=label)
            self.assertTrue(segmenter.learning_boundary_protected(feature,config))
        subject = segmenter.BoundaryFeatures(index=1,protected_by_dependency=True,
            previous_dependency='nsubj',next_pos='VERB')
        self.assertTrue(segmenter.learning_boundary_protected(subject,config))

    def test_recommended_model_threshold_does_not_split_pronoun_auxiliary(self):
        words = segmenter.normalize_words([{'text':t,'start':i*.3,'end':i*.3+.2}
                   for i,t in enumerate('we are ready'.split())])
        features = segmenter.analyze_boundaries(words)
        features[1].sat_probability = .6
        features[1].protected_by_pos_pair = True
        result,_ = segmenter.learning_sentences(words,features,segmenter.SegmenterConfig(
            learning_sentence_mode=True,learning_boundary_probability=.25,learning_soft_dependency_boundaries=True))
        self.assertEqual([s['text'] for s in result],['we are ready'])

    def test_learning_does_not_span_long_gap_to_protect_auxiliary(self):
        raw = [{'text': 'please', 'start': 0, 'end': .3},
               {'text': 'do', 'start': .4, 'end': .8},
               {'text': 'Next', 'start': 45, 'end': 45.3},
               {'text': 'topic', 'start': 45.4, 'end': 45.8}]
        result, debug = segmenter.segment_words(raw,
            config=segmenter.SegmenterConfig(learning_sentence_mode=True))
        self.assertEqual([s['text'] for s in result], ['please do', 'Next topic'])
        self.assertTrue(any(w['kind'] == 'long_word_gap_boundary' for w in debug['warnings']))
        self.assertTrue(all(s['boundary_review_required'] for s in result))

    def test_normal_hesitation_does_not_break_subject_auxiliary(self):
        raw = [{'text': 'we', 'start': 0, 'end': .3},
               {'text': 'are', 'start': 1.1, 'end': 1.4},
               {'text': 'ready', 'start': 1.5, 'end': 1.8}]
        result, _ = segmenter.segment_words(raw,
            config=segmenter.SegmenterConfig(learning_sentence_mode=True))
        self.assertEqual([s['text'] for s in result], ['we are ready'])

    def test_learning_and_display_ranges_conserve_varied_sources(self):
        # Structural invariants across topics, not a semantic-accuracy claim.
        rng = random.Random(2701)
        vocabulary = ('one one two five we are not mix flour circuit voltage '
                      'patient oxygen music rhythm price thousand hello yes').split()
        config = segmenter.SegmenterConfig(learning_sentence_mode=True)
        for case in range(80):
            raw, position = [], 0.
            for index in range(rng.randint(1, 130)):
                position += rng.choice([0., .04, .3, 1.5])
                text = rng.choice(vocabulary) + rng.choice(['', '', '', ',', '.'])
                raw.append({'text': text, 'start': position, 'end': position+.2,
                            'source_token_index': index, 'probability': rng.random()})
                position += .2
            before = [dict(word) for word in raw]
            result, _ = segmenter.segment_words(raw, config=config)
            with self.subTest(case=case):
                self.assertEqual(raw, before)
                covered = [i for sentence in result
                           for i in range(sentence['word_start'], sentence['word_end'])]
                self.assertEqual(covered, list(range(len(raw))))
                for sentence in result:
                    display_covered = [i for cue in sentence['display_cues']
                                       for i in range(cue['word_start'], cue['word_end'])]
                    self.assertEqual(display_covered,
                                     list(range(sentence['word_start'], sentence['word_end'])))
                    for cue in sentence['display_cues']:
                        self.assertEqual(cue['learning_sentence_id'], sentence['learning_sentence_id'])

    def test_acoustically_aligned_recovery_is_still_unverified_text(self):
        result, _ = segmenter.segment_words([
            {"text": "Hello.", "start": 0, "end": 1, "alignment_status": "aligned", "recovered": True}],
            config=segmenter.SegmenterConfig(learning_sentence_mode=True))
        self.assertFalse(result[0]["alignment_review_required"])
        self.assertTrue(result[0]["text_review_required"])
        self.assertEqual(result[0]["text_review_word_count"], 1)

    def test_learning_sentence_keeps_unresolved_timing_warning(self):
        result, _ = segmenter.segment_words([
            {"text": "Hello", "start": 0, "end": 1, "alignment_status": "estimated_review_required"},
            {"text": "there.", "start": .5, "end": .7, "alignment_status": "aligned"}],
            config=segmenter.SegmenterConfig(learning_sentence_mode=True))
        self.assertTrue(result[0]["alignment_review_required"])
        self.assertEqual(result[0]["alignment_review_word_count"], 1)
        self.assertEqual(result[0]["end"], 1)

    def test_short_complete_reply_can_end_with_auxiliary(self):
        words = segmenter.normalize_words([{"text": w, "start": i, "end": i+.5}
                                           for i,w in enumerate("It is. Yes, indeed.".split())])
        features = segmenter.analyze_boundaries(words)
        features[2].sat_probability = .95
        result, _ = segmenter.learning_sentences(words, features, segmenter.SegmenterConfig(learning_sentence_mode=True))
        self.assertEqual(result[0]["text"], "It is.")

    def test_complete_sentence_ending_that_does_not_absorb_next_sentence(self):
        text = "It gets more than that. Yeah, the difference is noticeable."
        words = segmenter.normalize_words([{"text": w, "start": i*.4, "end": i*.4+.3}
                                           for i,w in enumerate(text.split())])
        features = segmenter.analyze_boundaries(words)
        features[5].protected_by_dependency = True
        result, _ = segmenter.learning_sentences(words, features, segmenter.SegmenterConfig(learning_sentence_mode=True))
        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["text"], "It gets more than that.")

    def test_alignment_score_is_not_recognition_confidence(self):
        word = segmenter.normalized_word({"text": "But", "start": 0, "end": .1,
            "aligned_by": "whisperx", "probability": .05, "alignment_score": .05}, 0)
        self.assertIsNone(word["probability"])
        self.assertEqual(word["alignment_score"], .05)

    def test_learning_sentence_not_cut_by_display_duration(self):
        text = "We will continue walking through the mountains until we finally reach the village."
        words = segmenter.normalize_words([{"text": w, "start": i*1.5, "end": i*1.5+1}
                                           for i, w in enumerate(text.split())])
        config = segmenter.SegmenterConfig(learning_sentence_mode=True)
        result, _ = segmenter.learning_sentences(words, segmenter.analyze_boundaries(words), config)
        self.assertEqual([s["text"] for s in result], [text])
        self.assertGreater(len(result[0]["display_cues"]), 1)
        self.assertEqual(result[0]["word_end"], len(words))
        self.assertTrue(all(c["learning_sentence_id"] == 0 for c in result[0]["display_cues"]))

    def test_learning_mode_never_deletes_weak_function_word(self):
        raw = [{"text": "But", "start": 0, "end": .1, "probability": .01},
               {"text": "then", "start": 8, "end": 9},
               {"text": "everything", "start": 9, "end": 10},
               {"text": "changed.", "start": 10, "end": 11}]
        result, _ = segmenter.segment_words(raw, config=segmenter.SegmenterConfig(learning_sentence_mode=True))
        self.assertEqual(" ".join(s["text"] for s in result), "But then everything changed.")

    def test_noun_and_entity_protection_uses_global_chunk_offset(self):
        words = segmenter.normalize_words([
            {"text": word, "start": i, "end": i+.5}
            for i, word in enumerate("New York today New Delhi tomorrow".split())
        ])
        class FakeDoc:
            def __init__(self, text):
                span = SimpleNamespace(start_char=0, end_char=len(text.rsplit(" ", 1)[0]))
                self.noun_chunks, self.ents = [span], [span]
            def __iter__(self):
                return iter([])
        features = segmenter.analyze_boundaries(words, spacy_nlp=FakeDoc,
            config=segmenter.SegmenterConfig(analysis_chunk_words=3))
        for attribute in ("protected_by_noun_chunk", "protected_by_entity"):
            self.assertEqual([f.index for f in features if getattr(f, attribute)], [1, 4])

    def test_oversize_token_is_retained_and_reported_not_whole_film_fallback(self):
        words = segmenter.normalize_words([
            {"text": "Hello.", "start": 0, "end": 20},
            {"text": "World.", "start": 21, "end": 22},
        ])
        features = segmenter.analyze_boundaries(words)
        segments, debug = segmenter.optimize_segments(words, features)
        self.assertEqual([s["text"] for s in segments], ["Hello.", "World."])
        self.assertEqual(len(debug["oversize_tokens"]), 1)

    def test_oversize_text_is_not_dropped(self):
        words = segmenter.normalize_words([{"text": "x"*200, "start": 0, "end": 1}])
        result, debug = segmenter.optimize_segments(words, segmenter.analyze_boundaries(words))
        self.assertEqual(result[0]["text"], "x"*200)
        self.assertEqual(len(debug["oversize_tokens"]), 1)


if __name__ == "__main__":
    unittest.main()
