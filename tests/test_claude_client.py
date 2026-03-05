"""Tests for corphish.claude_client."""

import asyncio
from unittest.mock import MagicMock, patch

import pytest

from corphish.claude_client import (
    ClaudeClient,
    _build_options,
    _load_system_prompt,
)


# ---------------------------------------------------------------------------
# Helpers — fake Agent SDK message types
# ---------------------------------------------------------------------------


def _text_block(text):
    """Creates a fake TextBlock."""
    block = MagicMock()
    block.text = text
    # Make isinstance checks work via duck typing — we check the class name
    type(block).__name__ = "TextBlock"
    return block


def _tool_use_block(name="Bash", tool_id="tool_1", tool_input=None):
    """Creates a fake ToolUseBlock."""
    block = MagicMock()
    block.id = tool_id
    block.name = name
    block.input = tool_input or {}
    type(block).__name__ = "ToolUseBlock"
    return block


def _assistant_message(content_blocks, model="test-model"):
    """Creates a fake AssistantMessage."""
    msg = MagicMock()
    msg.content = content_blocks
    msg.model = model
    return msg


def _result_message(result=None):
    """Creates a fake ResultMessage."""
    msg = MagicMock()
    msg.result = result
    msg.subtype = "success"
    msg.duration_ms = 100
    msg.is_error = False
    return msg


def _user_message(content="", tool_use_result=None):
    """Creates a fake UserMessage (tool result)."""
    msg = MagicMock()
    msg.content = content
    msg.tool_use_result = tool_use_result
    return msg


# ---------------------------------------------------------------------------
# Patch targets — we patch isinstance to make duck-typed mocks work with
# the real SDK types.  Instead we inject a fake query_fn.
# ---------------------------------------------------------------------------


async def _fake_query(messages, **kwargs):
    """Default no-op query that yields nothing."""
    return
    yield  # make it an async generator


def _make_query_fn(message_sequence):
    """Creates a fake query_fn that yields the given messages."""

    async def fake_query(*, prompt, options):
        for msg in message_sequence:
            yield msg

    return fake_query


def _make_client(query_fn=None, **kwargs):
    """Creates a ClaudeClient with a fake query_fn."""
    from claude_agent_sdk import ClaudeAgentOptions

    kwargs.setdefault("options", ClaudeAgentOptions(system_prompt="test"))
    kwargs.setdefault("query_fn", query_fn or _fake_query)
    return ClaudeClient(**kwargs)


# ---------------------------------------------------------------------------
# System prompt tests
# ---------------------------------------------------------------------------


def test_load_system_prompt_returns_string():
    prompt = _load_system_prompt()
    assert isinstance(prompt, str)
    assert len(prompt) > 0


# ---------------------------------------------------------------------------
# Options construction tests
# ---------------------------------------------------------------------------


def test_build_options_uses_claude_code_preset():
    opts = _build_options(system_prompt="custom")
    assert opts.system_prompt["type"] == "preset"
    assert opts.system_prompt["preset"] == "claude_code"
    assert opts.system_prompt["append"] == "custom"


def test_build_options_sets_bypass_permissions():
    opts = _build_options(system_prompt="test")
    assert opts.permission_mode == "bypassPermissions"


def test_build_options_disallows_interactive_tools():
    opts = _build_options(system_prompt="test")
    assert "EnterPlanMode" in opts.disallowed_tools
    assert "ExitPlanMode" in opts.disallowed_tools
    assert "AskUserQuestion" in opts.disallowed_tools


def test_build_options_sets_model():
    opts = _build_options(model="claude-haiku-4-5-20251001", system_prompt="test")
    assert opts.model == "claude-haiku-4-5-20251001"


def test_build_options_enables_continue_conversation():
    opts = _build_options(system_prompt="test")
    assert opts.continue_conversation is True


# ---------------------------------------------------------------------------
# Client construction tests
# ---------------------------------------------------------------------------


def test_client_accepts_custom_options():
    from claude_agent_sdk import ClaudeAgentOptions

    custom = ClaudeAgentOptions(system_prompt="custom")
    client = _make_client(options=custom)
    assert client._options is custom


def test_busy_is_false_initially():
    client = _make_client()
    assert client.busy is False


# ---------------------------------------------------------------------------
# send() — basic response tests
# ---------------------------------------------------------------------------


async def test_send_returns_text_from_assistant_message():
    """Simple case: assistant returns a single text block."""
    from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

    messages = [
        AssistantMessage(content=[TextBlock(text="Hello back!")], model="test"),
        ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s1",
        ),
    ]
    client = _make_client(query_fn=_make_query_fn(messages))
    result = await client.send("Hello")
    assert result == "Hello back!"


async def test_send_prefers_result_message_result():
    """When ResultMessage has a result field, prefer that."""
    from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

    messages = [
        AssistantMessage(content=[TextBlock(text="intermediate")], model="test"),
        ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s1",
            result="final answer",
        ),
    ]
    client = _make_client(query_fn=_make_query_fn(messages))
    result = await client.send("question")
    assert result == "final answer"


async def test_send_returns_empty_on_no_text():
    """When no text blocks are produced, return empty string."""
    from claude_agent_sdk import ResultMessage

    messages = [
        ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=0,
            session_id="s1",
        ),
    ]
    client = _make_client(query_fn=_make_query_fn(messages))
    result = await client.send("hi")
    assert result == ""


# ---------------------------------------------------------------------------
# send() — tool use flow tests
# ---------------------------------------------------------------------------


async def test_send_handles_tool_use_loop():
    """Verify that when Claude uses tools, the final text is returned."""
    from claude_agent_sdk import (
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ResultMessage,
        UserMessage,
    )

    messages = [
        # Step 1: Claude decides to use a tool
        AssistantMessage(
            content=[
                TextBlock(text="Let me check the files."),
                ToolUseBlock(id="t1", name="Bash", input={"command": "ls"}),
            ],
            model="test",
        ),
        # Step 2: Tool result comes back (SDK handles execution)
        UserMessage(content="file1.py\nfile2.py"),
        # Step 3: Claude produces final response
        AssistantMessage(
            content=[TextBlock(text="I found 2 files: file1.py and file2.py.")],
            model="test",
        ),
        ResultMessage(
            subtype="success",
            duration_ms=200,
            duration_api_ms=150,
            is_error=False,
            num_turns=2,
            session_id="s1",
        ),
    ]
    client = _make_client(query_fn=_make_query_fn(messages))
    result = await client.send("List files")
    # Should return the final assistant text, not the intermediate one
    assert result == "I found 2 files: file1.py and file2.py."


async def test_send_handles_multi_step_tool_use():
    """Multiple tool calls in sequence before final response."""
    from claude_agent_sdk import (
        AssistantMessage,
        TextBlock,
        ToolUseBlock,
        ResultMessage,
        UserMessage,
    )

    messages = [
        # Step 1: First tool call
        AssistantMessage(
            content=[ToolUseBlock(id="t1", name="Glob", input={"pattern": "*.py"})],
            model="test",
        ),
        UserMessage(content="main.py"),
        # Step 2: Second tool call
        AssistantMessage(
            content=[
                ToolUseBlock(
                    id="t2", name="Read", input={"file_path": "main.py"}
                )
            ],
            model="test",
        ),
        UserMessage(content="print('hello')"),
        # Step 3: Final response
        AssistantMessage(
            content=[TextBlock(text="The file prints hello.")],
            model="test",
        ),
        ResultMessage(
            subtype="success",
            duration_ms=300,
            duration_api_ms=250,
            is_error=False,
            num_turns=3,
            session_id="s1",
        ),
    ]
    client = _make_client(query_fn=_make_query_fn(messages))
    result = await client.send("What does main.py do?")
    assert result == "The file prints hello."


async def test_send_passes_prompt_and_options():
    """Verify that send() passes the prompt and options to query."""
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage

    captured = {}

    async def capturing_query(*, prompt, options):
        captured["prompt"] = prompt
        captured["options"] = options
        yield ResultMessage(
            subtype="success",
            duration_ms=0,
            duration_api_ms=0,
            is_error=False,
            num_turns=0,
            session_id="s1",
        )

    opts = ClaudeAgentOptions(system_prompt="test")
    client = _make_client(query_fn=capturing_query, options=opts)
    await client.send("hello world")

    assert captured["prompt"] == "hello world"
    assert captured["options"] is opts


# ---------------------------------------------------------------------------
# Lock / busy tests
# ---------------------------------------------------------------------------


async def test_lock_serialises_calls():
    """Verify that concurrent sends are serialised by the lock."""
    from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

    order = []

    async def slow_query(*, prompt, options):
        order.append(f"start-{prompt}")
        await asyncio.sleep(0.05)
        order.append(f"end-{prompt}")
        yield AssistantMessage(
            content=[TextBlock(text=f"reply-{prompt}")], model="test"
        )
        yield ResultMessage(
            subtype="success",
            duration_ms=50,
            duration_api_ms=40,
            is_error=False,
            num_turns=1,
            session_id="s1",
        )

    client = _make_client(query_fn=slow_query)

    async def locked_send(text):
        async with client.lock:
            return await client.send(text)

    await asyncio.gather(locked_send("a"), locked_send("b"))

    assert order == ["start-a", "end-a", "start-b", "end-b"] or order == [
        "start-b",
        "end-b",
        "start-a",
        "end-a",
    ]


# ---------------------------------------------------------------------------
# send() — async generator cleanup (issue #27)
# ---------------------------------------------------------------------------


async def test_send_closes_generator_on_early_return():
    """send() must close the generator in the same task after breaking.

    Regression test for issues #27 and #36: the generator is explicitly closed
    via aclose() in the finally block so the SDK's cancel scope is torn down in
    the originating task, not deferred to GC in a different task.
    """
    from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

    closed = False

    async def gen_query(*, prompt, options):
        nonlocal closed
        try:
            yield AssistantMessage(
                content=[TextBlock(text="intermediate")], model="test"
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=100,
                duration_api_ms=80,
                is_error=False,
                num_turns=1,
                session_id="s1",
                result="final",
            )
            # This code would run if generator were not closed after early return
            yield AssistantMessage(
                content=[TextBlock(text="should not reach")], model="test"
            )
        finally:
            closed = True

    client = _make_client(query_fn=gen_query)
    result = await client.send("test")
    assert result == "final"
    assert closed, "async generator was not closed after early break"


async def test_send_closes_generator_on_normal_exhaustion():
    """Generator cleanup works on the normal (no early return) path too."""
    from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

    closed = False

    async def gen_query(*, prompt, options):
        nonlocal closed
        try:
            yield AssistantMessage(
                content=[TextBlock(text="hello")], model="test"
            )
            yield ResultMessage(
                subtype="success",
                duration_ms=100,
                duration_api_ms=80,
                is_error=False,
                num_turns=1,
                session_id="s1",
            )
        finally:
            closed = True

    client = _make_client(query_fn=gen_query)
    result = await client.send("test")
    assert result == "hello"
    assert closed, "async generator was not properly closed"


# ---------------------------------------------------------------------------
# send() — cancel scope cleanup mitigation (issue #33 / #36)
# ---------------------------------------------------------------------------


async def test_send_exhausts_generator_without_break():
    """Regression #33/#36: send() must not break out of the generator early.

    Breaking causes gen.aclose() which triggers the SDK's finally block in a
    different task, crashing with 'Attempted to exit cancel scope in a
    different task'.  Instead, send() should let the generator exhaust
    naturally so cleanup runs in the same task.
    """
    from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

    consumed = []

    async def tracking_query(prompt, options):
        messages = [
            AssistantMessage(content=[TextBlock(text="hi")], model="test"),
            ResultMessage(
                subtype="success",
                duration_ms=100,
                duration_api_ms=80,
                is_error=False,
                num_turns=1,
                session_id="s1",
            ),
            AssistantMessage(
                content=[TextBlock(text="after-result")], model="test"
            ),
        ]
        for msg in messages:
            consumed.append(type(msg).__name__)
            yield msg

    client = _make_client(query_fn=tracking_query)
    result = await client.send("test")
    assert result == "hi"
    # All messages should be consumed — no early break
    assert consumed == [
        "AssistantMessage",
        "ResultMessage",
        "AssistantMessage",
    ]


# ---------------------------------------------------------------------------
# reset() tests
# ---------------------------------------------------------------------------


def test_reset_recreates_options():
    """reset() should create fresh options to clear conversation history."""
    from claude_agent_sdk import ClaudeAgentOptions

    client = _make_client(
        options=ClaudeAgentOptions(
            system_prompt={
                "type": "preset",
                "preset": "claude_code",
                "append": "custom prompt",
            },
            model="claude-sonnet-4-5-20250929",
            continue_conversation=True,
        )
    )
    old_options = client._options

    client.reset()

    # Options should be recreated (new object)
    assert client._options is not old_options
    # But preserve the model and system prompt
    assert client._options.model == "claude-sonnet-4-5-20250929"
    assert client._options.system_prompt["type"] == "preset"
    assert client._options.system_prompt["preset"] == "claude_code"
    assert client._options.system_prompt["append"] == "custom prompt"


def test_reset_preserves_model():
    """reset() should preserve the model setting."""
    from claude_agent_sdk import ClaudeAgentOptions

    client = _make_client(
        options=ClaudeAgentOptions(
            system_prompt="test", model="claude-haiku-4-5-20251001"
        )
    )

    client.reset()

    assert client._options.model == "claude-haiku-4-5-20251001"


async def test_reset_clears_conversation_history():
    """After reset, send() should start a fresh conversation."""
    from claude_agent_sdk import AssistantMessage, TextBlock, ResultMessage

    call_count = 0

    async def tracking_query(*, prompt, options):
        nonlocal call_count
        call_count += 1
        yield AssistantMessage(
            content=[TextBlock(text=f"response-{call_count}")], model="test"
        )
        yield ResultMessage(
            subtype="success",
            duration_ms=100,
            duration_api_ms=80,
            is_error=False,
            num_turns=1,
            session_id="s1",
        )

    client = _make_client(query_fn=tracking_query)

    # First conversation
    result1 = await client.send("hello")
    assert result1 == "response-1"

    # Reset
    client.reset()

    # Second conversation should be fresh (new options passed to query)
    result2 = await client.send("hi again")
    assert result2 == "response-2"
    assert call_count == 2
