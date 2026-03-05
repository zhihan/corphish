"""Claude Agent SDK adapter with tool support via claude_code preset."""

import asyncio
import logging
from pathlib import Path
from typing import Optional

from claude_agent_sdk import (
    AssistantMessage,
    ClaudeAgentOptions,
    ResultMessage,
    TextBlock,
    query,
)

from . import config

logger = logging.getLogger(__name__)

_DEFAULT_MODEL = "claude-opus-4-5-20251101"

_DISALLOWED_TOOLS = ["EnterPlanMode", "ExitPlanMode", "AskUserQuestion"]


def _load_system_prompt() -> str:
    """Loads the system prompt from IDENTITY.md.

    Returns:
        The contents of IDENTITY.md, or a minimal fallback.
    """
    identity_path = Path(__file__).parent.parent / "IDENTITY.md"
    if identity_path.exists():
        return identity_path.read_text()
    return "You are Corphish, a personal AI assistant."


def _build_options(
    *,
    model: str = _DEFAULT_MODEL,
    system_prompt: Optional[str] = None,
) -> ClaudeAgentOptions:
    """Builds ClaudeAgentOptions with the claude_code preset.

    Uses the claude_code system prompt preset which provides all built-in
    Claude Code tools (Bash, Read, Write, Edit, Grep, Glob, etc.).
    The custom system prompt from IDENTITY.md is appended to the preset.

    Args:
        model: The model name to use.
        system_prompt: Override the default system prompt appended to the
            preset. Defaults to the contents of IDENTITY.md.

    Returns:
        Configured ClaudeAgentOptions.
    """
    prompt_text = system_prompt or _load_system_prompt()
    return ClaudeAgentOptions(
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": prompt_text,
        },
        permission_mode="bypassPermissions",
        disallowed_tools=list(_DISALLOWED_TOOLS),
        model=model,
        continue_conversation=True,
        cwd=str(config.get_config_dir()),
    )


class ClaudeClient:
    """Wraps the Claude Agent SDK with a lock for serialised access.

    Uses the claude_code system prompt preset which provides all built-in
    tools.  The Agent SDK handles the tool-use loop automatically —
    when Claude calls a tool, the SDK executes it and feeds the result
    back until Claude produces a final text response.

    An asyncio.Lock serialises calls so only one request is in flight at
    a time (used to skip heartbeats while busy).

    Args:
        model: The model name to use.
        system_prompt: Override the default system prompt.
        options: Fully-constructed ClaudeAgentOptions (overrides model
            and system_prompt if provided).
        query_fn: The Agent SDK query function (injectable for testing).
    """

    def __init__(
        self,
        *,
        model: str = _DEFAULT_MODEL,
        system_prompt: Optional[str] = None,
        options: Optional[ClaudeAgentOptions] = None,
        query_fn=None,
    ) -> None:
        self._options = options or _build_options(
            model=model,
            system_prompt=system_prompt,
        )
        self._query = query_fn or query
        self.lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        """Returns True if the lock is currently held."""
        return self.lock.locked()

    def reset(self) -> None:
        """Resets the conversation by recreating the options.

        This clears the conversation history and starts fresh. Any markdown
        files or other artifacts created during the conversation are preserved.
        """
        model = self._options.model or _DEFAULT_MODEL
        system_prompt_config = self._options.system_prompt

        # Extract the custom system prompt if it was appended to preset
        custom_prompt = None
        if isinstance(system_prompt_config, dict):
            if system_prompt_config.get("type") == "preset":
                custom_prompt = system_prompt_config.get("append")

        self._options = _build_options(
            model=model,
            system_prompt=custom_prompt,
        )

    async def send(self, user_text: str) -> str:
        """Sends a user message and returns Claude's final text response.

        The Agent SDK handles the full tool-use loop: if Claude calls a
        tool (Bash, Read, Write, etc.), the SDK executes it and feeds
        the result back, repeating until Claude produces a final text
        response.

        Args:
            user_text: The message from the user.

        Returns:
            The text content of Claude's final response.
        """
        last_text = ""
        result_text = None
        done = False

        async for message in self._query(
            prompt=user_text, options=self._options
        ):
            if done:
                continue
            if isinstance(message, ResultMessage):
                if message.result:
                    result_text = message.result
                done = True
            elif isinstance(message, AssistantMessage):
                parts = [
                    block.text
                    for block in message.content
                    if isinstance(block, TextBlock)
                ]
                if parts:
                    last_text = "\n".join(parts)

        return result_text or last_text
