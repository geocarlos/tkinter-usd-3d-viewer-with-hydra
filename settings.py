"""Tiny on-disk store for user preferences that should survive between app
runs (currently just the implicit-surface tessellation quality). This is a
user preference, not scene data, so it lives next to the user rather than
in any USD file.
"""

import json
from pathlib import Path

_PATH = Path.home() / ".tkinter_usd_viewer_settings.json"


def load():
    try:
        return json.loads(_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save(values):
    try:
        _PATH.write_text(json.dumps(values))
    except OSError:
        pass
