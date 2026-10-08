from dataclasses import replace
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"versions/v2.1.0"))
from speaker_boundary_evidence import boundary_evidence
from semantic_caption_segmenter_v206 import BoundaryFeatures, SegmenterConfig, learning_sentences, apply_speaker_evidence


class SpeakerEvidenceTests(unittest.TestCase):
    def test_question_final_verb_needs_both_text_models_and_audio(self):
        words = [{'text': 'do'}, {'text': 'update'}]
        features = [BoundaryFeatures(index=i) for i in range(3)]
        f = features[1]
        f.previous_pos, f.previous_dependency = 'VERB', 'ROOT'
        f.sat_probability, f.restored_terminal_probability = .99, .92
        speaker = {'requires_semantic_support':True,'boundaries':[{'word_boundary':1}]}
        self.assertEqual(apply_speaker_evidence(words,features,speaker,SegmenterConfig()),[])
        self.assertTrue(f.acoustic_speaker_change)
        f.acoustic_speaker_change = False
        f.restored_terminal_probability = .3
        self.assertEqual(apply_speaker_evidence(words,features,speaker,SegmenterConfig()),[1])
        self.assertFalse(f.acoustic_speaker_change)

    def test_audio_cannot_split_pronoun_auxiliary(self):
        words = [{'text':'we'}, {'text':'are'}]
        f = BoundaryFeatures(index=1,sat_probability=.99,restored_terminal_probability=.99,
                             previous_pos='PRON',previous_dependency='nsubj',protected_by_pos_pair=True)
        self.assertEqual(apply_speaker_evidence(words,[BoundaryFeatures(index=0),f,BoundaryFeatures(index=2)],
            {'requires_semantic_support':True,'boundaries':[{'word_boundary':1}]},SegmenterConfig()),[1])

    def data(self):
        return ([{"text": "Yes", "start": 0, "end": .5}, {"text": "No", "start": .6, "end": 1.1}],
                [{"speaker": "a", "start": 0, "end": .5}, {"speaker": "b", "start": .6, "end": 1.1}])

    def test_clear_turn_produces_boundary_without_rewriting_words(self):
        words, turns = self.data()
        original = [dict(w) for w in words]
        result = boundary_evidence(words, turns)
        self.assertEqual([b["word_boundary"] for b in result["boundaries"]], [1])
        self.assertEqual(words, original)

    def test_simultaneous_speech_does_not_force_cut(self):
        words, turns = self.data()
        self.assertEqual(boundary_evidence(words, turns, [{"start": .4, "end": .8}])["boundaries"], [])

    def test_weak_coverage_does_not_force_cut(self):
        words, turns = self.data()
        turns[1]["start"] = .9
        self.assertEqual(boundary_evidence(words, turns)["boundaries"], [])

    def test_alignment_fallback_does_not_force_cut(self):
        words, turns = self.data()
        words[1]["alignment_status"] = "source_fallback"
        self.assertEqual(boundary_evidence(words, turns)["boundaries"], [])

    def test_nonexclusive_input_is_rejected(self):
        words, turns = self.data()
        turns[0]["end"] = .8
        with self.assertRaises(ValueError):
            boundary_evidence(words, turns)

    def test_speaker_boundary_is_opt_in_and_reviewable(self):
        words, _ = self.data()
        features = [BoundaryFeatures(index=i) for i in range(3)]
        features[1].acoustic_speaker_change = True
        config = SegmenterConfig(learning_sentence_mode=True)
        old, _ = learning_sentences(words, features, config)
        new, debug = learning_sentences(words, features, replace(config, learning_speaker_boundaries=True))
        self.assertEqual(len(old), 1)
        self.assertEqual(len(new), 2)
        self.assertTrue(all(u["boundary_review_required"] for u in new))
        self.assertEqual(debug["warnings"][0]["kind"], "acoustic_speaker_boundary")


if __name__ == "__main__":
    unittest.main()
