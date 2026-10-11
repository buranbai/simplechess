import json
import tempfile
import tkinter as tk
import unittest
from pathlib import Path
from unittest.mock import patch

from simple_chess import ChessGame, ChessUI, START_STATE, replay_positions


class ReplayTests(unittest.TestCase):
    def test_replay_from_custom_black_start(self):
        """Rebuild games begun from custom positions and reject an inconsistent final board."""
        start = ChessGame()
        start.move('e2', 'e4')
        initial = start.save()
        start.move('e7', 'e5')
        start.move('g1', 'f3')
        history = [[1, '', 'e7e5'], [2, 'g1f3', '']]
        frames = replay_positions(initial, history, start.save())
        self.assertEqual(len(frames), 3)
        self.assertEqual(frames[0], initial)
        with self.assertRaises(ValueError):
            replay_positions(initial, history, START_STATE)

    def test_save_load_and_replay_without_api_requests(self):
        """Save matchup details and replay loaded moves locally without duplicating history."""
        root = tk.Tk()
        root.withdraw()
        try:
            ui = ChessUI(root)
            ui.game_players = {'white': {'provider': 'openai', 'model': 'example',
                                         'reasoning_effort': 'low', 'api_key': 'never-save'},
                               'black': {'provider': 'random'}}
            for move in ('e2e4', 'e7e5'):
                ui.game.move(move[:2], move[2:])
                ui.record_move()
            final = ui.game.save()
            with tempfile.TemporaryDirectory() as folder:
                path = Path(folder) / 'game.json'
                with patch('simple_chess.filedialog.asksaveasfilename', return_value=str(path)), patch('simple_chess.messagebox.showinfo'):
                    ui.save_game()
                data = json.loads(path.read_text())
                self.assertEqual(data['initial_state'], START_STATE)
                self.assertEqual(data['players']['black']['provider'], 'random')
                self.assertNotIn('never-save', path.read_text())
                ui.reset()
                with patch('simple_chess.filedialog.askopenfilename', return_value=str(path)):
                    ui.load_game()
                self.assertEqual(ui.game_players['white']['model'], 'example')
                with patch('simple_chess.choose_move') as request, patch.object(ui, 'animate_move'):
                    ui.toggle_replay()
                    self.assertEqual(ui.game.save(), START_STATE)
                    ui.replay_tick()
                    self.assertEqual(ui.game.last_move, 'e2e4')
                    ui.toggle_replay()
                    ui.replay_tick()
                    self.assertEqual(ui.game.last_move, 'e2e4')
                    ui.toggle_replay()
                    ui.replay_tick()
                    ui.replay_tick()
                    self.assertEqual(ui.game.save(), final)
                    self.assertFalse(ui.replay_mode)
                    self.assertEqual(len(ui.move_history), 1)
                    request.assert_not_called()
        finally:
            root.destroy()
