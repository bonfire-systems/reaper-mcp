import json
import os
from pathlib import Path

from platformdirs import user_config_dir

CONFIG_DIR = Path(user_config_dir("reaper-mcp"))
DEFAULT_CONFIG_PATH = CONFIG_DIR / "config.json"

DEFAULT_CONFIG = {
    "default_project_directory": str(Path.home() / "Documents" / "REAPER Projects"),
    "default_tempo": 120.0,
    "default_time_signature": "4/4",
    "default_sample_rate": 48000,
    "default_bit_depth": 24,
    "default_audio_format": "wav",
}


def load_config(config_path=None) -> dict:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    if not path.exists():
        os.makedirs(path.parent, exist_ok=True)
        with open(path, "w") as f:
            json.dump(DEFAULT_CONFIG, f, indent=2)
        return DEFAULT_CONFIG.copy()
    try:
        with open(path) as f:
            config = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            config.setdefault(k, v)
        return config
    except Exception:
        return DEFAULT_CONFIG.copy()


def save_config(config: dict, config_path=None) -> bool:
    path = Path(config_path) if config_path else DEFAULT_CONFIG_PATH
    try:
        os.makedirs(path.parent, exist_ok=True)
        with open(path, "w") as f:
            json.dump(config, f, indent=2)
        return True
    except Exception:
        return False
