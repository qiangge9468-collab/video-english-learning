from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]/'versions/v2.1.0'))
from context_translation import LocalContextTranslator, validate, validate_endpoint


class ContextRuntimeTests(unittest.TestCase):
    def client(self):
        c = LocalContextTranslator('.')
        c.ensure_ready = Mock(return_value='digest')
        c.unload = Mock()
        return c

    def test_only_loopback_without_redirect_target_credentials_or_query(self):
        self.assertEqual(validate_endpoint('http://127.0.0.1:11435/'), 'http://127.0.0.1:11435')
        for uri in ('https://example.com', 'http://localhost:1234', 'http://127.0.0.1:1234/a',
                    'http://a@127.0.0.1:1234', 'http://127.0.0.1:1234?q=x', 'http://127.0.0.1:1234#x'):
            with self.subTest(uri=uri), self.assertRaises(ValueError):
                validate_endpoint(uri)

    def test_ids_and_numbers_guard(self):
        with self.assertRaises(ValueError):
            validate({'1': '你好'}, {0: 'Hello'})
        row = validate({'0': '50美元'}, {0: '$5,000'})[0]
        self.assertEqual(row['translation_status'], 'review_required')

    def test_full_context_targets_preserved_and_unloaded(self):
        c = self.client()
        c.batch = Mock(side_effect=lambda texts, ids: validate({str(i): '你好' for i in ids}, {i: texts[i] for i in ids}))
        fallback, release = Mock(), Mock()
        texts = ['Hello'] * 25
        rows = c.translate(texts, lambda _: None, fallback, lambda a, b: 'generated_unreviewed', release)
        self.assertEqual(len(rows), 25)
        self.assertEqual([len(call.args[1]) for call in c.batch.call_args_list], [12, 12, 1])
        self.assertEqual(c.batch.call_args_list[-1].args[0], texts)
        release.assert_called_once()
        fallback.assert_not_called()
        c.unload.assert_called_once()

    def test_fluent_translation_does_not_hide_incomplete_source(self):
        row = validate({'0': '博物馆解释了每个展品的原理。'}, {0: 'Museum explains the science behind each'})[0]
        self.assertEqual(row['translation_status'], 'review_required')
        self.assertIn('source_fragment', row['translation_warnings'])

    def test_backend_disconnect_falls_back_once_and_unloads_first(self):
        c = self.client()
        c.batch = Mock(side_effect=OSError('offline'))
        def fallback(texts):
            c.unload.assert_called_once()
            return ['你好'] * len(texts)
        rows = c.translate(['Hello']*24, lambda _: None, fallback,
                           lambda a, b: 'generated_unreviewed', Mock())
        c.batch.assert_called_once()
        self.assertTrue(all(r['translation_provider'] == 'legacy_fallback' for r in rows))

    def test_bad_batch_retries_each_id_without_dropping_words(self):
        c = self.client()
        c.batch = Mock(side_effect=[ValueError('missing ID'),
            validate({'0': '你好'}, {0: 'Hello'}), validate({'1': '再见'}, {1: 'Bye'})])
        rows = c.translate(['Hello', 'Bye'], lambda _: None, Mock(),
                           lambda a, b: 'generated_unreviewed', Mock())
        self.assertEqual([r['translation'] for r in rows], ['你好', '再见'])

    def test_pure_counts_do_not_load_model(self):
        c = self.client()
        rows = c.translate(['one two'], lambda _: '1、2', Mock(), Mock(), Mock())
        c.ensure_ready.assert_not_called()
        self.assertEqual(rows[0]['translation_status'], 'deterministic')

    def test_truncated_answer_rejected(self):
        c = self.client()
        c.request = Mock(return_value={'done': True, 'done_reason': 'length', 'message': {'content': '{"0":"你好"}'}})
        with self.assertRaises(ValueError):
            c.batch(['Hello'], [0])

    def test_remote_model_tag_rejected_without_inference(self):
        c = LocalContextTranslator('.')
        c.request = Mock(return_value={'models': [{'name': c.model, 'remote_model': 'cloud-model'}]})
        with self.assertRaises(RuntimeError):
            c.ensure_ready()


if __name__ == '__main__':
    unittest.main()
