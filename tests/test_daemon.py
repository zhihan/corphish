"""Tests for corphish.daemon."""

import asyncio
import logging
from unittest.mock import AsyncMock, MagicMock, patch

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


def _make_deps(chat_id=42, updates=None, initial_offset=0):
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
        "get_offset_fn": MagicMock(return_value=initial_offset),
        "save_offset_fn": MagicMock(),
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


async def test_daemon_continues_after_claude_failure():
    """The daemon should log Claude errors and keep processing, not crash."""
    updates = [
        _make_update(1, 42, "boom"),
        _make_update(2, 42, "ok"),
    ]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(
        side_effect=[RuntimeError("API down"), "reply-ok"]
    )

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    # First message failed (Claude), second succeeded
    assert deps["claude"].send.await_count == 2
    # send_message should only be called for the second (successful) message
    deps["send_message_fn"].assert_awaited_once_with(
        deps["_bot"], 42, "reply-ok"
    )


async def test_daemon_skips_send_when_claude_fails():
    """When Claude call fails, send_message must not be called for that message."""
    updates = [_make_update(1, 42, "boom")]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(side_effect=RuntimeError("API down"))

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["send_message_fn"].assert_not_awaited()


async def test_daemon_continues_after_telegram_send_failure():
    """If Telegram send fails, the loop should continue processing."""
    updates = [
        _make_update(1, 42, "first"),
        _make_update(2, 42, "second"),
    ]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(side_effect=["r1", "r2"])
    deps["send_message_fn"] = AsyncMock(
        side_effect=[RuntimeError("Telegram timeout"), None]
    )

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    assert deps["claude"].send.await_count == 2
    assert deps["send_message_fn"].await_count == 2


async def test_daemon_continues_after_telegram_network_error():
    """Regression: httpx/getaddrinfo errors on send_message must not crash."""
    updates = [
        _make_update(1, 42, "first"),
        _make_update(2, 42, "second"),
    ]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(side_effect=["r1", "r2"])
    deps["send_message_fn"] = AsyncMock(
        side_effect=[OSError("[Errno 8] nodename nor servname provided"), None]
    )

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    # Both messages processed, second send succeeded
    assert deps["claude"].send.await_count == 2
    assert deps["send_message_fn"].await_count == 2


async def test_daemon_continues_after_poll_failure():
    """If polling Telegram raises, the daemon should log and continue."""
    deps = _make_deps(chat_id=42)
    deps["poll_fn"] = AsyncMock(side_effect=RuntimeError("network error"))

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    # Should not crash — Claude and Telegram send should not be called
    deps["claude"].send.assert_not_awaited()
    deps["send_message_fn"].assert_not_awaited()


async def test_daemon_poll_backoff(monkeypatch):
    """Consecutive poll failures should trigger exponential backoff."""
    slept = []

    async def fake_sleep(seconds):
        slept.append(seconds)

    # Patch sleep in the daemon module specifically
    monkeypatch.setattr("corphish.daemon.asyncio.sleep", fake_sleep)

    call_count = 0

    async def poll_fn(bot, offset):
        nonlocal call_count
        call_count += 1
        if call_count <= 3:
            raise RuntimeError("network down")
        if call_count == 4:
            return []
        raise KeyboardInterrupt  # stop after one successful poll

    deps = _make_deps(chat_id=42)
    deps["poll_fn"] = poll_fn
    deps["once"] = False

    with pytest.raises(KeyboardInterrupt):
        await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    # 3 failures → backoff sleeps of 2, 4, 8 seconds
    # Plus the normal 1-second sleep after the successful poll iteration
    backoff_sleeps = [s for s in slept if s > 1]
    assert backoff_sleeps == [2, 4, 8]


# --- Offset persistence tests ---


async def test_daemon_loads_offset_from_config():
    """Daemon should pass the persisted offset to the first poll call."""
    deps = _make_deps(chat_id=42, initial_offset=500)

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["get_offset_fn"].assert_called_once()
    deps["poll_fn"].assert_awaited_once_with(deps["_bot"], 500)


async def test_daemon_persists_offset_for_each_update():
    """Offset should be saved (update_id+1) for every update, before processing."""
    updates = [
        _make_update(100, 42, "first"),
        _make_update(101, 42, "second"),
    ]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(side_effect=["r1", "r2"])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    save_calls = deps["save_offset_fn"].call_args_list
    assert len(save_calls) == 2
    assert save_calls[0].args[0] == 101
    assert save_calls[1].args[0] == 102


async def test_daemon_persists_offset_before_processing():
    """Offset must be saved even for updates that are skipped (wrong chat, no text)."""
    update = _make_update(200, 999, "wrong chat")
    deps = _make_deps(chat_id=42, updates=[update])

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["save_offset_fn"].assert_called_once_with(201)
    deps["claude"].send.assert_not_awaited()


async def test_daemon_persists_offset_even_when_claude_fails():
    """Offset should be persisted even if Claude call fails."""
    update = _make_update(300, 42, "boom")
    deps = _make_deps(chat_id=42, updates=[update])
    deps["claude"].send = AsyncMock(side_effect=RuntimeError("API down"))

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["save_offset_fn"].assert_called_once_with(301)


# --- CancelledError resilience tests (issue #33) ---


async def test_daemon_continues_after_send_message_cancelled_error():
    """Regression #33: CancelledError on send_message must not crash the daemon."""
    updates = [
        _make_update(1, 42, "first"),
        _make_update(2, 42, "second"),
    ]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(side_effect=["r1", "r2"])
    deps["send_message_fn"] = AsyncMock(
        side_effect=[asyncio.CancelledError("cancel scope leak"), None]
    )

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    # Both messages should be processed; the daemon must not exit
    assert deps["claude"].send.await_count == 2
    assert deps["send_message_fn"].await_count == 2


async def test_daemon_continues_after_claude_cancelled_error():
    """Regression #33: CancelledError from Claude SDK must not crash the daemon."""
    updates = [
        _make_update(1, 42, "boom"),
        _make_update(2, 42, "ok"),
    ]
    deps = _make_deps(chat_id=42, updates=updates)
    deps["claude"].send = AsyncMock(
        side_effect=[asyncio.CancelledError("cancel scope leak"), "reply-ok"]
    )

    await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    assert deps["claude"].send.await_count == 2
    # First message's send_message should be skipped; only second succeeds
    deps["send_message_fn"].assert_awaited_once_with(deps["_bot"], 42, "reply-ok")


async def test_daemon_logs_cancelled_error_on_send(caplog):
    """CancelledError on send_message should be logged as a warning, not crash."""
    updates = [_make_update(1, 42, "hi")]
    deps = _make_deps(chat_id=42, updates=[_make_update(1, 42, "hi")])
    deps["claude"].send = AsyncMock(return_value="reply")
    deps["send_message_fn"] = AsyncMock(
        side_effect=asyncio.CancelledError("cancel scope leak")
    )

    with caplog.at_level(logging.WARNING):
        await run_daemon(**{k: v for k, v in deps.items() if k != "_bot"})

    assert any("send_message cancelled" in r.message for r in caplog.records)
