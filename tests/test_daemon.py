"""Tests for corphish.daemon."""

import asyncio
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corphish.daemon import (
    _is_trivial_response,
    run_daemon,
    run_heartbeat_runner,
    run_message_consumer,
    run_message_processor,
)


def _make_update(update_id, chat_id, text):
    """Creates a mock Telegram Update object."""
    update = MagicMock()
    update.update_id = update_id
    update.message = MagicMock()
    update.message.text = text
    update.message.message_id = update_id * 10  # Simple mapping for testing
    update.message.chat = MagicMock()
    update.message.chat.id = chat_id
    return update


def _make_consumer_deps(chat_id=42, updates=None, initial_offset=0):
    """Returns a dict of mock dependencies for run_message_consumer."""
    mock_bot = MagicMock()

    return {
        "get_token_fn": MagicMock(return_value="tok"),
        "build_bot_fn": MagicMock(return_value=mock_bot),
        "load_config_fn": MagicMock(return_value={"chat_id": chat_id}),
        "poll_fn": AsyncMock(return_value=updates or []),
        "once": True,
        "get_offset_fn": MagicMock(return_value=initial_offset),
        "save_offset_fn": MagicMock(),
        "insert_incoming_fn": AsyncMock(return_value=1),
        "_bot": mock_bot,
    }


def _make_stream_fn(*chunks):
    """Returns an async generator function that yields the given chunks."""

    async def _gen(text):
        for chunk in chunks:
            yield chunk

    return _gen


def _make_failing_stream_fn(exc):
    """Returns an async generator function that raises exc immediately."""

    async def _gen(text):
        raise exc
        yield  # make it an async generator

    return _gen


def _make_processor_deps(chat_id=42):
    """Returns a dict of mock dependencies for run_message_processor."""
    mock_bot = MagicMock()
    mock_claude = MagicMock()
    mock_claude.lock = __import__("asyncio").Lock()
    mock_claude.stream = _make_stream_fn("claude says hi")

    mock_sent_message = MagicMock()
    mock_sent_message.message_id = 999

    return {
        "get_token_fn": MagicMock(return_value="tok"),
        "build_bot_fn": MagicMock(return_value=mock_bot),
        "load_config_fn": MagicMock(return_value={"chat_id": chat_id}),
        "send_message_fn": AsyncMock(return_value=mock_sent_message),
        "claude": mock_claude,
        "once": True,
        "get_next_unprocessed_fn": AsyncMock(return_value=None),
        "mark_processed_fn": AsyncMock(),
        "insert_outgoing_fn": AsyncMock(return_value=1),
        "get_unsent_outgoing_fn": AsyncMock(return_value=[]),
        "mark_outgoing_sent_fn": AsyncMock(),
        "_bot": mock_bot,
    }


# --- Message Consumer Tests ---


async def test_consumer_inserts_incoming_message():
    """Message consumer should insert incoming messages to database."""
    update = _make_update(1, 42, "hello")
    deps = _make_consumer_deps(chat_id=42, updates=[update])

    await run_message_consumer(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["insert_incoming_fn"].assert_awaited_once_with(
        text="hello",
        telegram_update_id=1,
        telegram_message_id=10,
        db_path=None,
    )


async def test_consumer_ignores_other_chat_ids():
    """Consumer should ignore messages from other chats."""
    update = _make_update(1, 999, "wrong chat")
    deps = _make_consumer_deps(chat_id=42, updates=[update])

    await run_message_consumer(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["insert_incoming_fn"].assert_not_awaited()


async def test_consumer_ignores_updates_without_text():
    """Consumer should ignore updates without text."""
    update = MagicMock()
    update.update_id = 1
    update.message = MagicMock()
    update.message.text = None
    update.message.chat = MagicMock()
    update.message.chat.id = 42
    deps = _make_consumer_deps(chat_id=42, updates=[update])

    await run_message_consumer(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["insert_incoming_fn"].assert_not_awaited()


# --- Message Processor Tests ---


async def test_processor_processes_message_with_claude():
    """Processor should stream messages through Claude and send each chunk."""
    message = {
        "id": 1,
        "text": "hello",
        "telegram_update_id": 1,
        "telegram_message_id": 10,
        "created_at": "2024-01-01T00:00:00Z",
    }
    deps = _make_processor_deps(chat_id=42)
    deps["get_next_unprocessed_fn"] = AsyncMock(side_effect=[message, None])

    await run_message_processor(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["mark_processed_fn"].assert_awaited_once_with(1, db_path=None)
    deps["insert_outgoing_fn"].assert_awaited_once_with(
        text="claude says hi", db_path=None
    )
    deps["send_message_fn"].assert_awaited_once_with(deps["_bot"], 42, "claude says hi")
    deps["mark_outgoing_sent_fn"].assert_awaited_once_with(1, 999, db_path=None)


async def test_processor_streams_multiple_chunks():
    """Processor should send each chunk to Telegram individually."""
    message = {
        "id": 1,
        "text": "hello",
        "telegram_update_id": 1,
        "telegram_message_id": 10,
        "created_at": "2024-01-01T00:00:00Z",
    }
    deps = _make_processor_deps(chat_id=42)
    deps["claude"].stream = _make_stream_fn("chunk one", "chunk two")
    deps["insert_outgoing_fn"] = AsyncMock(side_effect=[1, 2])
    deps["get_next_unprocessed_fn"] = AsyncMock(side_effect=[message, None])

    await run_message_processor(**{k: v for k, v in deps.items() if k != "_bot"})

    assert deps["insert_outgoing_fn"].await_count == 2
    assert deps["send_message_fn"].await_count == 2
    assert deps["mark_outgoing_sent_fn"].await_count == 2


async def test_processor_sends_outgoing_messages():
    """Processor should send unsent outgoing messages via Telegram."""
    outgoing = [{"id": 1, "text": "response", "created_at": "2024-01-01T00:00:00Z"}]
    deps = _make_processor_deps(chat_id=42)
    deps["get_unsent_outgoing_fn"] = AsyncMock(return_value=outgoing)

    await run_message_processor(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["send_message_fn"].assert_awaited_once_with(deps["_bot"], 42, "response")
    deps["mark_outgoing_sent_fn"].assert_awaited_once_with(1, 999, db_path=None)


async def test_processor_handles_reset_command():
    """/reset command should reset Claude and send confirmation."""
    message = {
        "id": 1,
        "text": "/reset",
        "telegram_update_id": 1,
        "telegram_message_id": 10,
        "created_at": "2024-01-01T00:00:00Z",
    }
    deps = _make_processor_deps(chat_id=42)
    # Return message once, then None to avoid infinite loop
    deps["get_next_unprocessed_fn"] = AsyncMock(side_effect=[message, None])
    deps["claude"].reset = MagicMock()

    await run_message_processor(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["claude"].reset.assert_called_once()
    deps["mark_processed_fn"].assert_awaited_once()
    deps["insert_outgoing_fn"].assert_awaited_once()
    # Check that confirmation message was inserted
    call_args = deps["insert_outgoing_fn"].call_args
    assert "reset" in call_args.kwargs["text"].lower()


async def test_processor_continues_after_claude_failure():
    """Processor should mark message as processed even if Claude streaming fails."""
    message = {
        "id": 1,
        "text": "boom",
        "telegram_update_id": 1,
        "telegram_message_id": 10,
        "created_at": "2024-01-01T00:00:00Z",
    }
    deps = _make_processor_deps(chat_id=42)
    deps["get_next_unprocessed_fn"] = AsyncMock(side_effect=[message, None])
    deps["claude"].stream = _make_failing_stream_fn(RuntimeError("API down"))

    await run_message_processor(**{k: v for k, v in deps.items() if k != "_bot"})

    deps["mark_processed_fn"].assert_awaited_once_with(1, db_path=None)
    deps["insert_outgoing_fn"].assert_not_awaited()


# --- Integration Tests ---


async def test_daemon_initializes_database(tmp_path):
    """run_daemon should initialize the database."""
    db_path = tmp_path / "test.db"

    # Mock all components to return immediately
    with patch("corphish.daemon.run_message_consumer", new=AsyncMock()):
        with patch("corphish.daemon.run_message_processor", new=AsyncMock()):
            with patch("corphish.daemon.run_heartbeat_runner", new=AsyncMock()):
                await run_daemon(
                    get_token_fn=MagicMock(return_value="tok"),
                    build_bot_fn=MagicMock(return_value=MagicMock()),
                    load_config_fn=MagicMock(return_value={"chat_id": 42}),
                    send_message_fn=AsyncMock(),
                    poll_fn=AsyncMock(return_value=[]),
                    once=True,
                    get_offset_fn=MagicMock(return_value=0),
                    save_offset_fn=MagicMock(),
                    db_path=db_path,
                )

    # Database file should exist
    assert db_path.exists()


async def test_daemon_runs_consumer_and_processor_concurrently():
    """run_daemon should start both consumer and processor."""
    consumer_called = False
    processor_called = False

    async def mock_consumer(**kwargs):
        nonlocal consumer_called
        consumer_called = True

    async def mock_processor(**kwargs):
        nonlocal processor_called
        processor_called = True

    with patch("corphish.daemon.run_message_consumer", new=mock_consumer):
        with patch("corphish.daemon.run_message_processor", new=mock_processor):
            with patch("corphish.daemon.run_heartbeat_runner", new=AsyncMock()):
                await run_daemon(
                    get_token_fn=MagicMock(return_value="tok"),
                    build_bot_fn=MagicMock(return_value=MagicMock()),
                    load_config_fn=MagicMock(return_value={"chat_id": 42}),
                    send_message_fn=AsyncMock(),
                    poll_fn=AsyncMock(return_value=[]),
                    once=True,
                    get_offset_fn=MagicMock(return_value=0),
                    save_offset_fn=MagicMock(),
                )

    assert consumer_called
    assert processor_called


# --- Trivial Response Detection Tests ---


def test_is_trivial_response_empty():
    """Empty responses are trivial."""
    assert _is_trivial_response("") is True
    assert _is_trivial_response("   ") is True
    assert _is_trivial_response(None) is True


def test_is_trivial_response_silence_patterns():
    """Responses indicating silence should be trivial."""
    assert _is_trivial_response("No message needed.") is True
    assert _is_trivial_response("Nothing to say right now.") is True
    assert _is_trivial_response("Staying silent.") is True
    assert _is_trivial_response("I'll stay silent on this one.") is True
    assert _is_trivial_response("No response necessary.") is True
    assert _is_trivial_response("No update at this time.") is True
    assert _is_trivial_response("Silence") is True


def test_is_trivial_response_non_trivial():
    """Meaningful responses should not be trivial."""
    assert _is_trivial_response("Remember to submit your report by 5pm.") is False
    assert _is_trivial_response("I noticed an error in the build logs.") is False
    assert _is_trivial_response("Your meeting starts in 10 minutes.") is False


# --- Heartbeat Runner Tests ---


def _make_heartbeat_deps():
    """Returns a dict of mock dependencies for run_heartbeat_runner."""
    mock_claude = MagicMock()
    mock_claude.lock = asyncio.Lock()
    mock_claude.busy = False
    mock_claude.send = AsyncMock(return_value="meaningful response")

    return {
        "claude": mock_claude,
        "once": True,
        "insert_outgoing_fn": AsyncMock(return_value=1),
        "get_interval_fn": MagicMock(return_value=0),  # No delay for testing
        "load_prompt_fn": MagicMock(return_value="Heartbeat prompt"),
    }


async def test_heartbeat_sends_meaningful_response():
    """Heartbeat should send non-trivial responses to database."""
    deps = _make_heartbeat_deps()
    deps["claude"].send = AsyncMock(return_value="Remember your meeting at 3pm!")

    await run_heartbeat_runner(**deps)

    deps["claude"].send.assert_awaited_once_with("Heartbeat prompt")
    deps["insert_outgoing_fn"].assert_awaited_once_with(
        text="Remember your meeting at 3pm!", db_path=None
    )


async def test_heartbeat_suppresses_trivial_response():
    """Heartbeat should not send trivial responses."""
    deps = _make_heartbeat_deps()
    deps["claude"].send = AsyncMock(return_value="No message needed.")

    await run_heartbeat_runner(**deps)

    deps["claude"].send.assert_awaited_once()
    deps["insert_outgoing_fn"].assert_not_awaited()


async def test_heartbeat_suppresses_empty_response():
    """Heartbeat should not send empty responses."""
    deps = _make_heartbeat_deps()
    deps["claude"].send = AsyncMock(return_value="")

    await run_heartbeat_runner(**deps)

    deps["claude"].send.assert_awaited_once()
    deps["insert_outgoing_fn"].assert_not_awaited()


async def test_heartbeat_skips_when_claude_busy():
    """Heartbeat should skip when Claude is busy."""
    deps = _make_heartbeat_deps()
    deps["claude"].busy = True

    await run_heartbeat_runner(**deps)

    deps["claude"].send.assert_not_awaited()
    deps["insert_outgoing_fn"].assert_not_awaited()


async def test_heartbeat_continues_after_claude_failure():
    """Heartbeat should handle Claude failures gracefully."""
    deps = _make_heartbeat_deps()
    deps["claude"].send = AsyncMock(side_effect=RuntimeError("API down"))

    # Should not raise
    await run_heartbeat_runner(**deps)

    deps["claude"].send.assert_awaited_once()
    deps["insert_outgoing_fn"].assert_not_awaited()


async def test_heartbeat_uses_configurable_interval():
    """Heartbeat should use interval from config."""
    deps = _make_heartbeat_deps()
    # Use 0 for testing, just verify the function is called
    deps["get_interval_fn"] = MagicMock(return_value=0)

    await run_heartbeat_runner(**deps)

    deps["get_interval_fn"].assert_called()


async def test_daemon_includes_heartbeat_runner():
    """run_daemon should start heartbeat runner when enabled."""
    consumer_called = False
    processor_called = False
    heartbeat_called = False

    async def mock_consumer(**kwargs):
        nonlocal consumer_called
        consumer_called = True

    async def mock_processor(**kwargs):
        nonlocal processor_called
        processor_called = True

    async def mock_heartbeat(**kwargs):
        nonlocal heartbeat_called
        heartbeat_called = True

    with patch("corphish.daemon.run_message_consumer", new=mock_consumer):
        with patch("corphish.daemon.run_message_processor", new=mock_processor):
            with patch("corphish.daemon.run_heartbeat_runner", new=mock_heartbeat):
                await run_daemon(
                    get_token_fn=MagicMock(return_value="tok"),
                    build_bot_fn=MagicMock(return_value=MagicMock()),
                    load_config_fn=MagicMock(return_value={"chat_id": 42}),
                    send_message_fn=AsyncMock(),
                    poll_fn=AsyncMock(return_value=[]),
                    once=True,
                    get_offset_fn=MagicMock(return_value=0),
                    save_offset_fn=MagicMock(),
                    enable_heartbeat=True,
                )

    assert consumer_called
    assert processor_called
    assert heartbeat_called


async def test_daemon_can_disable_heartbeat():
    """run_daemon should not start heartbeat when disabled."""
    heartbeat_called = False

    async def mock_heartbeat(**kwargs):
        nonlocal heartbeat_called
        heartbeat_called = True

    with patch("corphish.daemon.run_message_consumer", new=AsyncMock()):
        with patch("corphish.daemon.run_message_processor", new=AsyncMock()):
            with patch("corphish.daemon.run_heartbeat_runner", new=mock_heartbeat):
                await run_daemon(
                    get_token_fn=MagicMock(return_value="tok"),
                    build_bot_fn=MagicMock(return_value=MagicMock()),
                    load_config_fn=MagicMock(return_value={"chat_id": 42}),
                    send_message_fn=AsyncMock(),
                    poll_fn=AsyncMock(return_value=[]),
                    once=True,
                    get_offset_fn=MagicMock(return_value=0),
                    save_offset_fn=MagicMock(),
                    enable_heartbeat=False,
                )

    assert not heartbeat_called

