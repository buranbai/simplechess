import tkinter as tk
from tkinter import messagebox, simpledialog

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
    return FILES[col] + str(8 - row)


def parse_square(name):
    if len(name) != 2 or name[0] not in FILES or name[1] not in RANKS:
        raise ValueError(f"Invalid square: {name}")
    return 8 - int(name[1]), FILES.index(name[0])


def piece_color(piece):
    if piece is None:
        return None
    return "w" if piece.isupper() else "b"


def other(color):
    return "b" if color == "w" else "w"


class ChessGame:
    def __init__(self, state=START_STATE):
        self.load(state)

    # ------------------------------------------------------------------
    # Serialization
    # ------------------------------------------------------------------

    def load(self, state):
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
        wanted = "K" if color == "w" else "k"
        for r in range(8):
            for c in range(8):
                if self.board[r][c] == wanted:
                    return r, c
        raise ValueError("King missing")

    def is_square_attacked(self, row, col, by_color):
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
        moves = self.legal_moves()
        if moves:
            return "check" if self.in_check(self.turn) else "playing"
        return "checkmate" if self.in_check(self.turn) else "stalemate"

    # ------------------------------------------------------------------
    # Internal snapshots used by validation
    # ------------------------------------------------------------------

    def _snapshot(self):
        return (
            [row[:] for row in self.board],
            self.turn,
            self.castling,
            self.en_passant,
            self.last_move,
        )

    def _restore(self, snapshot):
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

    def __init__(self, root):
        self.root = root
        self.root.title("Simple Chess")

        self.game = ChessGame(START_STATE)
        self.state_string = self.game.save()
        self.selected = None
        self.legal_targets = set()

        self.board_frame = tk.Frame(root)
        self.board_frame.pack(padx=10, pady=10)

        self.buttons = []
        for r in range(8):
            row = []
            for c in range(8):
                button = tk.Button(
                    self.board_frame,
                    width=4,
                    height=2,
                    font=("Segoe UI Symbol", 24),
                    command=lambda r=r, c=c: self.on_square(r, c),
                    relief=tk.FLAT,
                )
                button.grid(row=r, column=c, sticky="nsew")
                row.append(button)
            self.buttons.append(row)

        self.status_label = tk.Label(root, anchor="w", font=("Segoe UI", 11))
        self.status_label.pack(fill="x", padx=10)

        tk.Label(root, text="Serialized state:").pack(anchor="w", padx=10, pady=(8, 0))
        self.state_var = tk.StringVar(value=self.state_string)
        self.state_entry = tk.Entry(root, textvariable=self.state_var, width=80)
        self.state_entry.pack(fill="x", padx=10, pady=(0, 8))

        controls = tk.Frame(root)
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

        self.refresh()

    def on_square(self, row, col):
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
            # This is the only persisted game data.
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
        text = self.state_var.get().strip()
        try:
            self.game = ChessGame(text)
            self.state_string = self.game.save()
            self.state_var.set(self.state_string)
            self.selected = None
            self.legal_targets.clear()
            self.refresh()
        except ValueError as exc:
            messagebox.showerror("Invalid state", str(exc))

    def reset(self):
        self.game = ChessGame(START_STATE)
        self.state_string = self.game.save()
        self.state_var.set(self.state_string)
        self.selected = None
        self.legal_targets.clear()
        self.refresh()

    def copy_state(self):
        self.root.clipboard_clear()
        self.root.clipboard_append(self.state_var.get())

    def refresh(self):
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


def run_tests():
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
    run_tests()
    root = tk.Tk()
    ChessUI(root)
    root.mainloop()
