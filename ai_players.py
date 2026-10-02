"""AI transport and strict UCI move validation (standard library only)."""
import json
import os
import re
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def load_config(path):
    """Load local credentials and validate player settings and request limits from JSON."""
    path = Path(path).resolve()
    # Optional local secrets file; existing environment values take precedence.
    env_path = path.parent / '.env'
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8-sig').splitlines():
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                key = key.strip()
                if not os.environ.get(key):
                    os.environ[key] = value.strip().strip('"\'')
    config = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(config, dict):
        raise ValueError('Configuration must be a JSON object')
    for side in ('white', 'black'):
        player = config.get(side, {'provider': 'human'})
        if not isinstance(player, dict):
            raise ValueError(f'{side}: player configuration must be a JSON object')
        provider = player.get('provider', 'human')
        player['provider'] = provider
        if provider not in ('human', 'openai', 'anthropic'):
            raise ValueError(f'{side}: provider must be human, openai, or anthropic')
        if provider != 'human':
            if not isinstance(player.get('model'), str) or not player['model'].strip():
                raise ValueError(f'{side}: model is required')
            key_name = player.get('api_key_env', 'OPENAI_API_KEY' if provider == 'openai' else 'ANTHROPIC_API_KEY')
            if not isinstance(key_name, str) or not key_name:
                raise ValueError(f'{side}: api_key_env must be an environment variable name')
            if not os.environ.get(key_name):
                hint = 'file found, but key is missing or empty' if env_path.exists() else 'file not found'
                raise ValueError(f'{side}: set {key_name} in {env_path} ({hint}) or your environment')
        config[side] = player
    for key, default, low, high in (
        ('timeout_seconds', 90, 1, 600), ('max_output_tokens', 2048, 128, 32000),
        ('attempts', 2, 1, 5), ('move_delay_ms', 500, 0, 60000),
        ('max_plies', 300, 1, 10000),
    ):
        value = config.get(key, default)
        if type(value) is not int or not low <= value <= high:
            raise ValueError(f'{key} must be an integer between {low} and {high}')
        config[key] = value
    return config


def validated_move(game, response):
    """Accept only one legal UCI move, preserving the current board during validation."""
    move = response.strip()
    if not re.fullmatch(r'[a-h][1-8][a-h][1-8][qrbn]?', move):
        raise ValueError('Return only one UCI move, for example e2e4 or a7a8q')
    ok, reason = game.validate_move(move[:2], move[2:4], move[4:] or None)
    if not ok:
        raise ValueError(f'Illegal move: {reason}')
    return move


def request_text(player, prompt, config):
    """Send a prompt to the configured provider and extract its text response."""
    provider = player['provider']
    key_name = player.get('api_key_env', 'OPENAI_API_KEY' if provider == 'openai' else 'ANTHROPIC_API_KEY')
    key = os.environ[key_name]
    headers = {'Content-Type': 'application/json'}
    if provider == 'openai':
        url = 'https://api.openai.com/v1/responses'
        headers['Authorization'] = f'Bearer {key}'
        payload = {'model': player['model'], 'input': prompt,
                   'max_output_tokens': config['max_output_tokens'], 'store': False}
    else:
        url = 'https://api.anthropic.com/v1/messages'
        headers.update({'x-api-key': key, 'anthropic-version': '2023-06-01'})
        payload = {'model': player['model'], 'max_tokens': config['max_output_tokens'],
                   'messages': [{'role': 'user', 'content': prompt}]}
    request = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
    try:
        with urlopen(request, timeout=config['timeout_seconds']) as result:
            data = json.load(result)
    except HTTPError as exc:
        # Do not expose headers or credentials through errors.
        raise RuntimeError(f'{provider} API returned HTTP {exc.code}; check key, model, quota and rate limits') from None
    except (URLError, TimeoutError) as exc:
        raise RuntimeError(f'{provider} request failed or timed out') from None
    if provider == 'openai':
        text = ''.join(part.get('text', '') for item in data.get('output', [])
                       if item.get('type') == 'message' for part in item.get('content', [])
                       if part.get('type') == 'output_text')
    else:
        text = ''.join(part.get('text', '') for part in data.get('content', [])
                       if part.get('type') == 'text')
    if not text.strip():
        raise RuntimeError(f'{provider} returned no text; try increasing max_output_tokens')
    return text


def choose_move(game, player, config, on_exchange=None):
    """Request a legal AI move and optionally report prompts, responses, and retry errors."""
    color = 'White' if game.turn == 'w' else 'Black'
    prompt = (
        f'You are playing chess as {color}. It is your turn. Choose one strong legal move.\n'
        'Input state format: <FEN piece placement> <side to move w/b> <castling KQkq or -> '
        '<en-passant target or ->;<last move in UCI or ->.\n'
        'Uppercase pieces are White; lowercase pieces are Black. Board ranks run 8 to 1.\n'
        'Return ONLY one move from the legal moves list in UCI format, '
        'for example e2e4 or a7a8q (promotion suffix q/r/b/n). '
        'For castling use the king move, such as e1g1. '
        'Do not return the board state, markdown, explanation, or extra fields.\n'
        f'Current state: {game.save()}\nLast move: {game.last_move}\n'
        f'Legal moves: {", ".join(game.legal_moves())}'
    )
    for attempt in range(config['attempts']):
        if on_exchange:
            on_exchange('sent', attempt + 1, prompt)
        response = request_text(player, prompt, config)
        if on_exchange:
            on_exchange('received', attempt + 1, response)
        try:
            return validated_move(game, response)
        except ValueError as exc:
            if on_exchange:
                on_exchange('validation', attempt + 1, str(exc))
            if attempt + 1 == config['attempts']:
                raise RuntimeError(f'AI response rejected: {exc}') from None
            prompt += f'\nYour previous response was invalid: {exc}. Try again using the original current state.'
