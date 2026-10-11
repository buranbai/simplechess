"""Build a credential-free model catalogue from both providers' account model lists."""
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from ai_players import load_config


def list_models(provider, key_name):
    """List all account-visible model IDs, following Anthropic pagination without generating text."""
    key = os.environ.get(key_name)
    if not key:
        raise RuntimeError(f'Set {key_name} in .env or the environment')
    if provider == 'openai':
        base = 'https://api.openai.com/v1/models'
        headers = {'Authorization': f'Bearer {key}'}
    else:
        base = 'https://api.anthropic.com/v1/models'
        headers = {'x-api-key': key, 'anthropic-version': '2023-06-01'}
    models = {}
    url = base
    seen_cursors = set()
    while True:
        try:
            with urlopen(Request(url, headers=headers), timeout=30) as response:
                page = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f'{provider} model list returned HTTP {exc.code}') from None
        except (URLError, TimeoutError):
            raise RuntimeError(f'{provider} model list network request failed') from None
        for model in page['data']:
            entry = {'model': model['id'], 'player_config': {
                'provider': provider, 'model': model['id'], 'api_key_env': key_name}}
            if model.get('display_name'):
                entry['display_name'] = model['display_name']
            models[model['id']] = entry
        if provider == 'openai' or not page.get('has_more'):
            break
        cursor = page.get('last_id')
        if not cursor or cursor in seen_cursors:
            raise RuntimeError('Anthropic model list returned an invalid pagination cursor')
        seen_cursors.add(cursor)
        url = base + '?' + urlencode({'limit': 1000, 'after_id': cursor})
    return [models[key] for key in sorted(models)]


def main():
    """Load local credentials, refresh both model lists, and write reusable player configurations."""
    folder = Path(__file__).resolve().parent
    config = load_config(folder / 'ai_config.json')
    key_names = {'openai': 'OPENAI_API_KEY', 'anthropic': 'ANTHROPIC_API_KEY'}
    for side in ('white', 'black'):
        player = config[side]
        if player['provider'] in key_names:
            key_names[player['provider']] = player.get('api_key_env', key_names[player['provider']])
    catalog = {
        'generated_at_utc': datetime.now(timezone.utc).isoformat(),
        'scope': 'All model IDs returned by the providers for your API keys',
        'usage': 'Copy a player_config into white or black in ai_config.json. This catalogue is not a game config.',
        'compatibility': 'Listing does not verify chess or endpoint support. OpenAI lists also include image, audio, embedding, moderation and legacy models which cannot play this game. Select a text model supporting Responses; Anthropic players use Messages. Set reasoning_effort only when supported by the selected model.',
        'sources': {'openai': 'https://api.openai.com/v1/models',
                    'anthropic': 'https://api.anthropic.com/v1/models'},
        'providers': {},
    }
    for provider in key_names:
        catalog['providers'][provider] = list_models(provider, key_names[provider])
    path = folder / 'model_catalog.json'
    path.write_text(json.dumps(catalog, indent=2) + '\n', encoding='utf-8')
    print(f'Saved {path.name}: ' + ', '.join(f'{p}: {len(m)} models' for p, m in catalog['providers'].items()))


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, ValueError, OSError) as exc:
        raise SystemExit(str(exc)) from None
