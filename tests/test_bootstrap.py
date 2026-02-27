"""Tests for corphish.bootstrap."""

import os
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corphish.bootstrap import GREETING, run_bootstrap


def _make_deps(chat_id: int = 42):
    """Returns a dict of mock dependencies for run_bootstrap."""
    mock_bot = MagicMock()
    return {
        "get_token_fn": MagicMock(return_value="tok"),
        "build_bot_fn": MagicMock(return_value=mock_bot),
        "wait_for_message_fn": AsyncMock(return_value=chat_id),
        "send_message_fn": AsyncMock(),
        "save_config_fn": MagicMock(),
        "install_launchd_fn": MagicMock(),
        "_bot": mock_bot,
    }


async def test_all_phases_called(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    deps = _make_deps(chat_id=99)

    await run_bootstrap(
        get_token_fn=deps["get_token_fn"],
        build_bot_fn=deps["build_bot_fn"],
        wait_for_message_fn=deps["wait_for_message_fn"],
        send_message_fn=deps["send_message_fn"],
        save_config_fn=deps["save_config_fn"],
        install_launchd_fn=deps["install_launchd_fn"],
    )

    deps["get_token_fn"].assert_called_once()
    deps["build_bot_fn"].assert_called_once_with("tok")
    deps["wait_for_message_fn"].assert_awaited_once_with(deps["_bot"])
    deps["save_config_fn"].assert_called_once_with({"chat_id": 99})
    deps["send_message_fn"].assert_awaited_once()
    deps["install_launchd_fn"].assert_called_once()


async def test_chat_id_saved_to_config(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    saved = {}
    deps = _make_deps(chat_id=12345)
    deps["save_config_fn"] = lambda data: saved.update(data)

    await run_bootstrap(
        get_token_fn=deps["get_token_fn"],
        build_bot_fn=deps["build_bot_fn"],
        wait_for_message_fn=deps["wait_for_message_fn"],
        send_message_fn=deps["send_message_fn"],
        save_config_fn=deps["save_config_fn"],
        install_launchd_fn=deps["install_launchd_fn"],
    )

    assert saved["chat_id"] == 12345


async def test_greeting_sent_to_correct_chat_id(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    deps = _make_deps(chat_id=77)

    await run_bootstrap(
        get_token_fn=deps["get_token_fn"],
        build_bot_fn=deps["build_bot_fn"],
        wait_for_message_fn=deps["wait_for_message_fn"],
        send_message_fn=deps["send_message_fn"],
        save_config_fn=deps["save_config_fn"],
        install_launchd_fn=deps["install_launchd_fn"],
    )

    deps["send_message_fn"].assert_awaited_once_with(deps["_bot"], 77, GREETING)


async def test_missing_bot_token_raises(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    deps = _make_deps()
    deps["get_token_fn"] = MagicMock(side_effect=RuntimeError("TELEGRAM_BOT_TOKEN"))

    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        await run_bootstrap(
            get_token_fn=deps["get_token_fn"],
            build_bot_fn=deps["build_bot_fn"],
            wait_for_message_fn=deps["wait_for_message_fn"],
            send_message_fn=deps["send_message_fn"],
            save_config_fn=deps["save_config_fn"],
            install_launchd_fn=deps["install_launchd_fn"],
        )


async def test_missing_anthropic_key_raises(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    deps = _make_deps()

    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        await run_bootstrap(
            get_token_fn=deps["get_token_fn"],
            build_bot_fn=deps["build_bot_fn"],
            wait_for_message_fn=deps["wait_for_message_fn"],
            send_message_fn=deps["send_message_fn"],
            save_config_fn=deps["save_config_fn"],
            install_launchd_fn=deps["install_launchd_fn"],
        )


async def test_phases_called_in_order(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-test")
    call_order = []
    deps = _make_deps(chat_id=42)

    deps["get_token_fn"] = MagicMock(
        side_effect=lambda: call_order.append("get_token") or "tok"
    )
    deps["build_bot_fn"] = MagicMock(
        side_effect=lambda t: call_order.append("build_bot") or deps["_bot"]
    )
    deps["wait_for_message_fn"] = AsyncMock(
        side_effect=lambda b: call_order.append("wait") or 42
    )
    deps["save_config_fn"] = MagicMock(
        side_effect=lambda d: call_order.append("save_config")
    )
    deps["send_message_fn"] = AsyncMock(
        side_effect=lambda b, c, t: call_order.append("send_message")
    )
    deps["install_launchd_fn"] = MagicMock(
        side_effect=lambda: call_order.append("install_launchd")
    )

    await run_bootstrap(**{k: v for k, v in deps.items() if k != "_bot"})

    assert call_order == [
        "get_token",
        "build_bot",
        "wait",
        "save_config",
        "send_message",
        "install_launchd",
    ]
