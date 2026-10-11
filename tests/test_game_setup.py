import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from game_setup import GameSetup, model_choices


class GameSetupTests(unittest.TestCase):
    @patch('game_setup.load_config', side_effect=lambda path, settings: settings)
    def test_claude_effort_is_selectable_and_saved(self, validate):
        """Enable Claude effort selection and preserve it in the launched game configuration."""
        root = tk.Tk()
        root.withdraw()
        try:
            launch = Mock()
            setup = GameSetup(root, launch)
            with tempfile.TemporaryDirectory() as folder:
                setup.folder = Path(folder)
                setup.players['white'][0].set('human')
                setup.update_player('white', True)
                setup.players['black'][0].set('anthropic')
                setup.update_player('black', True)
                self.assertEqual(str(setup.players['black'][4].cget('state')), 'readonly')
                self.assertNotIn('none', setup.players['black'][4].cget('values'))
                setup.players['black'][1].set('claude-sonnet-5')
                setup.players['black'][2].set('low')
                setup.start_game()
                self.assertEqual(launch.call_args.args[0]['black']['reasoning_effort'], 'low')
                saved = json.loads((Path(folder) / 'match_config.json').read_text())
                self.assertEqual(saved['black']['reasoning_effort'], 'low')
        finally:
            root.destroy()
    def test_model_suggestions_exclude_specialized_models(self):
        """Offer likely text models while filtering obvious image/audio and embedding entries."""
        catalog = {'providers': {'openai': [{'model': model} for model in
                                           ('gpt-5.6-luna', 'gpt-image-1', 'gpt-audio', 'text-embedding-3-small')]}}
        self.assertEqual(model_choices(catalog, 'openai'), ['gpt-5.6-luna'])

    @patch.dict('os.environ', {}, clear=True)
    def test_local_match_start_and_remembered_choices(self):
        """Start local players without API keys and remember settings without credentials."""
        root = tk.Tk()
        root.withdraw()
        try:
            launch = Mock()
            setup = GameSetup(root, launch)
            with tempfile.TemporaryDirectory() as folder:
                setup.folder = Path(folder)
                for side, provider in (('white', 'random'), ('black', 'human')):
                    setup.players[side][0].set(provider)
                    setup.update_player(side, True)
                    self.assertEqual(str(setup.players[side][3].cget('state')), 'disabled')
                setup.auto.set(True)
                setup.start_game()
                launch.assert_called_once()
                config, auto = launch.call_args.args
                self.assertTrue(auto)
                self.assertEqual(config['white'], {'provider': 'random'})
                saved = json.loads((Path(folder) / 'match_config.json').read_text())
                self.assertEqual(saved['black'], {'provider': 'human'})
        finally:
            root.destroy()
