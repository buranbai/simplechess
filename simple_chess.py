import tkinter as tk
from tkinter import messagebox, simpledialog, filedialog
from tkinter.scrolledtext import ScrolledText
from tkinter import ttk
import argparse
import csv
import io
import json
import re
import queue
import threading
import time
from pathlib import Path
from ai_players import choose_move, load_config

# ---------------------------------------------------------------------------
# Compact game-state format
# ---------------------------------------------------------------------------
#
#   <board> <turn> <castling> <en-passant>;<last-move>
#
# Example starting position:
#   rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -;-
#
# board       = FEN piece placement
# turn        = w or b
# castling    = KQkq subset, or -
# en-passant  = target square, or -
# last-move   = UCI-like move, e.g. e2e4, e7e8q, or -
#
# Castling rights have to be stored because board + last move alone cannot
# tell whether a king or rook moved earlier and later returned to its square.
# ---------------------------------------------------------------------------

START_STATE = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -;-"

FILES = "abcdefgh"
RANKS = "12345678"

UNICODE_PIECES = {
    "K": "♔", "Q": "♕", "R": "♖", "B": "♗", "N": "♘", "P": "♙",
    "k": "♚", "q": "♛", "r": "♜", "b": "♝", "n": "♞", "p": "♟",
}


def square_name(row, col):
    """Convert zero-based board coordinates to a square name such as e4."""
    return FILES[col] + str(8 - row)


def parse_square(name):
    """Validate a square name and convert it to zero-based row and column."""
    if len(name) != 2 or name[0] not in FILES or name[1] not in RANKS:
        raise ValueError(f"Invalid square: {name}")
    return 8 - int(name[1]), FILES.index(name[0])


def piece_color(piece):
    """Return w or b from a piece's letter case, or None for an empty square."""
    if piece is None:
        return None
    return "w" if piece.isupper() else "b"


def other(color):
    """Return the opposing player's colour."""
    return "b" if color == "w" else "w"


def moves_csv(history):
    """Format numbered White/Black move history as a CSV readable by spreadsheet apps."""
    output = io.StringIO(newline='')
    writer = csv.writer(output)
    writer.writerow(['Move', 'White', 'Black'])
    writer.writerows(history)
    return output.getvalue()


def read_saved_game(text):
    """Read a JSON game with optional move history, or a plain serialized board state."""
    text = text.lstrip('\ufeff').strip()
    if not text.startswith('{'):
        return ChessGame(text), []
    data = json.loads(text)
    if not isinstance(data.get('state'), str):
        raise ValueError('Saved game must contain a board state string')
    game = ChessGame(data['state'])
    history = data.get('moves', [])
    if not isinstance(history, list):
        raise ValueError('Move history must be a list')
    for number, row in enumerate(history, 1):
        if (not isinstance(row, list) or len(row) != 3 or type(row[0]) is not int
                or row[0] != number):
            raise ValueError('History rows must contain a move number, White move, and Black move')
        for move in row[1:]:
            if not isinstance(move, str) or (move and not re.fullmatch(r'[a-h][1-8][a-h][1-8][qrbn]?', move)):
                raise ValueError('History contains an invalid UCI move')
        if (not any(row[1:]) or (number > 1 and not row[1])
                or (number < len(history) and not row[2])):
            raise ValueError('History contains missing moves')
    if history:
        last = history[-1]
        if game.last_move != (last[2] or last[1]) or game.turn != ('w' if last[2] else 'b'):
            raise ValueError('History last move does not match the board state')
    return game, history


class ChessGame:
    def __init__(self, state=START_STATE):
        """Create a game from the starting position or a supplied state string."""
        self.load(state)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def load(self, state):
        """Parse and validate the serialized board, turn, rights, and last move."""
        try:
            position, self.last_move = state.strip().split(";", 1)
            board_text, self.turn, castling, ep = position.split()

            rows = board_text.split("/")
            if len(rows) != 8:
                raise ValueError("Board must have 8 ranks")

            board = []
            valid_pieces = set("prnbqkPRNBQK")
            for encoded in rows:
                row = []
                for ch in encoded:
                    if ch.isdigit():
                        row.extend([None] * int(ch))
                    elif ch in valid_pieces:
                        row.append(ch)
                    else:
                        raise ValueError(f"Invalid board character: {ch}")
                if len(row) != 8:
                    raise ValueError("Each rank must contain 8 squares")
                board.append(row)

            if self.turn not in ("w", "b"):
                raise ValueError("Turn must be w or b")

            self.castling = "" if castling == "-" else castling
            if any(ch not in "KQkq" for ch in self.castling):
                raise ValueError("Invalid castling rights")

            self.en_passant = None if ep == "-" else parse_square(ep)
            self.board = board

            # Basic sanity check.
            if sum(piece == "K" for row in board for piece in row) != 1:
                raise ValueError("Position must contain exactly one white king")
            if sum(piece == "k" for row in board for piece in row) != 1:
                raise ValueError("Position must contain exactly one black king")

        except Exception as exc:
            raise ValueError(f"Invalid state string: {exc}") from exc

    def save(self):
        """Serialize the current position and last move into the compact state format."""
        ranks = []
        for row in self.board:
            encoded = ""
            empty = 0
            for piece in row:
                if piece is None:
                    empty += 1
                else:
                    if empty:
                        encoded += str(empty)
                        empty = 0
                    encoded += piece
            if empty:
                encoded += str(empty)
            ranks.append(encoded)

        board_text = "/".join(ranks)
        castling = self.castling or "-"
        ep = square_name(*self.en_passant) if self.en_passant else "-"
        return f"{board_text} {self.turn} {castling} {ep};{self.last_move or '-'}"

    # ------------------------------------------------------------------
    # Attack / check detection
    # ------------------------------------------------------------------

    def find_king(self, color):
        """Find the given colour's king, raising an error if it is missing."""
        wanted = "K" if color == "w" else "k"
        for r in range(8):
            for c in range(8):
                if self.board[r][c] == wanted:
                    return r, c
        raise ValueError("King missing")

    def is_square_attacked(self, row, col, by_color):
        """Check whether any piece of the given colour attacks this square."""
        # Pawns
        pawn = "P" if by_color == "w" else "p"
        pawn_source_row = row + 1 if by_color == "w" else row - 1
        for dc in (-1, 1):
            c = col + dc
            if 0 <= pawn_source_row < 8 and 0 <= c < 8:
                if self.board[pawn_source_row][c] == pawn:
                    return True

        # Knights
        knight = "N" if by_color == "w" else "n"
        for dr, dc in (
            (-2, -1), (-2, 1), (-1, -2), (-1, 2),
            (1, -2), (1, 2), (2, -1), (2, 1),
        ):
            r, c = row + dr, col + dc
            if 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == knight:
                return True

        # Kings
        king = "K" if by_color == "w" else "k"
        for dr in (-1, 0, 1):
            for dc in (-1, 0, 1):
                if dr == 0 and dc == 0:
                    continue
                r, c = row + dr, col + dc
                if 0 <= r < 8 and 0 <= c < 8 and self.board[r][c] == king:
                    return True

        # Sliding pieces
        rook = "R" if by_color == "w" else "r"
        bishop = "B" if by_color == "w" else "b"
        queen = "Q" if by_color == "w" else "q"

        for dr, dc, attackers in (
            (-1, 0, (rook, queen)),
            (1, 0, (rook, queen)),
            (0, -1, (rook, queen)),
            (0, 1, (rook, queen)),
            (-1, -1, (bishop, queen)),
            (-1, 1, (bishop, queen)),
            (1, -1, (bishop, queen)),
            (1, 1, (bishop, queen)),
        ):
            r, c = row + dr, col + dc
            while 0 <= r < 8 and 0 <= c < 8:
                piece = self.board[r][c]
                if piece is not None:
                    if piece in attackers:
                        return True
                    break
                r += dr
                c += dc

        return False

    def in_check(self, color):
        """Check whether the given colour's king is under attack."""
        kr, kc = self.find_king(color)
        return self.is_square_attacked(kr, kc, other(color))

    # ------------------------------------------------------------------
    # Move validation
    # ------------------------------------------------------------------

    def validate_move(self, src, dst, promotion=None):
        """
        Validate one move.

        src / dst can be "e2" / "e4".
        promotion can be q, r, b, or n.

        Returns:
            (True, "") on success
            (False, reason) on failure
        """
        try:
            sr, sc = parse_square(src)
            dr, dc = parse_square(dst)
        except ValueError as exc:
            return False, str(exc)

        if (sr, sc) == (dr, dc):
            return False, "Source and destination are the same square"

        piece = self.board[sr][sc]
        if piece is None:
            return False, "No piece on source square"

        color = piece_color(piece)
        if color != self.turn:
            return False, "That piece does not belong to the side to move"

        target = self.board[dr][dc]
        if target is not None and piece_color(target) == color:
            return False, "Cannot capture your own piece"

        # Kings are never captured in legal chess; check/checkmate handles them.
        if target is not None and target.lower() == "k":
            return False, "The king cannot be captured"

        pseudo_ok, reason = self._validate_piece_move(
            sr, sc, dr, dc, promotion, check_castling_attacks=True
        )
        if not pseudo_ok:
            return False, reason

        # Simulate and reject moves leaving own king in check.
        snapshot = self._snapshot()
        self._apply_unchecked(sr, sc, dr, dc, promotion)
        illegal = self.in_check(color)
        self._restore(snapshot)

        if illegal:
            return False, "Move would leave your king in check"

        return True, ""

    def _validate_piece_move(
        self, sr, sc, dr, dc, promotion=None, check_castling_attacks=True
    ):
        """Check piece movement rules, promotion, en passant, and castling conditions."""
        piece = self.board[sr][sc]
        color = piece_color(piece)
        target = self.board[dr][dc]
        p = piece.lower()

        drow = dr - sr
        dcol = dc - sc

        if p == "p":
            direction = -1 if color == "w" else 1
            start_row = 6 if color == "w" else 1
            promotion_row = 0 if color == "w" else 7

            # Straight one square.
            if dcol == 0 and drow == direction and target is None:
                pass

            # Straight two squares from starting rank.
            elif (
                dcol == 0
                and drow == 2 * direction
                and sr == start_row
                and target is None
                and self.board[sr + direction][sc] is None
            ):
                pass

            # Normal capture.
            elif (
                abs(dcol) == 1
                and drow == direction
                and target is not None
                and piece_color(target) == other(color)
            ):
                pass

            # En passant.
            elif (
                abs(dcol) == 1
                and drow == direction
                and target is None
                and self.en_passant == (dr, dc)
            ):
                captured = self.board[sr][dc]
                expected = "p" if color == "w" else "P"
                if captured != expected:
                    return False, "Invalid en passant capture"
            else:
                return False, "Illegal pawn move"

            if dr == promotion_row:
                if promotion is None:
                    return False, "Promotion piece required: q, r, b, or n"
                if promotion.lower() not in "qrbn":
                    return False, "Invalid promotion piece"
            elif promotion is not None:
                return False, "Promotion is only allowed on the last rank"

            return True, ""

        if promotion is not None:
            return False, "Only pawns can promote"

        if p == "n":
            if (abs(drow), abs(dcol)) not in ((1, 2), (2, 1)):
                return False, "Illegal knight move"
            return True, ""

        if p == "b":
            if abs(drow) != abs(dcol):
                return False, "Illegal bishop move"
            if not self._path_clear(sr, sc, dr, dc):
                return False, "Bishop path is blocked"
            return True, ""

        if p == "r":
            if not (drow == 0 or dcol == 0):
                return False, "Illegal rook move"
            if not self._path_clear(sr, sc, dr, dc):
                return False, "Rook path is blocked"
            return True, ""

        if p == "q":
            straight = drow == 0 or dcol == 0
            diagonal = abs(drow) == abs(dcol)
            if not (straight or diagonal):
                return False, "Illegal queen move"
            if not self._path_clear(sr, sc, dr, dc):
                return False, "Queen path is blocked"
            return True, ""

        if p == "k":
            if max(abs(drow), abs(dcol)) == 1:
                return True, ""

            # Castling.
            if drow == 0 and abs(dcol) == 2:
                home_row = 7 if color == "w" else 0
                if (sr, sc) != (home_row, 4):
                    return False, "King is not on its castling square"

                kingside = dcol == 2
                right = (
                    "K" if color == "w" and kingside else
                    "Q" if color == "w" else
                    "k" if kingside else "q"
                )
                if right not in self.castling:
                    return False, "Castling right is no longer available"

                rook_col = 7 if kingside else 0
                rook = "R" if color == "w" else "r"
                if self.board[home_row][rook_col] != rook:
                    return False, "Castling rook is missing"

                between = (5, 6) if kingside else (1, 2, 3)
                if any(self.board[home_row][c] is not None for c in between):
                    return False, "Castling path is blocked"

                if check_castling_attacks:
                    enemy = other(color)
                    through = (4, 5, 6) if kingside else (4, 3, 2)
                    if any(
                        self.is_square_attacked(home_row, c, enemy)
                        for c in through
                    ):
                        return False, "Cannot castle out of, through, or into check"

                return True, ""

            return False, "Illegal king move"

        return False, "Unknown piece"

    def _path_clear(self, sr, sc, dr, dc):
        """Check that all squares between a sliding piece's source and destination are empty."""
        step_r = 0 if dr == sr else (1 if dr > sr else -1)
        step_c = 0 if dc == sc else (1 if dc > sc else -1)

        r, c = sr + step_r, sc + step_c
        while (r, c) != (dr, dc):
            if self.board[r][c] is not None:
                return False
            r += step_r
            c += step_c
        return True

    # ------------------------------------------------------------------
    # Move execution
    # ------------------------------------------------------------------

    def move(self, src, dst, promotion=None):
        """Apply a legal move, record it, and switch turns; otherwise return the reason."""
        ok, reason = self.validate_move(src, dst, promotion)
        if not ok:
            return False, reason

        sr, sc = parse_square(src)
        dr, dc = parse_square(dst)
        self._apply_unchecked(sr, sc, dr, dc, promotion)

        suffix = promotion.lower() if promotion else ""
        self.last_move = f"{src}{dst}{suffix}"
        self.turn = other(self.turn)

        return True, ""

    def _apply_unchecked(self, sr, sc, dr, dc, promotion):
        """Update pieces and special-move state without validation or switching turns."""
        piece = self.board[sr][sc]
        color = piece_color(piece)
        target = self.board[dr][dc]

        # En passant capture.
        if (
            piece.lower() == "p"
            and sc != dc
            and target is None
            and self.en_passant == (dr, dc)
        ):
            self.board[sr][dc] = None

        # Castling rook move.
        if piece.lower() == "k" and abs(dc - sc) == 2:
            if dc > sc:  # kingside
                rook_from, rook_to = 7, 5
            else:        # queenside
                rook_from, rook_to = 0, 3
            self.board[sr][rook_to] = self.board[sr][rook_from]
            self.board[sr][rook_from] = None

        # Update castling rights before moving pieces.
        self._update_castling_rights(piece, sr, sc, target, dr, dc)

        # Move the piece.
        self.board[dr][dc] = piece
        self.board[sr][sc] = None

        # Promotion.
        if piece.lower() == "p" and dr in (0, 7):
            promoted = promotion.lower()
            self.board[dr][dc] = promoted.upper() if color == "w" else promoted

        # New en-passant target only after a two-square pawn move.
        self.en_passant = None
        if piece.lower() == "p" and abs(dr - sr) == 2:
            self.en_passant = ((sr + dr) // 2, sc)

    def _update_castling_rights(self, piece, sr, sc, captured, dr, dc):
        """Remove castling rights when a king or home rook moves, or a home rook is captured."""
        rights = set(self.castling)

        if piece == "K":
            rights.discard("K")
            rights.discard("Q")
        elif piece == "k":
            rights.discard("k")
            rights.discard("q")
        elif piece == "R":
            if (sr, sc) == (7, 0):
                rights.discard("Q")
            elif (sr, sc) == (7, 7):
                rights.discard("K")
        elif piece == "r":
            if (sr, sc) == (0, 0):
                rights.discard("q")
            elif (sr, sc) == (0, 7):
                rights.discard("k")

        # Capturing an unmoved rook also removes that castling right.
        if captured == "R":
            if (dr, dc) == (7, 0):
                rights.discard("Q")
            elif (dr, dc) == (7, 7):
                rights.discard("K")
        elif captured == "r":
            if (dr, dc) == (0, 0):
                rights.discard("q")
            elif (dr, dc) == (0, 7):
                rights.discard("k")

        self.castling = "".join(ch for ch in "KQkq" if ch in rights)

    # ------------------------------------------------------------------
    # Legal move enumeration / game status
    # ------------------------------------------------------------------

    def legal_moves(self, color=None):
        """List legal UCI moves for the chosen colour while preserving the game state."""
        color = color or self.turn
        if color != self.turn:
            snapshot = self._snapshot()
            self.turn = color
        else:
            snapshot = None

        moves = []
        try:
            for sr in range(8):
                for sc in range(8):
                    piece = self.board[sr][sc]
                    if piece is None or piece_color(piece) != color:
                        continue

                    src = square_name(sr, sc)
                    for dr in range(8):
                        for dc in range(8):
                            dst = square_name(dr, dc)

                            promotions = [None]
                            if piece.lower() == "p" and dr in (0, 7):
                                promotions = ["q", "r", "b", "n"]

                            for promotion in promotions:
                                ok, _ = self.validate_move(src, dst, promotion)
                                if ok:
                                    suffix = promotion or ""
                                    moves.append(src + dst + suffix)
        finally:
            if snapshot is not None:
                self._restore(snapshot)

        return moves

    def status(self):
        """Return playing, check, checkmate, or stalemate for the side to move."""
        moves = self.legal_moves()
        if moves:
            return "check" if self.in_check(self.turn) else "playing"
        return "checkmate" if self.in_check(self.turn) else "stalemate"

    # ------------------------------------------------------------------
    # Internal snapshots used by validation
    # ------------------------------------------------------------------

    def _snapshot(self):
        """Copy the current game state so temporary move simulations can be undone."""
        return (
            [row[:] for row in self.board],
            self.turn,
            self.castling,
            self.en_passant,
            self.last_move,
        )

    def _restore(self, snapshot):
        """Restore the board and move metadata from a saved snapshot."""
        (
            self.board,
            self.turn,
            self.castling,
            self.en_passant,
            self.last_move,
        ) = snapshot


class ChessUI:
    LIGHT = "#f0d9b5"
    DARK = "#b58863"
    SELECTED = "#f6f669"
    LEGAL = "#a9cf54"

    def __init__(self, root, config=None):
        """Build the chess window and optionally enable configured AI players."""
        self.root = root
        self.root.title("Simple Chess")

        self.game = ChessGame(START_STATE)
        self.state_string = self.game.save()
        self.selected = None
        self.legal_targets = set()
        self.ai_config = config
        self.ai_running = False
        self.auto_mode = False
        self.next_auto_move_at = 0
        self.ai_busy = False
        self.ai_generation = 0
        self.ai_plies = 0
        self.ai_results = queue.Queue()
        self.ai_events = queue.Queue()
        self.move_history = []

        layout = tk.Frame(root)
        layout.pack(fill=tk.BOTH, expand=True)
        game_panel = tk.Frame(layout)
        game_panel.pack(side=tk.LEFT, anchor='n')
        exchange_panel = tk.Frame(layout)
        exchange_panel.pack(side=tk.RIGHT, fill=tk.BOTH, expand=True, padx=10, pady=10)
        self.exchange_label = tk.Label(exchange_panel, text='AI exchange — no request yet', anchor='w',
                                       font=('Segoe UI', 11, 'bold'))
        self.exchange_label.pack(fill=tk.X, pady=(0, 8))
        self.sent_text = self.create_exchange_box(exchange_panel, 'Sent to AI')
        self.received_text = self.create_exchange_box(exchange_panel, 'AI answer')
        history_frame = tk.LabelFrame(exchange_panel, text='Move history', font=('Segoe UI', 11, 'bold'))
        history_frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        self.history_table = ttk.Treeview(history_frame, columns=('number', 'white', 'black'),
                                          show='headings', height=8)
        for column, title, width in (('number', 'Move', 55), ('white', 'White', 150), ('black', 'Black', 150)):
            self.history_table.heading(column, text=title)
            self.history_table.column(column, width=width, anchor=tk.CENTER)
        history_scroll = ttk.Scrollbar(history_frame, orient=tk.VERTICAL, command=self.history_table.yview)
        history_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.history_table.configure(yscrollcommand=history_scroll.set)
        self.history_table.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)

        self.board_frame = tk.Frame(game_panel)
        self.board_frame.pack(padx=10, pady=10)

        # Coordinates surround the board, with White's home rank at the bottom.
        coordinate_style = {"font": ("Segoe UI", 11, "bold"), "fg": "#555555"}
        for index in range(8):
            for edge_row in (0, 9):
                tk.Label(self.board_frame, text=FILES[index], **coordinate_style).grid(
                    row=edge_row, column=index + 1, pady=4
                )
            for edge_col in (0, 9):
                tk.Label(self.board_frame, text=str(8 - index), **coordinate_style).grid(
                    row=index + 1, column=edge_col, padx=6
                )

        self.buttons = []
        for r in range(8):
            row = []
            for c in range(8):
                # A fixed pixel-sized frame keeps each tile square regardless of font metrics.
                tile = tk.Frame(self.board_frame, width=80, height=80)
                tile.grid(row=r + 1, column=c + 1)
                tile.pack_propagate(False)
                button = tk.Button(
                    tile,
                    font=("Segoe UI Symbol", 24),
                    command=lambda r=r, c=c: self.on_square(r, c),
                    relief=tk.FLAT,
                    borderwidth=0,
                    highlightthickness=0,
                )
                button.pack(fill=tk.BOTH, expand=True)
                row.append(button)
            self.buttons.append(row)

        self.status_label = tk.Label(game_panel, anchor="w", font=("Segoe UI", 11))
        self.status_label.pack(fill="x", padx=10)

        tk.Label(game_panel, text="Serialized state:").pack(anchor="w", padx=10, pady=(8, 0))
        self.state_var = tk.StringVar(value=self.state_string)
        self.state_entry = tk.Entry(game_panel, textvariable=self.state_var, width=80)
        self.state_entry.pack(fill="x", padx=10, pady=(0, 8))

        controls = tk.Frame(game_panel)
        controls.pack(pady=(0, 10))

        tk.Button(controls, text="Load State", command=self.load_state).pack(
            side=tk.LEFT, padx=4
        )
        tk.Button(controls, text="Reset", command=self.reset).pack(
            side=tk.LEFT, padx=4
        )
        tk.Button(controls, text="Copy State", command=self.copy_state).pack(
            side=tk.LEFT, padx=4
        )
        file_controls = tk.Frame(game_panel)
        file_controls.pack(pady=(0, 10))
        for label, command in (('Save Game', self.save_game), ('Load Game', self.load_game),
                               ('Export Moves', self.export_moves)):
            tk.Button(file_controls, text=label, command=command).pack(side=tk.LEFT, padx=4)

        if config:
            self.ai_button = tk.Button(controls, text='Request AI Move', command=self.request_ai_move)
            self.ai_button.pack(side=tk.LEFT, padx=4)
            self.auto_button = tk.Button(controls, text='Start Auto Mode', command=self.toggle_auto_mode)
            self.auto_button.pack(side=tk.LEFT, padx=4)
            players = ' | '.join(f'{side.title()}: {config[side]["provider"]}' for side in ('white', 'black'))
            tk.Label(game_panel, text=players).pack(pady=(0, 5))
            self.root.after(100, self.poll_ai)
        self.refresh()

    def create_exchange_box(self, parent, title):
        """Create a scrollable, selectable, read-only text area for AI exchange details."""
        frame = tk.LabelFrame(parent, text=title, font=('Segoe UI', 11, 'bold'))
        frame.pack(fill=tk.BOTH, expand=True, pady=(0, 8))
        text = ScrolledText(frame, width=52, height=12, wrap=tk.WORD,
                            font=('Consolas', 10), state=tk.DISABLED)
        text.pack(fill=tk.BOTH, expand=True, padx=6, pady=6)
        return text

    def update_exchange_text(self, widget, text, append=False):
        """Replace or append exchange text while keeping it read-only for the user."""
        widget.configure(state=tk.NORMAL)
        if not append:
            widget.delete('1.0', tk.END)
        widget.insert(tk.END, text)
        widget.configure(state=tk.DISABLED)
        widget.see(tk.END)

    def record_move(self):
        """Record the last successful move in numbered White/Black columns and scroll to it."""
        color = other(self.game.turn)
        move = self.game.last_move
        if color == 'w' or not self.move_history or self.move_history[-1][2]:
            self.move_history.append([len(self.move_history) + 1, '', ''])
            self.history_table.insert('', tk.END, iid=str(len(self.move_history)),
                                      values=self.move_history[-1])
        self.move_history[-1][1 if color == 'w' else 2] = move
        item = str(len(self.move_history))
        self.history_table.item(item, values=self.move_history[-1])
        self.history_table.see(item)

    def clear_move_history(self):
        """Clear recorded moves when a new game or loaded position starts."""
        self.move_history.clear()
        for item in self.history_table.get_children():
            self.history_table.delete(item)

    def save_game(self):
        """Save the current board and history as JSON and export a companion moves CSV."""
        name = filedialog.asksaveasfilename(parent=self.root, title='Save Game',
                                           defaultextension='.json', filetypes=[('Saved game', '*.json')])
        if not name:
            return
        path = Path(name)
        try:
            data = {'state': self.game.save(), 'moves': self.move_history}
            path.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8')
            csv_path = path.with_name(path.stem + '.moves.csv')
            csv_path.write_text(moves_csv(self.move_history), encoding='utf-8')
            messagebox.showinfo('Game saved', f'Game: {path}\nMoves: {csv_path}', parent=self.root)
        except OSError as exc:
            messagebox.showerror('Save failed', str(exc), parent=self.root)

    def export_moves(self):
        """Export the current numbered move history to a user-selected CSV file."""
        name = filedialog.asksaveasfilename(parent=self.root, title='Export Moves',
                                           defaultextension='.csv', filetypes=[('Move history', '*.csv')])
        if not name:
            return
        try:
            Path(name).write_text(moves_csv(self.move_history), encoding='utf-8')
        except OSError as exc:
            messagebox.showerror('Export failed', str(exc), parent=self.root)

    def load_game(self):
        """Load a saved board with optional history, pausing AI and replacing the current game."""
        name = filedialog.askopenfilename(parent=self.root, title='Load Game',
                                         filetypes=[('Game or board state', '*.json *.txt'), ('All files', '*.*')])
        if not name:
            return
        try:
            game, history = read_saved_game(Path(name).read_text(encoding='utf-8-sig'))
        except (OSError, ValueError) as exc:
            messagebox.showerror('Load failed', str(exc), parent=self.root)
            return
        self.stop_ai()
        self.game = game
        self.clear_move_history()
        self.move_history = history
        for row in history:
            self.history_table.insert('', tk.END, iid=str(row[0]), values=row)
        if history:
            self.history_table.see(str(history[-1][0]))
        self.ai_plies = 0
        self.state_string = game.save()
        self.state_var.set(self.state_string)
        self.selected = None
        self.legal_targets.clear()
        self.refresh()

    def on_square(self, row, col):
        """Handle human piece selection, destination clicks, promotion, and move results."""
        if self.ai_config and self.current_player().get('provider', 'human') != 'human':
            return
        piece = self.game.board[row][col]

        if self.selected is None:
            if piece is None or piece_color(piece) != self.game.turn:
                return

            self.selected = (row, col)
            self.legal_targets = self._legal_targets_for(row, col)
            self.refresh()
            return

        sr, sc = self.selected

        # Clicking another own piece changes the selection.
        if piece is not None and piece_color(piece) == self.game.turn:
            self.selected = (row, col)
            self.legal_targets = self._legal_targets_for(row, col)
            self.refresh()
            return

        src = square_name(sr, sc)
        dst = square_name(row, col)
        moving_piece = self.game.board[sr][sc]

        promotion = None
        if moving_piece and moving_piece.lower() == "p" and row in (0, 7):
            promotion = self.ask_promotion()
            if promotion is None:
                return

        ok, reason = self.game.move(src, dst, promotion)
        if not ok:
            messagebox.showerror("Illegal move", reason)
        else:
            self.record_move()
            # Keep the compact board state synchronized with the displayed game.
            self.state_string = self.game.save()
            self.state_var.set(self.state_string)

        self.selected = None
        self.legal_targets.clear()
        self.refresh()

        status = self.game.status()
        if status == "checkmate":
            winner = "Black" if self.game.turn == "w" else "White"
            messagebox.showinfo("Checkmate", f"{winner} wins.")
        elif status == "stalemate":
            messagebox.showinfo("Stalemate", "The game is a draw.")

    def _legal_targets_for(self, row, col):
        """Find legal destination squares for the selected piece to highlight on the board."""
        src = square_name(row, col)
        piece = self.game.board[row][col]
        targets = set()

        for dr in range(8):
            for dc in range(8):
                dst = square_name(dr, dc)

                if piece.lower() == "p" and dr in (0, 7):
                    valid = any(
                        self.game.validate_move(src, dst, promo)[0]
                        for promo in "qrbn"
                    )
                else:
                    valid = self.game.validate_move(src, dst)[0]

                if valid:
                    targets.add((dr, dc))

        return targets

    def ask_promotion(self):
        """Ask the human player for a promotion piece, or return None if cancelled."""
        while True:
            value = simpledialog.askstring(
                "Promotion",
                "Promote to Q, R, B, or N:",
                parent=self.root,
            )
            if value is None:
                return None
            value = value.strip().lower()
            if value in ("q", "r", "b", "n"):
                return value
            messagebox.showerror("Invalid promotion", "Choose Q, R, B, or N.")

    def load_state(self):
        """Load the entered position and pause AI play, reporting invalid states."""
        text = self.state_var.get().strip()
        try:
            game = ChessGame(text)
            self.stop_ai()
            self.game = game
            self.clear_move_history()
            self.ai_plies = 0
            self.state_string = self.game.save()
            self.state_var.set(self.state_string)
            self.selected = None
            self.legal_targets.clear()
            self.refresh()
        except ValueError as exc:
            messagebox.showerror("Invalid state", str(exc))

    def reset(self):
        """Pause AI play and restore the starting board and AI move counter."""
        self.stop_ai()
        self.ai_plies = 0
        self.game = ChessGame(START_STATE)
        self.clear_move_history()
        self.state_string = self.game.save()
        self.state_var.set(self.state_string)
        self.selected = None
        self.legal_targets.clear()
        self.refresh()

    def copy_state(self):
        """Copy the state entry's text to the system clipboard."""
        self.root.clipboard_clear()
        self.root.clipboard_append(self.state_var.get())

    def current_player(self):
        """Return the configured player for the side whose turn it is."""
        return self.ai_config['white' if self.game.turn == 'w' else 'black']

    def stop_ai(self):
        """Stop automatic play and invalidate pending turns without cancelling sent requests."""
        self.ai_running = False
        self.auto_mode = False
        self.ai_generation += 1
        if self.ai_config:
            self.ai_button.configure(text='Request AI Move')
        if hasattr(self, 'auto_button'):
            self.auto_button.configure(text='Start Auto Mode')

    def toggle_auto_mode(self):
        """Start automatic AI turns or stop immediately and discard any pending move."""
        if self.auto_mode:
            self.stop_ai()
        elif self.game.status() not in ('checkmate', 'stalemate'):
            self.auto_mode = True
            self.next_auto_move_at = 0
        self.refresh()

    def request_ai_move(self):
        """Request exactly one AI turn when the current side is AI and no request is pending."""
        if self.ai_busy or self.ai_running or self.current_player()['provider'] == 'human':
            return
        if self.game.status() in ('checkmate', 'stalemate'):
            return
        self.ai_running = True
        self.selected = None
        self.legal_targets.clear()
        self.refresh()

    def drain_ai_events(self):
        """Display queued exchange details for the current request, ignoring stale workers."""
        # Only the UI thread touches widgets; workers publish display updates through a queue.
        while not self.ai_events.empty():
            generation, kind, attempt, text = self.ai_events.get_nowait()
            if generation != self.ai_generation:
                continue
            heading = f'--- Attempt {attempt} ---\n'
            if kind == 'sent':
                self.update_exchange_text(self.sent_text, heading + text + '\n\n', append=True)
            elif kind == 'received':
                self.update_exchange_text(self.received_text, heading + text + '\n\n', append=True)
            else:
                self.update_exchange_text(self.received_text, f'{kind.title()}: {text}\n\n', append=True)

    def poll_ai(self):
        """Process background moves and request further AI turns when automatic play is enabled."""
        self.drain_ai_events()
        try:
            generation, state, move, error = self.ai_results.get_nowait()
        except queue.Empty:
            pass
        else:
            # The worker queues all exchange details before its final result.
            self.drain_ai_events()
            self.ai_busy = False
            if self.ai_running and generation == self.ai_generation and self.game.save() == state:
                if error:
                    self.stop_ai()
                    messagebox.showerror('AI paused', error)
                else:
                    ok, reason = self.game.move(move[:2], move[2:4], move[4:] or None)
                    if not ok:
                        self.stop_ai()
                        messagebox.showerror('AI paused', reason)
                    else:
                        self.record_move()
                        self.ai_plies += 1
                        self.state_string = self.game.save()
                        self.state_var.set(self.state_string)
                self.ai_running = False
                self.next_auto_move_at = time.monotonic() + self.ai_config.get('move_delay_ms', 500) / 1000
            self.refresh()
        if getattr(self, 'auto_mode', False) and not self.ai_busy and not self.ai_running:
            if self.game.status() in ('checkmate', 'stalemate'):
                self.stop_ai()
                self.refresh()
            elif time.monotonic() >= self.next_auto_move_at and self.current_player()['provider'] != 'human':
                self.request_ai_move()
        if self.ai_running and not self.ai_busy:
            if self.game.status() in ('checkmate', 'stalemate'):
                self.stop_ai()
                self.refresh()
            elif self.ai_plies >= self.ai_config['max_plies']:
                self.stop_ai()
                messagebox.showinfo('AI paused', 'AI move limit reached. Reset or load a state to start a new run.')
            elif self.current_player().get('provider', 'human') != 'human':
                state = self.game.save()
                generation = self.ai_generation
                player = self.current_player().copy()
                self.ai_busy = True
                color = 'White' if self.game.turn == 'w' else 'Black'
                self.exchange_label.configure(text=f'{color} — {player["provider"]} / {player["model"]}')
                self.update_exchange_text(self.sent_text, '')
                self.update_exchange_text(self.received_text, '')
                self.status_label.configure(text=f'{player["provider"]} is thinking…')

                def on_exchange(kind, attempt, text):
                    """Queue the exact prompt, raw answer, or validation error for the UI thread."""
                    self.ai_events.put((generation, kind, attempt, text))

                def worker():
                    """Request a validated AI move in the background and queue its result or error."""
                    try:
                        move = choose_move(ChessGame(state), player, self.ai_config, on_exchange)
                        self.ai_results.put((generation, state, move, None))
                    except Exception as exc:
                        on_exchange('error', 0, str(exc))
                        self.ai_results.put((generation, state, None, str(exc)))

                threading.Thread(target=worker, daemon=True).start()
        self.root.after(100, self.poll_ai)

    def refresh(self):
        """Redraw pieces, selection highlights, and the current game status."""
        for r in range(8):
            for c in range(8):
                piece = self.game.board[r][c]
                base = self.LIGHT if (r + c) % 2 == 0 else self.DARK

                if self.selected == (r, c):
                    color = self.SELECTED
                elif (r, c) in self.legal_targets:
                    color = self.LEGAL
                else:
                    color = base

                self.buttons[r][c].configure(
                    text=UNICODE_PIECES.get(piece, ""),
                    bg=color,
                    activebackground=color,
                )

        side = "White" if self.game.turn == "w" else "Black"
        status = self.game.status()
        if status == "check":
            text = f"{side} to move — CHECK"
        elif status == "checkmate":
            text = f"{side} is checkmated"
        elif status == "stalemate":
            text = "Stalemate"
        else:
            text = f"{side} to move"

        if self.game.last_move and self.game.last_move != "-":
            text += f" | Last move: {self.game.last_move}"

        self.status_label.configure(text=text)
        if self.ai_config:
            waiting = self.ai_busy or self.ai_running
            enabled = (not waiting and not self.auto_mode and self.current_player()['provider'] != 'human'
                       and status not in ('checkmate', 'stalemate'))
            self.ai_button.configure(text='Thinking…' if waiting else 'Request AI Move',
                                     state=tk.NORMAL if enabled else tk.DISABLED)
            self.auto_button.configure(text='Stop Auto Mode' if self.auto_mode else 'Start Auto Mode',
                                       state=tk.NORMAL if self.auto_mode or status not in ('checkmate', 'stalemate') else tk.DISABLED)


def run_tests():
    """Check engine serialization, basic moves, checkmate, and special chess moves."""
    # Basic movement.
    g = ChessGame()
    assert g.move("e2", "e4")[0]
    saved = g.save()

    # Reload from exactly the serialized string.
    g = ChessGame(saved)
    assert g.turn == "b"
    assert g.last_move == "e2e4"
    assert g.board[4][4] == "P"

    # Illegal move.
    assert not g.validate_move("e4", "e6")[0]

    # Common opening moves.
    assert g.move("e7", "e5")[0]
    assert g.move("g1", "f3")[0]
    assert g.move("b8", "c6")[0]

    # Fool's mate proves self-check/checkmate validation is active.
    g = ChessGame()
    assert g.move("f2", "f3")[0]
    assert g.move("e7", "e5")[0]
    assert g.move("g2", "g4")[0]
    assert g.move("d8", "h4")[0]
    assert g.status() == "checkmate"

    # Castling.
    g = ChessGame("r3k2r/8/8/8/8/8/8/R3K2R w KQkq -;-")
    assert g.validate_move("e1", "g1")[0]
    assert g.move("e1", "g1")[0]
    assert g.board[7][6] == "K"
    assert g.board[7][5] == "R"

    # En passant.
    g = ChessGame()
    assert g.move("e2", "e4")[0]
    assert g.move("a7", "a6")[0]
    assert g.move("e4", "e5")[0]
    assert g.move("d7", "d5")[0]
    assert g.validate_move("e5", "d6")[0]
    assert g.move("e5", "d6")[0]
    assert g.board[3][3] is None

    # Promotion.
    g = ChessGame("7k/P7/8/8/8/8/8/7K w - -;-")
    assert not g.validate_move("a7", "a8")[0]
    assert g.validate_move("a7", "a8", "q")[0]
    assert g.move("a7", "a8", "q")[0]
    assert g.board[0][0] == "Q"

    print("All chess-engine tests passed.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description='Simple Chess with optional AI players')
    parser.add_argument('--config', type=Path, help='AI player JSON configuration')
    parser.add_argument('--test', action='store_true', help='Run engine tests without a window')
    args = parser.parse_args()
    if args.test:
        run_tests()
    else:
        try:
            config = load_config(args.config.resolve()) if args.config else None
        except (ValueError, OSError) as exc:
            parser.error(str(exc))
        root = tk.Tk()
        ChessUI(root, config)
        root.mainloop()
