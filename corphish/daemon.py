"""Daemon loop: polls Telegram, routes through Claude, replies."""

import asyncio
import logging
from typing import Callable, Optional

from telegram import Bot

from . import chat, config
from .claude_client import ClaudeClient

logger = logging.getLogger(__name__)

_BACKOFF_BASE = 1
_BACKOFF_MAX = 60


async def _poll_updates(bot: Bot, offset: int, timeout: int = 10):
    """Fetches new updates from Telegram starting after *offset*.

    Args:
        bot: The Telegram Bot instance.
        offset: Update ID offset (exclusive lower bound).
        timeout: Long-poll timeout in seconds.

    Returns:
        A list of Update objects.
    """
    return await bot.get_updates(offset=offset, timeout=timeout)


async def run_daemon(
    *,
    get_token_fn: Callable = chat.get_bot_token,
    build_bot_fn: Callable = chat.build_bot,
    load_config_fn: Callable = config.load_config,
    send_message_fn: Callable = chat.send_message,
    poll_fn: Optional[Callable] = None,
    claude: Optional[ClaudeClient] = None,
    once: bool = False,
    get_offset_fn: Callable = config.get_update_offset,
    save_offset_fn: Callable = config.save_update_offset,
) -> None:
    """Runs the main daemon polling loop.

    Fetches Telegram updates for the configured chat_id, sends each
    message through Claude, and replies with the response.

    Uses exponential backoff on consecutive poll failures to avoid
    tight error loops when the network is down.

    Args:
        get_token_fn: Returns the Telegram bot token.
        build_bot_fn: Builds a Bot from a token.
        load_config_fn: Returns the current config dict.
        send_message_fn: Sends a message via Telegram.
        poll_fn: Async callable(bot, offset) returning updates.
        claude: A ClaudeClient instance.
        once: If True, process one batch of updates and return (for testing).
        get_offset_fn: Returns the persisted update offset.
        save_offset_fn: Persists the update offset.
    """
    token = get_token_fn()
    bot = build_bot_fn(token)
    cfg = load_config_fn()
    chat_id = cfg["chat_id"]
    poll = poll_fn or _poll_updates
    client = claude or ClaudeClient()
    offset = get_offset_fn()
    poll_backoff = 0

    logger.info("Daemon started, listening on chat %s", chat_id)

    while True:
        try:
            updates = await poll(bot, offset)
            poll_backoff = 0
        except Exception:
            logger.exception("Failed to poll updates")
            updates = []
            if not once:
                poll_backoff = min(
                    (poll_backoff or _BACKOFF_BASE) * 2, _BACKOFF_MAX
                )
                logger.info("Backing off for %ds before next poll", poll_backoff)
                await asyncio.sleep(poll_backoff)

        for update in updates:
            offset = update.update_id + 1
            save_offset_fn(offset)

            if not update.message or not update.message.text:
                continue
            if update.message.chat.id != chat_id:
                continue

            user_text = update.message.text
            logger.info("[user] %s", user_text)

            try:
                async with client.lock:
                    reply = await client.send(user_text)
            except Exception:
                logger.exception("Claude call failed for message: %s", user_text)
                continue
            except asyncio.CancelledError:
                logger.warning(
                    "Claude call cancelled (SDK cleanup leak) for message: %s",
                    user_text,
                )
                continue

            logger.info("[assistant] %s", reply)

            try:
                await send_message_fn(bot, chat_id, reply)
            except Exception:
                logger.exception(
                    "Failed to send reply via Telegram for message: %s",
                    user_text,
                )
            except asyncio.CancelledError:
                logger.warning(
                    "send_message cancelled (SDK cleanup leak) for message: %s",
                    user_text,
                )

        if once:
            break

        await asyncio.sleep(1)
