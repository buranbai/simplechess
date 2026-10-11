"""A single startup screen for choosing both players and their models."""
import json
from pathlib import Path
import tkinter as tk
from tkinter import ttk, messagebox

from ai_players import load_config


def model_choices(catalog, provider):
    """Suggest text models from the catalogue, excluding obvious specialized OpenAI models."""
    ids = [entry['model'] for entry in catalog.get('providers', {}).get(provider, [])]
    if provider == 'openai':
        excluded = ('audio', 'realtime', 'transcribe', 'tts', 'image', 'search', 'moderation', 'embedding')
        ids = [model for model in ids if model.startswith(('gpt-', 'o1', 'o3', 'o4', 'ft:gpt-'))
               and not any(term in model for term in excluded)]
    return sorted(set(ids))


class GameSetup:
    def __init__(self, root, launch):
        """Build player/model selectors and start the chosen matchup after validation."""
        self.root = root
        self.launch = launch
        self.folder = Path(__file__).resolve().parent
        self.catalog = self.read_json('model_catalog.json', {})
        self.defaults = self.read_json('match_config.json', self.read_json('ai_config.json', {}))
        root.title('Simple Chess — Choose Players')
        self.frame = ttk.Frame(root, padding=24)
        self.frame.pack(fill=tk.BOTH, expand=True)
        ttk.Label(self.frame, text='Choose who plays', font=('Segoe UI', 18, 'bold')).pack(anchor='w', pady=(0, 16))
        self.players = {}
        for side, fallback in (('white', 'openai'), ('black', 'anthropic')):
            box = ttk.LabelFrame(self.frame, text=side.title(), padding=12)
            box.pack(fill=tk.X, pady=6)
            default = self.defaults.get(side, {})
            provider = tk.StringVar(value=default.get('provider', fallback))
            model = tk.StringVar(value=default.get('model', ''))
            effort = tk.StringVar(value=default.get('reasoning_effort', 'default'))
            ttk.Label(box, text='Player').grid(row=0, column=0, sticky='w', padx=(0, 12))
            picker = ttk.Combobox(box, textvariable=provider, values=('openai', 'anthropic', 'random', 'human'), state='readonly', width=18)
            picker.grid(row=0, column=1, sticky='w')
            ttk.Label(box, text='Model').grid(row=1, column=0, sticky='w', pady=8)
            models = ttk.Combobox(box, textvariable=model, width=48)
            models.grid(row=1, column=1, sticky='ew', pady=8)
            ttk.Label(box, text='Reasoning effort').grid(row=2, column=0, sticky='w', padx=(0, 12))
            reasoning = ttk.Combobox(box, textvariable=effort, values=('default', 'none', 'low', 'medium', 'high'), state='readonly', width=18)
            reasoning.grid(row=2, column=1, sticky='w')
            box.columnconfigure(1, weight=1)
            self.players[side] = (provider, model, effort, models, reasoning)
            picker.bind('<<ComboboxSelected>>', lambda event, side=side: self.update_player(side, True))
            self.update_player(side)
        self.auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(self.frame, text='Start in auto mode', variable=self.auto).pack(anchor='w', pady=12)
        ttk.Label(self.frame, text='AI vs AI: choose an AI for both sides. AI vs Random: choose random for either side.\n'
                  'Model suggestions come from your catalogue. You can also type a model ID.\n'
                  'Use default effort for models without effort support. Available effort levels depend on the model.\n'
                  'Use .env for API keys. Random and human players need no key.', wraplength=540).pack(anchor='w', pady=8)
        ttk.Button(self.frame, text='Start Game', command=self.start_game).pack(anchor='e', pady=(12, 0))

    def read_json(self, name, fallback):
        """Read optional setup defaults or catalogue, falling back when unavailable or invalid."""
        try:
            value = json.loads((self.folder / name).read_text(encoding='utf-8-sig'))
            return value if isinstance(value, dict) else fallback
        except (OSError, ValueError):
            return fallback

    def update_player(self, side, changed=False):
        """Update model suggestions and disable AI-only settings for local players."""
        provider, model, effort, models, reasoning = self.players[side]
        name = provider.get()
        models.configure(values=model_choices(self.catalog, name), state='normal' if name in ('openai', 'anthropic') else 'disabled')
        efforts = ('default', 'none', 'low', 'medium', 'high', 'xhigh', 'max') if name == 'openai' else ('default', 'low', 'medium', 'high', 'xhigh', 'max')
        reasoning.configure(values=efforts, state='readonly' if name in ('openai', 'anthropic') else 'disabled')
        if effort.get() not in efforts:
            effort.set('default')
        if changed or not model.get():
            model.set({'openai': 'gpt-5.6-luna', 'anthropic': 'claude-haiku-4-5'}.get(name, ''))
            effort.set('low' if name == 'openai' else 'default')

    def start_game(self):
        """Validate selected players, remember non-secret settings, and launch the chess window."""
        settings = {key: value for key, value in self.defaults.items() if key not in ('white', 'black')}
        for side, (provider, model, effort, _, _) in self.players.items():
            player = {'provider': provider.get()}
            if provider.get() in ('openai', 'anthropic'):
                player['model'] = model.get().strip()
                previous = self.defaults.get(side, {})
                if previous.get('provider') == provider.get() and previous.get('api_key_env'):
                    player['api_key_env'] = previous['api_key_env']
                if effort.get() != 'default':
                    player['reasoning_effort'] = effort.get()
            settings[side] = player
        try:
            config = load_config(self.folder / 'ai_config.json', settings)
            (self.folder / 'match_config.json').write_text(json.dumps(config, indent=2) + '\n', encoding='utf-8')
        except (ValueError, OSError) as exc:
            messagebox.showerror('Cannot start game', str(exc), parent=self.root)
            return
        self.frame.destroy()
        self.launch(config, self.auto.get())
