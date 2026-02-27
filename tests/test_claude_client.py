"""Tests for corphish.claude_client."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corphish.claude_client import ClaudeClient, _load_system_prompt


def test_load_system_prompt_returns_string():
    prompt = _load_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 0


def test_client_accepts_custom_system_prompt():
    client = ClaudeClient(
        client=MagicMock(), system_prompt="custom prompt"
    )
    assert client._system == "custom prompt"


def test_client_uses_injected_client():
    mock_anthropic = MagicMock()
    client = ClaudeClient(client=mock_anthropic, system_prompt="test")
    assert client._client is mock_anthropic


def test_client_default_model():
    client = ClaudeClient(client=MagicMock(), system_prompt="test")
    assert client._model == "claude-sonnet-4-5-20250929"


def test_client_custom_model():
    client = ClaudeClient(
        client=MagicMock(), model="claude-haiku-4-5-20251001", system_prompt="test"
    )
    assert client._model == "claude-haiku-4-5-20251001"


def test_busy_is_false_initially():
    client = ClaudeClient(client=MagicMock(), system_prompt="test")
    assert client.busy is False


async def test_send_returns_response_text():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="Hello back!")]

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    client = ClaudeClient(client=mock_anthropic, system_prompt="test")
    result = await client.send("Hello")

    assert result == "Hello back!"


async def test_send_passes_correct_params():
    mock_response = MagicMock()
    mock_response.content = [MagicMock(text="reply")]

    mock_anthropic = MagicMock()
    mock_anthropic.messages.create = AsyncMock(return_value=mock_response)

    client = ClaudeClient(
        client=mock_anthropic, model="test-model", system_prompt="sys"
    )
    await client.send("hi")

    mock_anthropic.messages.create.assert_awaited_once_with(
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

    client = ClaudeClient(client=mock_anthropic, system_prompt="test")
    await client.send("first")
    await client.send("second")

    assert client._history == [
        {"role": "user", "content": "first"},
        {"role": "assistant", "content": "reply-1"},
        {"role": "user", "content": "second"},
        {"role": "assistant", "content": "reply-2"},
    ]


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

    client = ClaudeClient(client=mock_anthropic, system_prompt="test")

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
