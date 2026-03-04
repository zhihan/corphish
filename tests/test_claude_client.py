"""Tests for corphish.claude_client."""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corphish.claude_client import ClaudeClient, _load_system_prompt


def _make_client(**kwargs):
    """Creates a ClaudeClient with persistence disabled by default."""
    kwargs.setdefault("client", MagicMock())
    kwargs.setdefault("system_prompt", "test")
    kwargs.setdefault("history_path", None)
    return ClaudeClient(**kwargs)


def _mock_anthropic(text="reply"):
    """Returns a mock Anthropic client that returns *text*."""
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text=text)]
    mock = MagicMock()
    mock.messages.create = AsyncMock(return_value=mock_response)
    return mock


def test_load_system_prompt_returns_string():
    prompt = _load_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_client_accepts_custom_system_prompt():
    client = _make_client(system_prompt="custom prompt")
    assert client._system == "custom prompt"


def test_client_uses_injected_client():
    mock_anthropic = MagicMock()
    client = _make_client(client=mock_anthropic)
    assert client._client is mock_anthropic


def test_client_default_model():
    client = _make_client()
    assert client._model == "claude-sonnet-4-5-20250929"


def test_client_custom_model():
    client = _make_client(model="claude-haiku-4-5-20251001")
    assert client._model == "claude-haiku-4-5-20251001"


def test_busy_is_false_initially():
    client = _make_client()
    assert client.busy is False


async def test_send_returns_response_text():
    client = _make_client(client=_mock_anthropic("Hello back!"))
    result = await client.send("Hello")
    assert result == "Hello back!"


async def test_send_passes_correct_params():
    mock = _mock_anthropic("reply")
    client = _make_client(client=mock, model="test-model", system_prompt="sys")
    await client.send("hi")

    mock.messages.create.assert_awaited_once_with(
        model="test-model",
        max_tokens=4096,
        system="sys",
        messages=[{"role": "user", "content": "hi"}],
    )


async def test_send_builds_conversation_history():
    call_count = 0

    async def mock_create(**kwargs):
        nonlocal call_count
        call_count += 1
        resp = MagicMock()
        resp.content = [MagicMock(text=f"reply-{call_count}")]
        return resp

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = mock_create

    client = _make_client(client=mock_anthropic)
    await client.send("first")
    await client.send("second")

    assert len(client._history) == 4
    assert client._history[0]["role"] == "user"
    assert client._history[0]["content"] == "first"
    assert client._history[1]["role"] == "assistant"
    assert client._history[1]["content"] == "reply-1"
    assert client._history[2]["role"] == "user"
    assert client._history[2]["content"] == "second"
    assert client._history[3]["role"] == "assistant"
    assert client._history[3]["content"] == "reply-2"


async def test_lock_serialises_calls():
    """Verify that concurrent sends are serialised by the lock."""
    order = []

    async def slow_create(**kwargs):
        msg = kwargs["messages"][-1]["content"]
        order.append(f"start-{msg}")
        await asyncio.sleep(0.05)
        order.append(f"end-{msg}")
        resp = MagicMock()
        resp.content = [MagicMock(text="ok")]
        return resp

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = slow_create

    client = _make_client(client=mock_anthropic)

    async def locked_send(text):
        async with client.lock:
            return await client.send(text)

    await asyncio.gather(locked_send("a"), locked_send("b"))

    # Because the lock serialises, one must fully complete before the
    # other starts.  The exact order (a-first or b-first) depends on
    # scheduling, but there must be no interleaving.
    assert order == ["start-a", "end-a", "start-b", "end-b"] or order == [
        "start-b",
        "end-b",
        "start-a",
        "end-a",
    ]


# --- History persistence tests ---


async def test_history_saves_to_disk(tmp_path):
    hp = tmp_path / "history.json"
    client = ClaudeClient(
        client=_mock_anthropic("hi"),
        system_prompt="test",
        history_path=hp,
    )
    await client.send("hello")

    saved = json.loads(hp.read_text())
    assert len(saved) == 2
    assert saved[0]["role"] == "user"
    assert saved[0]["content"] == "hello"
    assert "ts" in saved[0]
    assert saved[1]["role"] == "assistant"
    assert saved[1]["content"] == "hi"
    assert "ts" in saved[1]


async def test_history_loads_on_init(tmp_path):
    hp = tmp_path / "history.json"
    now = datetime.now(timezone.utc).isoformat()
    existing = [
        {"role": "user", "content": "old", "ts": now},
        {"role": "assistant", "content": "reply", "ts": now},
    ]
    hp.write_text(json.dumps(existing))

    client = ClaudeClient(
        client=_mock_anthropic("new reply"),
        system_prompt="test",
        history_path=hp,
    )
    assert client._history == existing

    await client.send("new")
    assert len(client._history) == 4


def test_missing_history_file_starts_empty(tmp_path):
    hp = tmp_path / "nonexistent.json"
    client = ClaudeClient(
        client=MagicMock(),
        system_prompt="test",
        history_path=hp,
    )
    assert client._history == []


def test_corrupt_json_starts_empty(tmp_path):
    hp = tmp_path / "history.json"
    hp.write_text("not valid json {{{")

    client = ClaudeClient(
        client=MagicMock(),
        system_prompt="test",
        history_path=hp,
    )
    assert client._history == []


def test_none_history_path_disables_persistence():
    client = _make_client()
    assert client._history_path is None
    # _save_history should be a no-op
    client._save_history()


# --- TTL pruning tests ---


async def test_history_entries_include_ts():
    client = _make_client(client=_mock_anthropic("reply"))
    await client.send("hello")
    for entry in client._history:
        assert "ts" in entry
        # Should be valid ISO 8601
        datetime.fromisoformat(entry["ts"])


async def test_expired_entries_pruned_on_save(tmp_path):
    hp = tmp_path / "history.json"
    old_ts = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
    existing = [
        {"role": "user", "content": "old", "ts": old_ts},
        {"role": "assistant", "content": "old reply", "ts": old_ts},
    ]
    hp.write_text(json.dumps(existing))

    client = ClaudeClient(
        client=_mock_anthropic("new reply"),
        system_prompt="test",
        history_path=hp,
        history_ttl_days=7,
    )
    await client.send("new")

    # Old entries should be pruned; only the new pair remains.
    assert len(client._history) == 2
    assert client._history[0]["content"] == "new"
    assert client._history[1]["content"] == "new reply"


async def test_ttl_none_disables_pruning(tmp_path):
    hp = tmp_path / "history.json"
    old_ts = (datetime.now(timezone.utc) - timedelta(days=100)).isoformat()
    existing = [
        {"role": "user", "content": "ancient", "ts": old_ts},
        {"role": "assistant", "content": "ancient reply", "ts": old_ts},
    ]
    hp.write_text(json.dumps(existing))

    client = ClaudeClient(
        client=_mock_anthropic("new reply"),
        system_prompt="test",
        history_path=hp,
        history_ttl_days=None,
    )
    await client.send("new")

    # All 4 entries kept (no pruning).
    assert len(client._history) == 4


async def test_legacy_entries_without_ts_pruned(tmp_path):
    hp = tmp_path / "history.json"
    existing = [
        {"role": "user", "content": "legacy"},
        {"role": "assistant", "content": "legacy reply"},
    ]
    hp.write_text(json.dumps(existing))

    client = ClaudeClient(
        client=_mock_anthropic("new reply"),
        system_prompt="test",
        history_path=hp,
        history_ttl_days=7,
    )
    await client.send("new")

    # Legacy entries (no ts) are dropped; only the new pair remains.
    assert len(client._history) == 2
    assert client._history[0]["content"] == "new"


async def test_messages_sent_to_api_exclude_ts():
    mock = _mock_anthropic("reply")
    client = _make_client(client=mock)
    await client.send("hi")

    call_kwargs = mock.messages.create.call_args
    messages = call_kwargs.kwargs["messages"]
    for msg in messages:
        assert "ts" not in msg
        assert set(msg.keys()) == {"role", "content"}
