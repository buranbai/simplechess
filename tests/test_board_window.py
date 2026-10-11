import tkinter as tk
import unittest

from simple_chess import ChessUI


class BoardWindowTests(unittest.TestCase):
    def test_board_is_separate_from_controls(self):
        """Keep the board in its own window while controls and exchange remain in the main window."""
        root = tk.Tk()
        root.withdraw()
        try:
            ui = ChessUI(root)
            self.assertIs(ui.board_frame.master, ui.board_window)
            self.assertIsNot(ui.board_window, root)
            self.assertEqual(ui.board_window.title(), 'Simple Chess — Board')
            self.assertEqual(ui.board_window.resizable(), (0, 0))
            self.assertEqual(str(ui.sent_text.winfo_toplevel()), str(root))
            state = ui.game.save()
            ui.board_window.withdraw()
            self.assertEqual(ui.game.save(), state)
        finally:
            root.destroy()
