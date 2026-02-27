"""Tests for corphish.daemon."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from corphish.daemon import run_daemon


def _make_update(update_id, chat_id, text):
    """Creates a mock Telegram Update object."""
    update = MagicMock()
    update.update_id = update_id
    update.message = MagicMock()
    update.message.text = text
    update.message.chat = MagicMock()
    update.message.chat.id = chat_id
    return update


def _make_deps(chat_id=42, updates=None):
    """Returns a dict of mock dependencies for run_daemon."""
    mock_bot = MagicMock()
    mock_claude = MagicMock()
    mock_claude.lock = __import__("asyncio").Lock()
    mock_claude.send = AsyncMock(return_value="claude says hi")

    return {
        "get_token_fn": MagicMock(return_value="tok"),
        "build_bot_fn": MagicMock(return_value=mock_bot),
        "load_config_fn": MagicMock(return_value={"chat_id": chat_id}),
        "send_message_fn": AsyncMock(),
        "poll_fn": AsyncMock(return_value=updates or []),
        "claude": mock_claude,
        "once": True,
        "_bot": mock_bot,
    }


async def test_daemon_processes_message():
    update = _make_update(1, 42, "hello")
    deps = _make_deps(chat_id=42, updates=[update])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["claude"].send.assert_awaited_once_with("hello")
    deps["send_message_fn"].assert_awaited_once_with(
        deps["_bot"], 42, "claude says hi"
    )


async def test_daemon_ignores_other_chat_ids():
    update = _make_update(1, 999, "wrong chat")
    deps = _make_deps(chat_id=42, updates=[update])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["claude"].send.assert_not_awaited()
    deps["send_message_fn"].assert_not_awaited()


async def test_daemon_ignores_updates_without_text():
    update = MagicMock()
    update.update_id = 1
    update.message = MagicMock()
    update.message.text = None
    update.message.chat = MagicMock()
    update.message.chat.id = 42
    deps = _make_deps(chat_id=42, updates=[update])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["claude"].send.assert_not_awaited()


async def test_daemon_ignores_updates_without_message():
    update = MagicMock()
    update.update_id = 1
    update.message = None
    deps = _make_deps(chat_id=42, updates=[update])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["claude"].send.assert_not_awaited()


async def test_daemon_processes_multiple_messages_in_order():
    updates = [
        _make_update(1, 42, "first"),
        _make_update(2, 42, "second"),
    ]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(side_effect=["reply-1", "reply-2"])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    assert deps["claude"].send.await_count == 2
    assert deps["send_message_fn"].await_count == 2

    # Verify order
    calls = deps["claude"].send.call_args_list
    assert calls[0].args[0] == "first"
    assert calls[1].args[0] == "second"


async def test_daemon_reads_chat_id_from_config():
    update = _make_update(1, 777, "hi")
    deps = _make_deps(chat_id=777, updates=[update])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["claude"].send.assert_awaited_once_with("hi")
    deps["send_message_fn"].assert_awaited_once_with(
        deps["_bot"], 777, "claude says hi"
    )


async def test_daemon_filters_mixed_chat_ids():
    updates = [
        _make_update(1, 42, "good"),
        _make_update(2, 99, "bad"),
        _make_update(3, 42, "also good"),
    ]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(side_effect=["r1", "r2"])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    assert deps["claude"].send.await_count == 2
    calls = deps["claude"].send.call_args_list
    assert calls[0].args[0] == "good"
    assert calls[1].args[0] == "also good"
