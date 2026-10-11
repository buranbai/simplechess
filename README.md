# Simple Chess

A Tkinter chess game with configurable OpenAI, Claude, or human players. No extra Python packages are needed.

## Setup

The board and coordinate labels open in a separate **Simple Chess — Board** window for recording. Controls, move history, and AI messages stay in the main window. Closing the board hides it without ending the game; **Show Board** reopens it. Closing the main window closes both windows.

1. Copy `.env.example` to `.env` and replace the placeholders with your API keys. The file is ignored by Git. Environment variables take precedence over `.env`.
2. Use a model available to your API account. Model suggestions are read from `model_catalog.json`.
3. Double-click `start.bat`. Choose each side's player (`openai`, `anthropic`, `random`, or `human`), select or type its model, and click **Start Game**. Optionally check **Start in auto mode**. Choices are remembered in `match_config.json`. For OpenAI models without reasoning support, select **default** for reasoning.
4. Click **Request AI Move** to request one move for the current side. After applying that move, the game waits for your next click. If a side is human, click board squares on that side's turn.

The right panel shows the exact prompt sent to the AI at the top and its raw text answer at the bottom. Each new move replaces the previous exchange; retries and errors are shown for that request. You can select and copy the text. API keys and authentication headers are not included.

The move-history table records every successful human or AI move in numbered White/Black columns using UCI notation. Reset and Load State clear the history. A loaded state contains only its last move, so earlier moves cannot be reconstructed; the table records moves played after loading.

**Save Game** writes the current board and move history to a JSON file and also exports a companion `.moves.csv` file. **Export Moves** saves just the history as CSV. **Load Game** restores a JSON game including its moves, or loads a plain board-state text file with an empty history. JSON files containing only `{"state": "..."}` also load with an empty history. Loaded history is checked for valid move notation and agreement with the board's last move; earlier moves are not replayed. Moves played after loading are appended to the restored history.

The request button is disabled while the AI is thinking, on a human turn, and when the game is over. Reset and Load State discard pending results. A request already sent can still finish and incur charges. After an API error, fix the issue and click **Request AI Move** to retry. Restart the app after changing configuration or credentials.

Each requested AI move uses a paid API request. `attempts` limits retries for invalid responses; `timeout_seconds`, `max_output_tokens`, and `max_plies` bound requests and play. The legacy `move_delay_ms` setting is unused in manual request mode. The move limit counts AI moves and resets on Reset or Load State. The engine detects checkmate and stalemate, but does not implement repetition, fifty-move, or insufficient-material draws.

Run `python simple_chess.py` to open the same setup screen. Choose human for both sides for manual play. To skip setup, run `py -3 simple_chess.py --config ai_config.json`.

**Start Auto Mode** requests and plays successive AI moves. **Stop Auto Mode** stops further requests and discards any pending move (already sent requests may still incur charges). Automatic play waits on human turns and resumes after the human moves. Reset, Load State, Load Game, API errors, game over, and the AI move limit stop automatic play. `move_delay_ms` controls the pause between AI turns; it has no effect on manual requests.

The OpenAI player uses `"reasoning_effort": "low"` in the supplied config. This is sent as `reasoning.effort`; accepted effort levels depend on the selected model. Omit the setting for models without reasoning support. If OpenAI returns an incomplete or empty answer, the app displays its response status, actual stopping reason when provided, and output/reasoning token counts in the AI answer panel. It does not apply incomplete responses.

## Model catalogue

Saved games include the starting position, final board, complete recorded move history, and White/Black player details (provider, model, and reasoning effort). No API keys or prompt/answer transcripts are saved. After **Load Game**, the matchup is shown below the controls. Click **Replay Moves** to animate the recorded moves without API requests; click again to pause/resume. **Stop Replay** restores the saved final board. Live play is disabled during replay, and replay never duplicates history. Older saves without a starting position are replayed from the standard start when possible; board-only saves load normally with no replay history.

The setup screen's **Reasoning effort** selector works for both OpenAI and Claude. Claude effort is sent as `output_config.effort`; OpenAI uses `reasoning.effort`. **default** omits the parameter. Choose default for models without effort support (for example Claude Haiku 4.5). Sonnet 5 supports low, medium, and high effort; other levels depend on the selected model. The selected value is remembered with the player settings.

`model_catalog.json` lists all model IDs returned for your OpenAI and Anthropic API keys, with a `player_config` for each. Copy a suitable entry into `white` or `black` in `ai_config.json`; the catalogue itself is not a game configuration. Listing a model does not test endpoint compatibility or playing strength. OpenAI also lists image, audio, embedding, moderation and legacy models, which are not usable here. Choose a text model supporting the Responses API; Claude players use the Messages API. Preserve or adjust `reasoning_effort` only for models supporting it.

Refresh the account-specific catalogue with `py -3 refresh_model_catalog.py`. This reads your local keys but never writes them into the catalogue, and uses only model-list requests, not text-generation requests. The catalogue stores the time it was generated and may need refreshing as availability changes.

## AI vs random

Every human, AI, and random move is animated. Pieces slide to their destination; captured pieces shrink with a brief red burst. Castling animates both king and rook, and en passant animates the captured pawn. Auto mode waits for animations to finish before its next delay and request. Reset and loading a game cancel the current animation.

Use `start.bat` and select an AI for one side and random for the other. Only the chosen AI provider's key is required. The old `start_ai_vs_random.bat` now opens the same setup screen. You can still run `py -3 simple_chess.py --config ai_vs_random.json` to skip setup. Click **Start Auto Mode** for automatic turns, or request each move manually. **Stop Auto Mode** works for both players.

Use `{"provider": "random"}` for either side in any player configuration. Random players pick uniformly from the engine's available legal moves (including castling, en passant, and promotion choices), make no API calls, and need no key or model. Their legal-move list and selected move appear in the exchange panel, and their moves are recorded and saved like AI moves. You can replace the OpenAI side with your Claude configuration to test Claude against random moves.

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
