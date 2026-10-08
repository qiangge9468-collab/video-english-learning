import sys
from pathlib import Path
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/"versions/v2.1.0"))
from guarded_alignment import align_guarded, candidate_issues, source_drift_issues


class GuardedAlignmentTests(unittest.TestCase):
    def test_high_ctc_scores_do_not_authorize_coherent_large_shift(self):
        old = [{'segment_id': 0, 'text': t, 'start': 6+i*.3, 'end': 6+i*.3+.2}
               for i,t in enumerate(['We', 'are', 'here.'])]
        def align(_):
            return [{'word': w['text'], 'start': w['start']-4, 'end': w['end']-4, 'score': .99} for w in old]
        _, result, debug = align_guarded([{'id': 0, 'start': 0, 'end': 9, 'text': 'We are here.'}], old, align, 9)
        self.assertEqual([w['start'] for w in result], [w['start'] for w in old])
        self.assertTrue(all(w['alignment_status'] == 'source_timing_fallback' for w in result))
        self.assertEqual(debug['review_required_segments'], 1)

    def test_estimated_or_old_alignment_times_are_not_independent_anchors(self):
        original = [{'start': i, 'end': i+.2, 'aligned_by': 'whisperx'} for i in range(3)]
        candidate = [{'start': i+4, 'end': i+4.2} for i in range(3)]
        self.assertEqual(source_drift_issues(original, candidate), [])
        for w in original:
            w['aligned_by'] = 'asr'
            w['asr_timing_estimated'] = True
        self.assertEqual(source_drift_issues(original, candidate), [])

    def test_small_refinements_allowed_but_single_large_shift_requires_review(self):
        original = [{'start': i, 'end': i+.2} for i in range(3)]
        candidate = [{'start': i+.2, 'end': i+.4} for i in range(3)]
        self.assertEqual(source_drift_issues(original, candidate), [])
        candidate[1] = {'start': 8, 'end': 8.2}
        self.assertEqual(source_drift_issues(original, candidate), ['source_time_disagreement:1'])

    def test_two_word_utterance_is_not_exempt_from_drift_guard(self):
        old = [{'text': t, 'segment_id': 0, 'start': 7+i*.4, 'end': 7.3+i*.4}
               for i,t in enumerate(['Hello', 'there.'])]
        def align(_):
            return [{'word': w['text'], 'start': w['start']-4, 'end': w['end']-4, 'score': .99} for w in old]
        _, result, _ = align_guarded([{'start': 0, 'end': 9, 'text': 'Hello there.'}], old, align, 9)
        self.assertEqual([w['start'] for w in result], [7, 7.4])
        self.assertTrue(all(w['alignment_status'] == 'source_timing_fallback' for w in result))

    def test_mixed_fallback_cannot_reorder_utterance(self):
        old = [{'text': t, 'segment_id': 0, 'start': i, 'end': i+.2}
               for i,t in enumerate(['We', 'are', 'here.'])]
        def align(_):
            return [{'word': 'We', 'start': .1, 'end': .3, 'score': .9},
                    {'word': 'are', 'start': 2.8, 'end': 3, 'score': .99},
                    {'word': 'here.', 'start': 3.1, 'end': 3.3, 'score': .9}]
        _, result, debug = align_guarded([{'start': 0, 'end': 4, 'text': 'We are here.'}], old, align, 4)
        self.assertEqual([w['text'] for w in result], ['We', 'are', 'here.'])
        self.assertEqual(result[1]['start'], 1)
        self.assertEqual(result[2]['start'], 3.1)
        self.assertIn('candidate_words', debug['segments'][0]['attempts'][0])

    def test_fallback_propagates_only_to_crossing_neighbor(self):
        old = [{'text': t, 'segment_id': 0, 'start': i+4, 'end': i+4.2}
               for i,t in enumerate(['We', 'are', 'here.'])]
        def align(_):
            return [{'word': 'We', 'start': 1, 'end': 1.2, 'score': .99},
                    {'word': 'are', 'start': 3.7, 'end': 3.9, 'score': .99},
                    {'word': 'here.', 'start': 6.1, 'end': 6.3, 'score': .9}]
        _, result, debug = align_guarded([{'start': 0, 'end': 8, 'text': 'We are here.'}], old, align, 8)
        self.assertEqual([w['text'] for w in result], ['We', 'are', 'here.'])
        self.assertEqual([w['start'] for w in result], [4, 5, 6.1])
        self.assertIn('fallback_order_conflict:1', debug['segments'][0]['remaining_issues'])

    def test_fallback_never_restores_timestamp_beyond_audio(self):
        source = [{'id': 0, 'start': 0, 'end': 1, 'text': 'One'}]
        old = [{'segment_id': 0, 'start': 50, 'end': 51, 'text': 'One'}]
        _, result, _ = align_guarded(source, old, lambda _: [{'word': 'One'}], 1)
        self.assertEqual(result[0]['alignment_status'], 'estimated_review_required')
        self.assertGreaterEqual(result[0]['start'], 0)
        self.assertLessEqual(result[0]['end'], 1)

    def test_untimed_number_does_not_invalidate_other_word_times(self):
        source = [{'start': 0, 'end': 4, 'text': 'Paid $25 today.'}]
        def align(_):
            return [{'word': 'Paid', 'start': .3, 'end': .7, 'score': .9},
                    {'word': '$25'},
                    {'word': 'today.', 'start': 2.5, 'end': 2.9, 'score': .9}]
        _, words, debug = align_guarded(source, [], align, 4)
        self.assertEqual([w['alignment_status'] for w in words],
                         ['aligned', 'estimated_review_required', 'aligned'])
        self.assertEqual((words[0]['start'], words[0]['end']), (.3, .7))
        self.assertEqual((words[2]['start'], words[2]['end']), (2.5, 2.9))
        self.assertEqual((words[1]['start'], words[1]['end']), (.7, 2.5))
        self.assertEqual(debug['review_required_segments'], 1)

    def test_low_score_warning_is_local_but_keeps_segment_review(self):
        def align(_):
            return [{'word': 'We', 'start': .1, 'end': .5, 'score': .9},
                    {'word': 'agree.', 'start': .6, 'end': .9, 'score': .05}]
        segments, words, _ = align_guarded([{'start': 0, 'end': 1, 'text': 'We agree.'}], [], align, 1)
        self.assertEqual(words[0]['alignment_status'], 'aligned')
        self.assertEqual(words[1]['alignment_status'], 'review_required')
        self.assertTrue(segments[0]['alignment_review_required'])

    def test_no_missing_words_when_aligner_drops_token(self):
        source = [{"id": 0, "start": 1, "end": 3, "text": "Made it."}]
        old = [{"segment_id": 0, "text": "Made", "start": 1, "end": 1.5, "probability": .9},
               {"segment_id": 0, "text": "it.", "start": 1.6, "end": 2, "probability": .8}]
        segments, words, debug = align_guarded(source, old, lambda _: [{"word": "Made", "start": 1, "end": 2}], 10)
        self.assertEqual([w["text"] for w in words], ["Made", "it."])
        self.assertTrue(all(w["alignment_status"] == "source_timing_fallback" for w in words))
        self.assertEqual(words[1]["asr_probability"], .8)
        self.assertEqual(debug["review_required_segments"], 1)
        self.assertEqual(segments[0]["word_end"], 2)

    def test_untimed_numbers_remain_explicitly_unresolved(self):
        _, words, _ = align_guarded([{"start": 0, "end": 1, "text": "$4,000"}], [],
                                   lambda _: [{"word": "$4,000"}], 1)
        self.assertEqual(words[0]["text"], "$4,000")
        self.assertEqual(words[0]["alignment_status"], "estimated_review_required")
        self.assertIsNone(words[0]["alignment_score"])

    def test_retry_bounded_by_neighbor_and_accepts_improvement(self):
        windows = []
        source = [{"start": 0, "end": 1, "text": "One"}, {"start": 1.2, "end": 2, "text": "two"}]
        def align(window):
            windows.append(dict(window))
            if window["text"] == "One" and window["end"] == 1:
                return [{"word": "One"}]
            return [{"word": window["text"], "start": window["start"]+.01, "end": window["end"]-.01, "score": .9}]
        _, words, debug = align_guarded(source, [], align, 3)
        self.assertEqual(windows[1]["end"], 1.2)
        self.assertEqual(debug["review_required_segments"], 0)
        self.assertEqual(words[0]["alignment_status"], "aligned")

    def test_repeated_words_have_distinct_source_ids(self):
        source = [{"start": 0, "end": 2, "text": "one one"}]
        def align(_):
            return [{"word": "one", "start": 0, "end": 1, "score": .9},
                    {"word": "one", "start": .5, "end": 2, "score": .9}]
        _, words, _ = align_guarded(source, [], align, 2)
        self.assertEqual(len(words), 2)
        self.assertEqual([w["source_token_index"] for w in words], [0, 1])

    def test_low_ctc_score_is_not_low_asr_probability(self):
        old = [{"segment_id": 0, "text": "But", "start": 0, "end": 1, "probability": .95}]
        _, words, _ = align_guarded([{"start": 0, "end": 1, "text": "But"}], old,
            lambda _: [{"word": "But", "start": 0, "end": 1, "score": .05}], 1)
        self.assertEqual(words[0]["probability"], .95)
        self.assertEqual(words[0]["alignment_score"], .05)
        self.assertEqual(words[0]["alignment_status"], "review_required")

    def test_legacy_score_never_reused_as_asr_probability(self):
        old = [{"segment_id": 0, "text": "But", "start": 0, "end": 1, "probability": .95, "aligned_by": "whisperx"}]
        _, words, _ = align_guarded([{"start": 0, "end": 1, "text": "But"}], old,
            lambda _: [{"word": "But", "start": 0, "end": 1, "score": .9}], 1)
        self.assertIsNone(words[0]["probability"])

    def test_nan_and_backwards_candidates_rejected(self):
        issues = candidate_issues(["we", "are"], [{"word": "we", "start": 0, "end": float("nan")},
                                                  {"word": "are", "start": 2, "end": 1}], {"start": 0, "end": 3})
        self.assertEqual(len(issues), 2)

    def test_same_words_wrong_order_is_not_coverage(self):
        self.assertEqual(candidate_issues(["we", "are"], [{"word": "are"}, {"word": "we"}], {"start": 0, "end": 2}),
                         ["token_sequence_changed"])

    def test_interleaved_source_segments_keep_identity_and_playback_order(self):
        source = [{"start": 0, "end": 4, "text": "one three"},
                  {"start": 1, "end": 2, "text": "two"}]
        def align(part):
            if part["text"] == "two":
                return [{"word": "two", "start": 1, "end": 2, "score": .9}]
            return [{"word": "one", "start": 0, "end": .5, "score": .9},
                    {"word": "three", "start": 3, "end": 4, "score": .9}]
        segments, words, debug = align_guarded(source, [], align, 5)
        self.assertEqual([w["text"] for w in words], ["one", "two", "three"])
        self.assertEqual(segments[0]["word_indices"], [0, 2])
        self.assertFalse(segments[0]["word_range_contiguous"])
        self.assertEqual(debug["word_count"], 3)


if __name__ == "__main__":
    unittest.main()
