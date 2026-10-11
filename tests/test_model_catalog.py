import json
import unittest
from unittest.mock import Mock, patch

from refresh_model_catalog import list_models


class ModelCatalogTests(unittest.TestCase):
    @patch.dict('os.environ', {'TEST_KEY': 'test-secret'})
    @patch('refresh_model_catalog.urlopen')
    def test_anthropic_pagination_and_configs(self, request):
        """Collect paginated model lists and include key names without leaking credentials."""
        stream = Mock()
        stream.read.side_effect = [json.dumps({'data': [{'id': 'model-b'}], 'has_more': True, 'last_id': 'model-b'}),
                                   json.dumps({'data': [{'id': 'model-a'}], 'has_more': False})]
        request.return_value.__enter__.return_value = stream
        entries = list_models('anthropic', 'TEST_KEY')
        self.assertEqual([entry['model'] for entry in entries], ['model-a', 'model-b'])
        self.assertIn('after_id=model-b', request.call_args.args[0].full_url)
        self.assertEqual(entries[0]['player_config']['api_key_env'], 'TEST_KEY')
        self.assertNotIn('test-secret', json.dumps(entries))

    @patch.dict('os.environ', {'TEST_KEY': 'test-secret'})
    @patch('refresh_model_catalog.urlopen')
    def test_openai_lists_all_model_types(self, request):
        """Keep every returned OpenAI model rather than silently filtering specialized models."""
        stream = Mock()
        stream.read.return_value = json.dumps({'data': [{'id': 'gpt-test'}, {'id': 'image-test'}]})
        request.return_value.__enter__.return_value = stream
        self.assertEqual(len(list_models('openai', 'TEST_KEY')), 2)
        self.assertEqual(request.call_count, 1)
