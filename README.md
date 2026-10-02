# Simple Chess

A Tkinter chess game with configurable OpenAI, Claude, or human players. No extra Python packages are needed.

## Setup

1. Copy `.env.example` to `.env` and replace the placeholders with your API keys. The file is ignored by Git. Environment variables take precedence over `.env`.
2. Edit `ai_config.json` to choose each side's `provider` (`openai`, `anthropic`, or `human`) and `model`. Use a model available to your API account; the example names can be changed. For a human side use `{"provider": "human"}`.
3. Double-click `start.bat`, or run `py -3 simple_chess.py --config ai_config.json` on Windows (`python simple_chess.py --config ai_config.json` elsewhere).
4. Click **Request AI Move** to request one move for the current side. After applying that move, the game waits for your next click. If a side is human, click board squares on that side's turn.

The request button is disabled while the AI is thinking, on a human turn, and when the game is over. Reset and Load State discard pending results. A request already sent can still finish and incur charges. After an API error, fix the issue and click **Request AI Move** to retry. Restart the app after changing configuration or credentials.

Each requested AI move uses a paid API request. `attempts` limits retries for invalid responses; `timeout_seconds`, `max_output_tokens`, and `max_plies` bound requests and play. The legacy `move_delay_ms` setting is unused in manual request mode. The move limit counts AI moves and resets on Reset or Load State. The engine detects checkmate and stalemate, but does not implement repetition, fifty-move, or insufficient-material draws.

Run `python simple_chess.py` for manual play without AI configuration.

## State exchange

The AI receives its colour, current board state, last move, and legal moves. It returns one line describing the position **after** its move in the same format:

```text
<board> <next-turn> <castling> <en-passant>;<last-move>
```

Starting state sent to White:

```text
rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq -;-
```

Example response after `e2e4`:

```text
rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3;e2e4
```

The app extracts the move, validates it through `ChessGame.move`, and compares the whole resulting state against the AI response. Only the verified move is applied. Invalid responses receive limited retries, then pause play.

API references: [OpenAI Responses](https://developers.openai.com/api/docs/quickstart) and [Claude Messages](https://platform.claude.com/docs/en/api/messages/create).

## Tests

```powershell
python simple_chess.py --test
python -m unittest discover -s tests -v
```

API tests use mocked responses and do not spend credits.
