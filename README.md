# Simple Chess

A Tkinter chess game with configurable OpenAI, Claude, or human players. No extra Python packages are needed.

## Setup

1. Copy `.env.example` to `.env` and replace the placeholders with your API keys. The file is ignored by Git. Environment variables take precedence over `.env`.
2. Edit `ai_config.json` to choose each side's `provider` (`openai`, `anthropic`, or `human`) and `model`. Use a model available to your API account; the example names can be changed. For a human side use `{"provider": "human"}`.
3. Double-click `start.bat`, or run `py -3 simple_chess.py --config ai_config.json` on Windows (`python simple_chess.py --config ai_config.json` elsewhere).
4. Click **Request AI Move** to request one move for the current side. After applying that move, the game waits for your next click. If a side is human, click board squares on that side's turn.

The right panel shows the exact prompt sent to the AI at the top and its raw text answer at the bottom. Each new move replaces the previous exchange; retries and errors are shown for that request. You can select and copy the text. API keys and authentication headers are not included.

The move-history table records every successful human or AI move in numbered White/Black columns using UCI notation. Reset and Load State clear the history. A loaded state contains only its last move, so earlier moves cannot be reconstructed; the table records moves played after loading.

**Save Game** writes the current board and move history to a JSON file and also exports a companion `.moves.csv` file. **Export Moves** saves just the history as CSV. **Load Game** restores a JSON game including its moves, or loads a plain board-state text file with an empty history. JSON files containing only `{"state": "..."}` also load with an empty history. Loaded history is checked for valid move notation and agreement with the board's last move; earlier moves are not replayed. Moves played after loading are appended to the restored history.

The request button is disabled while the AI is thinking, on a human turn, and when the game is over. Reset and Load State discard pending results. A request already sent can still finish and incur charges. After an API error, fix the issue and click **Request AI Move** to retry. Restart the app after changing configuration or credentials.

Each requested AI move uses a paid API request. `attempts` limits retries for invalid responses; `timeout_seconds`, `max_output_tokens`, and `max_plies` bound requests and play. The legacy `move_delay_ms` setting is unused in manual request mode. The move limit counts AI moves and resets on Reset or Load State. The engine detects checkmate and stalemate, but does not implement repetition, fifty-move, or insufficient-material draws.

Run `python simple_chess.py` for manual play without AI configuration.

**Start Auto Mode** requests and plays successive AI moves. **Stop Auto Mode** stops further requests and discards any pending move (already sent requests may still incur charges). Automatic play waits on human turns and resumes after the human moves. Reset, Load State, Load Game, API errors, game over, and the AI move limit stop automatic play. `move_delay_ms` controls the pause between AI turns; it has no effect on manual requests.

The OpenAI player uses `"reasoning_effort": "low"` in the supplied config. This is sent as `reasoning.effort`; accepted effort levels depend on the selected model. Omit the setting for models without reasoning support. If OpenAI returns an incomplete or empty answer, the app displays its response status, actual stopping reason when provided, and output/reasoning token counts in the AI answer panel. It does not apply incomplete responses.

## State exchange

The AI receives its colour, current board state, last move, and legal moves. The input state uses this format:

```text
<board> <next-turn> <castling> <en-passant>;<last-move>
```

Starting state sent to White:

```text
rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -;-
```

The AI replies with only its chosen UCI move:

```text
e2e4
```

Moves use source and destination squares, with a promotion suffix when needed (`a7a8q`). Castling uses the king's move (`e1g1`). The app validates the move using the chess engine, then applies it through `ChessGame.move`. The engine updates the board, turn, castling rights, en-passant target, and last move. Invalid responses receive limited retries, then pause play.

API references: [OpenAI Responses](https://developers.openai.com/api/docs/quickstart) and [Claude Messages](https://platform.claude.com/docs/en/api/messages/create).

## Tests

```powershell
python simple_chess.py --test
python -m unittest discover -s tests -v
```

API tests use mocked responses and do not spend credits.
