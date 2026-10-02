import json
import os
import queue
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from ai_players import choose_move, load_config, request_text, validated_move
from simple_chess import ChessGame, ChessUI, START_STATE


class AIPlayersTests(unittest.TestCase):
    def setUp(self):
        """Prepare a starting game, a valid example response, and shared request settings."""
        self.game = ChessGame()
        self.response = 'e2e4'
        self.config = {'attempts': 2, 'timeout_seconds': 10, 'max_output_tokens': 2048}

    def test_validate_and_reject_invalid_responses(self):
        """Accept legal UCI moves and reject illegal moves, board states, and extra text."""
        self.assertEqual(validated_move(self.game, self.response), 'e2e4')
        self.assertEqual(self.game.save(), START_STATE)
        self.assertEqual(validated_move(self.game, ' e2e4\n'), 'e2e4')
        for response in (START_STATE, 'e2e5', 'e7e5', 'e2e4 e7e5', 'e2e4\ne7e5',
                         'My move is e2e4', 'Nf3', '```\ne2e4\n```'):
            with self.assertRaises(ValueError):
                validated_move(self.game, response)

    def test_special_moves(self):
        """Verify response validation handles castling, promotion, and en passant."""
        cases = [('r3k2r/8/8/8/8/8/8/R3K2R w KQkq -;-', 'e1g1'),
                 ('7k/P7/8/8/8/8/8/7K w - -;-', 'a7a8n'),
                 ('7k/8/8/3pP3/8/8/8/7K w - d6;d7d5', 'e5d6')]
        for state, move in cases:
            original = ChessGame(state)
            result = ChessGame(state)
            self.assertTrue(result.move(move[:2], move[2:4], move[4:] or None)[0])
            self.assertEqual(validated_move(original, move), move)
            self.assertEqual(original.save(), state)

    def test_black_knight_move_updates_board_in_engine(self):
        """Validate the reported b8c6 case and let the engine remove the knight from b8."""
        game = ChessGame('rnbqkbnr/pppp1ppp/8/4p3/4P3/5N2/PPPP1PPP/RNBQKB1R b KQkq -;g1f3')
        move = validated_move(game, 'b8c6')
        self.assertTrue(game.move(move[:2], move[2:4])[0])
        self.assertIsNone(game.board[0][1])
        self.assertEqual(game.board[2][2], 'n')

    @patch('ai_players.request_text')
    def test_prompt_and_retry(self, request):
        """Check prompt contents, successful retries, and failure after the retry limit."""
        request.side_effect = ['bad', self.response]
        self.assertEqual(choose_move(self.game, {}, self.config), 'e2e4')
        prompt = request.call_args_list[0].args[1]
        self.assertIn('as White', prompt)
        self.assertIn(START_STATE, prompt)
        self.assertIn('Last move: -', prompt)
        self.assertIn('e2e4', prompt)
        self.assertIn('Return ONLY one move', prompt)
        self.assertEqual(request.call_count, 2)
        request.side_effect = ['bad', 'bad']
        with self.assertRaises(RuntimeError):
            choose_move(self.game, {}, self.config)

    @patch('ai_players.request_text')
    def test_exchange_reports_exact_prompt_and_raw_responses(self, request):
        """Report each actual prompt and unmodified answer, including rejected retry responses."""
        request.side_effect = ['bad answer', self.response]
        events = []
        choose_move(self.game, {}, self.config, lambda *event: events.append(event))
        self.assertEqual([event[0] for event in events],
                         ['sent', 'received', 'validation', 'sent', 'received'])
        self.assertEqual(events[0][2], request.call_args_list[0].args[1])
        self.assertEqual(events[1], ('received', 1, 'bad answer'))
        self.assertEqual(events[3][2], request.call_args_list[1].args[1])
        self.assertEqual(events[4], ('received', 2, self.response))

    @patch.dict(os.environ, {'OPENAI_API_KEY': 'test-openai', 'ANTHROPIC_API_KEY': 'test-claude'})
    @patch('ai_players.urlopen')
    def test_provider_requests(self, urlopen):
        """Check both providers' request payloads, authentication, and response extraction."""
        for provider, response in (
            ('openai', {'output': [{'type': 'message', 'content': [{'type': 'output_text', 'text': self.response}]}]}),
            ('anthropic', {'content': [{'type': 'text', 'text': self.response}]}),
        ):
            stream = Mock()
            stream.read.return_value = json.dumps(response)
            urlopen.return_value.__enter__.return_value = stream
            self.assertEqual(request_text({'provider': provider, 'model': 'test-model'}, 'prompt', self.config), self.response)
            request = urlopen.call_args.args[0]
            payload = json.loads(request.data)
            self.assertEqual(payload['model'], 'test-model')
            self.assertEqual(urlopen.call_args.kwargs['timeout'], 10)
            if provider == 'openai':
                self.assertEqual(payload['input'], 'prompt')
                self.assertEqual(request.get_header('Authorization'), 'Bearer test-openai')
            else:
                self.assertEqual(payload['messages'][0]['content'], 'prompt')
                self.assertEqual(request.get_header('X-api-key'), 'test-claude')

    @patch.dict(os.environ, {}, clear=True)
    def test_config_and_secrets(self):
        """Check required keys, local credentials, environment precedence, and config limits."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'white': {'provider': 'openai', 'model': 'test'}}))
            with self.assertRaisesRegex(ValueError, 'OPENAI_API_KEY'):
                load_config(path)
            (path.parent / '.env').write_text('OPENAI_API_KEY=local-key\n')
            config = load_config(path)
            self.assertEqual(config['black']['provider'], 'human')
            os.environ['OPENAI_API_KEY'] = 'environment-key'
            load_config(path)
            self.assertEqual(os.environ['OPENAI_API_KEY'], 'environment-key')
            path.write_text(json.dumps({'attempts': 0}))
            with self.assertRaises(ValueError):
                load_config(path)

    def test_stale_result_cannot_change_reset_board(self):
        """Ensure a result from an earlier AI run cannot modify the current board."""
        ui = ChessUI.__new__(ChessUI)
        ui.root = Mock()
        ui.game = self.game
        ui.ai_results = queue.Queue()
        ui.ai_events = queue.Queue()
        ui.ai_results.put((0, START_STATE, 'e2e4', None))
        ui.ai_busy = True
        ui.ai_running = True
        ui.ai_generation = 1
        ui.ai_plies = 0
        ui.ai_config = {'white': {'provider': 'human'}, 'max_plies': 300}
        ui.refresh = Mock()
        ui.poll_ai()
        self.assertEqual(ui.game.save(), START_STATE)
        self.assertFalse(ui.ai_busy)

    @patch.dict(os.environ, {'ANTHROPIC_API_KEY': ''}, clear=True)
    def test_env_bom_and_empty_environment(self):
        """Load a Windows UTF-8 BOM file even when an inherited key variable is empty."""
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'config.json'
            path.write_text(json.dumps({'black': {'provider': 'anthropic', 'model': 'test'}}))
            (path.parent / '.env').write_text('ANTHROPIC_API_KEY=test-key\n', encoding='utf-8-sig')
            self.assertEqual(load_config(path)['black']['provider'], 'anthropic')
            self.assertEqual(os.environ['ANTHROPIC_API_KEY'], 'test-key')

    def test_one_request_applies_only_one_move(self):
        """Ensure a successful AI result stops play until another manual request."""
        ui = ChessUI.__new__(ChessUI)
        ui.root = Mock()
        ui.game = self.game
        ui.ai_results = queue.Queue()
        ui.ai_events = queue.Queue()
        ui.ai_results.put((0, START_STATE, 'e2e4', None))
        ui.ai_busy = True
        ui.ai_running = True
        ui.ai_generation = 0
        ui.ai_plies = 0
        ui.ai_config = {'white': {'provider': 'openai'}, 'black': {'provider': 'anthropic'}, 'max_plies': 300}
        ui.ai_button = Mock()
        ui.state_var = Mock()
        ui.refresh = Mock()
        with patch('simple_chess.threading.Thread') as thread:
            ui.poll_ai()
            ui.poll_ai()
            thread.assert_not_called()
        self.assertEqual(ui.game.last_move, 'e2e4')
        self.assertEqual(ui.game.turn, 'b')
        self.assertFalse(ui.ai_running)
        self.assertFalse(ui.ai_busy)
        self.assertEqual(ui.ai_plies, 1)

    def test_request_ignores_duplicate_clicks_and_human_turns(self):
        """Ensure manual requests cannot queue duplicate moves or request a human player's turn."""
        ui = ChessUI.__new__(ChessUI)
        ui.game = self.game
        ui.ai_config = {'white': {'provider': 'openai'}}
        ui.ai_busy = False
        ui.ai_running = False
        ui.selected = (6, 4)
        ui.legal_targets = {(4, 4)}
        ui.refresh = Mock()
        ui.request_ai_move()
        self.assertTrue(ui.ai_running)
        self.assertIsNone(ui.selected)
        ui.request_ai_move()
        ui.refresh.assert_called_once()
        ui.ai_running = False
        ui.ai_config['white']['provider'] = 'human'
        ui.request_ai_move()
        self.assertFalse(ui.ai_running)


if __name__ == '__main__':
    unittest.main()
