"""Settings persistence for the standalone app.

Settings live in %APPDATA%\voice-text-input\settings.json so the exe can be
a single portable file and survive upgrades. The JSON holds the engine config
plus app-only keys such as "theme".
"""

import json
import os
from pathlib import Path

from src.settings import Settings

APP_DIR_NAME = "voice-text-input"
FILE_NAME = "settings.json"


def config_dir() -> Path:
    base = os.environ.get("APPDATA") or str(Path.home())
    return Path(base) / APP_DIR_NAME


def config_path() -> Path:
    return config_dir() / FILE_NAME


def load_app() -> dict:
    """The whole stored JSON (engine config + app-only keys)."""
    try:
        raw = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return raw if isinstance(raw, dict) else {}


def save_app(data: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def settings_fields(settings: Settings) -> dict:
    return {name: getattr(settings, name)
            for name in type(settings).__dataclass_fields__}


def load() -> Settings:
    return Settings.from_config(load_app())
