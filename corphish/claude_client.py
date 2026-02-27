"""Claude Agent SDK adapter with conversation persistence."""

import asyncio
import os
from pathlib import Path
from typing import Optional

from anthropic import AsyncAnthropic


def _load_system_prompt() -> str:
    """Loads the system prompt from IDENTITY.md.

    Returns:
        The contents of IDENTITY.md, or a minimal fallback.
    """
    identity_path = Path(__file__).parent.parent / "IDENTITY.md"
    if identity_path.exists():
        return identity_path.read_text()
    return "You are Corphish, a personal AI assistant."


class ClaudeClient:
    """Wraps the Anthropic async client with conversation state and a lock.

    Maintains a running message history so Claude has full context across
    turns.  An asyncio.Lock serialises calls so only one request is in
    flight at a time (used to skip heartbeats while busy).

    Args:
        client: An AsyncAnthropic instance (injectable for testing).
        model: The model name to use.
        system_prompt: Override the default system prompt.
    """

    def __init__(
        self,
        *,
        client: Optional[AsyncAnthropic] = None,
        model: str = "claude-sonnet-4-5-20250929",
        system_prompt: Optional[str] = None,
    ) -> None:
        self._client = client or AsyncAnthropic()
        self._model = model
        self._system = system_prompt or _load_system_prompt()
        self._history: list[dict] = []
        self.lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        """Returns True if the lock is currently held."""
        return self.lock.locked()

    async def send(self, user_text: str) -> str:
        """Sends a user message and returns Claude's response.

        Appends both the user message and assistant response to the
        conversation history so context is preserved across turns.

        Args:
            user_text: The message from the user.

        Returns:
            The text content of Claude's response.
        """
        self._history.append({"role": "user", "content": user_text})

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=self._system,
            messages=list(self._history),
        )

        assistant_text = response.content[0].text
        self._history.append({"role": "assistant", "content": assistant_text})
        return assistant_text
