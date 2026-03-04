"""Claude Agent SDK adapter with conversation persistence."""

import asyncio
import json
import logging
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from anthropic import AsyncAnthropic

from . import config

logger = logging.getLogger(__name__)

_SENTINEL = object()


def _load_system_prompt() -> str:
    """Loads the system prompt from IDENTITY.md.

    Returns:
        The contents of IDENTITY.md, or a minimal fallback.
    """
    identity_path = Path(__file__).parent.parent / "IDENTITY.md"
    if identity_path.exists():
        return identity_path.read_text()
    return "You are Corphish, a personal AI assistant."


def _load_history(path: Path) -> list[dict]:
    """Loads conversation history from a JSON file.

    Returns an empty list if the file is missing or contains invalid JSON.
    """
    try:
        return json.loads(path.read_text())
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return []


class ClaudeClient:
    """Wraps the Anthropic async client with conversation state and a lock.

    Maintains a running message history so Claude has full context across
    turns.  An asyncio.Lock serialises calls so only one request is in
    flight at a time (used to skip heartbeats while busy).

    Args:
        client: An AsyncAnthropic instance (injectable for testing).
        model: The model name to use.
        system_prompt: Override the default system prompt.
        history_path: Path for persisting history to JSON.
            Defaults to ``<config_dir>/history.json``.
            Pass ``None`` to disable persistence.
    """

    def __init__(
        self,
        *,
        client: Optional[AsyncAnthropic] = None,
        model: str = "claude-sonnet-4-5-20250929",
        system_prompt: Optional[str] = None,
        history_path: object = _SENTINEL,
        history_ttl_days: Optional[int] = 7,
    ) -> None:
        self._client = client or AsyncAnthropic()
        self._model = model
        self._system = system_prompt or _load_system_prompt()
        self._ttl_days = history_ttl_days

        if history_path is _SENTINEL:
            self._history_path: Optional[Path] = (
                config.get_config_dir() / "history.json"
            )
        else:
            self._history_path = history_path  # type: ignore[assignment]

        if self._history_path is not None:
            self._history: list[dict] = _load_history(self._history_path)
        else:
            self._history = []

        self.lock = asyncio.Lock()

    @property
    def busy(self) -> bool:
        """Returns True if the lock is currently held."""
        return self.lock.locked()

    def _save_history(self) -> None:
        """Persists conversation history to disk via atomic write.

        If ``_ttl_days`` is set, entries older than that (or missing a ``ts``
        field) are pruned before writing.
        """
        if self._history_path is None:
            return
        if self._ttl_days is not None:
            cutoff = datetime.now(timezone.utc) - timedelta(days=self._ttl_days)
            cutoff_iso = cutoff.isoformat()
            self._history = [
                e for e in self._history if e.get("ts", "") >= cutoff_iso
            ]
        self._history_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._history_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._history))
        tmp.replace(self._history_path)

    async def send(self, user_text: str) -> str:
        """Sends a user message and returns Claude's response.

        Appends both the user message and assistant response to the
        conversation history so context is preserved across turns.

        Args:
            user_text: The message from the user.

        Returns:
            The text content of Claude's response.
        """
        now = datetime.now(timezone.utc).isoformat()
        self._history.append({"role": "user", "content": user_text, "ts": now})

        # Strip ts before sending to the API.
        messages = [
            {"role": e["role"], "content": e["content"]} for e in self._history
        ]

        response = await self._client.messages.create(
            model=self._model,
            max_tokens=4096,
            system=self._system,
            messages=messages,
        )

        assistant_text = response.content[0].text
        self._history.append(
            {"role": "assistant", "content": assistant_text, "ts": now}
        )
        self._save_history()
        return assistant_text
