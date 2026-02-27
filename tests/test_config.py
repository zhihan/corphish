"""Tests for corphish.config."""

from pathlib import Path

from corphish import config


def test_get_config_dir_default(tmp_path, monkeypatch):
    monkeypatch.delenv("XDG_CONFIG_HOME", raising=False)
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert config.get_config_dir() == tmp_path / ".config" / "corphish"


def test_get_config_dir_xdg(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    assert config.get_config_dir() == tmp_path / "xdg" / "corphish"


def test_get_config_dir_empty_xdg_falls_back_to_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", "")
    monkeypatch.setattr(Path, "home", staticmethod(lambda: tmp_path))
    assert config.get_config_dir() == tmp_path / ".config" / "corphish"


def test_get_config_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.get_config_path() == tmp_path / "corphish" / "config.toml"


def test_get_client_secret_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.get_client_secret_path() == tmp_path / "corphish" / "client_secret.json"


def test_get_token_path(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.get_token_path() == tmp_path / "corphish" / "token.json"


def test_ensure_config_dir_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = config.ensure_config_dir()
    assert path.is_dir()


def test_load_config_returns_empty_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.load_config() == {}


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"space_name": "spaces/abc123"})
    assert config.load_config()["space_name"] == "spaces/abc123"


def test_save_config_merges_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"space_name": "spaces/abc"})
    config.save_config({"heartbeat": {"interval_minutes": 30}})
    result = config.load_config()
    assert result["space_name"] == "spaces/abc"
    assert result["heartbeat"]["interval_minutes"] == 30


def test_save_config_overwrites_existing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"space_name": "spaces/old"})
    config.save_config({"space_name": "spaces/new"})
    assert config.load_config()["space_name"] == "spaces/new"


def test_save_config_deep_merges_nested(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"heartbeat": {"interval_minutes": 30, "idle_only": True}})
    config.save_config({"heartbeat": {"interval_minutes": 15}})
    result = config.load_config()["heartbeat"]
    assert result["interval_minutes"] == 15
    assert result["idle_only"] is True


def test_is_first_run_true_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.is_first_run() is True


def test_is_first_run_false_when_space_name_set(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"space_name": "spaces/abc"})
    assert config.is_first_run() is False


def test_is_first_run_true_when_config_exists_but_no_space(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"heartbeat": {"interval_minutes": 30}})
    assert config.is_first_run() is True
