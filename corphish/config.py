"""Configuration management for Corphish.

Handles XDG-compliant config paths, TOML read/write, and first-run detection.
"""

import os
import tomllib
from pathlib import Path
from typing import Any

import tomli_w


def get_config_dir() -> Path:
    """Returns the Corphish config directory, respecting XDG_CONFIG_HOME.

    Returns:
        Path to ~/.config/corphish/ or $XDG_CONFIG_HOME/corphish/.
    """
    xdg = os.environ.get("XDG_CONFIG_HOME") or None
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "corphish"


def get_config_path() -> Path:
    """Returns the path to config.toml.

    Returns:
        Path to the TOML config file.
    """
    return get_config_dir() / "config.toml"


def get_client_secret_path() -> Path:
    """Returns the path to client_secret.json.

    Returns:
        Path to the Google OAuth2 client secret file.
    """
    return get_config_dir() / "client_secret.json"


def get_token_path() -> Path:
    """Returns the path to token.json.

    Returns:
        Path to the cached OAuth2 token file.
    """
    return get_config_dir() / "token.json"


def ensure_config_dir() -> Path:
    """Creates the config directory if it does not exist.

    Returns:
        Path to the config directory.
    """
    path = get_config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> dict[str, Any]:
    """Reads config.toml and returns its contents.

    Returns:
        Parsed config as a dict, or {} if the file does not exist.
    """
    path = get_config_path()
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def save_config(data: dict[str, Any]) -> None:
    """Merges data into config.toml, creating it if necessary.

    Args:
        data: Key/value pairs to merge into the existing config.
    """
    ensure_config_dir()
    existing = load_config()
    merged = _deep_merge(existing, data)
    config_path = get_config_path()
    tmp_path = config_path.with_suffix(".tmp")
    with open(tmp_path, "wb") as f:
        tomli_w.dump(merged, f)
    tmp_path.replace(config_path)


def is_first_run() -> bool:
    """Returns True if no space has been configured yet.

    Returns:
        True if space_name is absent from config, False otherwise.
    """
    return "space_name" not in load_config()


def _deep_merge(base: dict[str, Any], updates: dict[str, Any]) -> dict[str, Any]:
    """Recursively merges updates into base.

    Args:
        base: The original dict.
        updates: Values to merge in; nested dicts are merged recursively.

    Returns:
        A new dict with updates applied.
    """
    result = dict(base)
    for key, value in updates.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result
