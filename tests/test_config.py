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


def test_ensure_config_dir_creates_directory(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    path = config.ensure_config_dir()
    assert path.is_dir()


def test_load_config_returns_empty_when_absent(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.load_config() == {}


def test_save_and_load_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"chat_id": 123456})
    assert config.load_config()["chat_id"] == 123456


def test_save_config_merges_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"chat_id": 123456})
    config.save_config({"heartbeat": {"interval_minutes": 30}})
    result = config.load_config()
    assert result["chat_id"] == 123456
    assert result["heartbeat"]["interval_minutes"] == 30


def test_save_config_overwrites_existing_key(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"chat_id": 111})
    config.save_config({"chat_id": 222})
    assert config.load_config()["chat_id"] == 222


def test_is_first_run_true_when_no_config(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.is_first_run() is True


def test_is_first_run_false_when_chat_id_set(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"chat_id": 123456})
    assert config.is_first_run() is False


def test_is_first_run_true_when_config_exists_but_no_chat_id(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"heartbeat": {"interval_minutes": 30}})
    assert config.is_first_run() is True


# --- Update offset tests ---


def test_get_update_offset_default(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.get_update_offset() == 0


def test_get_update_offset_after_save(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_update_offset(42)
    assert config.get_update_offset() == 42


def test_save_update_offset_preserves_other_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"chat_id": 123})
    config.save_update_offset(99)
    cfg = config.load_config()
    assert cfg["chat_id"] == 123
    assert cfg["last_update_id"] == 99


def test_save_update_offset_overwrites_previous(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_update_offset(10)
    config.save_update_offset(20)
    assert config.get_update_offset() == 20


# --- Heartbeat interval tests ---


def test_get_heartbeat_interval_default(tmp_path, monkeypatch):
    """Default heartbeat interval should be 30 minutes (1800 seconds)."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.get_heartbeat_interval() == 1800


def test_get_heartbeat_interval_after_save(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_heartbeat_interval(900)  # 15 minutes
    assert config.get_heartbeat_interval() == 900


def test_save_heartbeat_interval_preserves_other_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"chat_id": 123})
    config.save_heartbeat_interval(600)
    cfg = config.load_config()
    assert cfg["chat_id"] == 123
    assert cfg["heartbeat_interval"] == 600


def test_save_heartbeat_interval_overwrites_previous(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_heartbeat_interval(1800)
    config.save_heartbeat_interval(3600)
    assert config.get_heartbeat_interval() == 3600


# --- Heartbeat model tests ---


def test_get_heartbeat_model_default(tmp_path, monkeypatch):
    """Default heartbeat model should be 'haiku'."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    assert config.get_heartbeat_model() == "haiku"


def test_get_heartbeat_model_after_save(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_heartbeat_model("opus")
    assert config.get_heartbeat_model() == "opus"


def test_save_heartbeat_model_preserves_other_keys(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_config({"chat_id": 123})
    config.save_heartbeat_model("sonnet")
    cfg = config.load_config()
    assert cfg["chat_id"] == 123
    assert cfg["heartbeat_model"] == "sonnet"


def test_save_heartbeat_model_overwrites_previous(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    config.save_heartbeat_model("haiku")
    config.save_heartbeat_model("opus")
    assert config.get_heartbeat_model() == "opus"
