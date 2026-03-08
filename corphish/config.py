"""Configuration management for Corphish.

Handles XDG-compliant config paths, TOML read/write, and first-run detection.
"""

import os
import tomllib
from pathlib import Path

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


def ensure_config_dir() -> Path:
    """Creates the config directory if it does not exist.

    Returns:
        Path to the config directory.
    """
    path = get_config_dir()
    path.mkdir(parents=True, exist_ok=True)
    return path


def load_config() -> dict:
    """Reads config.toml and returns its contents.

    Returns:
        Parsed config as a dict, or {} if the file does not exist.
    """
    path = get_config_path()
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def save_config(data: dict) -> None:
    """Merges data into config.toml, creating it if necessary.

    Args:
        data: Key/value pairs to merge into the existing config.
    """
    ensure_config_dir()
    merged = load_config() | data
    config_path = get_config_path()
    tmp_path = config_path.with_suffix(".tmp")
    with open(tmp_path, "wb") as f:
        tomli_w.dump(merged, f)
    tmp_path.replace(config_path)


def get_update_offset() -> int:
    """Returns the persisted Telegram update offset.

    Returns:
        The last_update_id value from config, or 0 if not set.
    """
    return load_config().get("last_update_id", 0)


def save_update_offset(offset: int) -> None:
    """Persists the Telegram update offset to config.

    Args:
        offset: The update_id + 1 to resume from on next poll.
    """
    save_config({"last_update_id": offset})


def is_first_run() -> bool:
    """Returns True if no Telegram chat has been configured yet.

    Returns:
        True if chat_id is absent from config, False otherwise.
    """
    return "chat_id" not in load_config()


# Default heartbeat interval: 30 minutes in seconds
_DEFAULT_HEARTBEAT_INTERVAL = 30 * 60


def get_heartbeat_interval() -> int:
    """Returns the heartbeat interval in seconds.

    Returns:
        The heartbeat_interval value from config, or 1800 (30 minutes) if not set.
    """
    return load_config().get("heartbeat_interval", _DEFAULT_HEARTBEAT_INTERVAL)


def save_heartbeat_interval(interval: int) -> None:
    """Persists the heartbeat interval to config.

    Args:
        interval: The heartbeat interval in seconds.
    """
    save_config({"heartbeat_interval": interval})


# Default heartbeat model: use Haiku for simple heartbeat checks
_DEFAULT_HEARTBEAT_MODEL = "haiku"


def get_heartbeat_model() -> str:
    """Returns the model to use for heartbeat checks.

    Returns:
        The heartbeat_model value from config, or "haiku" if not set.
        Valid values: "haiku", "sonnet", "opus"
    """
    return load_config().get("heartbeat_model", _DEFAULT_HEARTBEAT_MODEL)


def save_heartbeat_model(model: str) -> None:
    """Persists the heartbeat model to config.

    Args:
        model: The model to use for heartbeat checks ("haiku", "sonnet", or "opus").
    """
    save_config({"heartbeat_model": model})
