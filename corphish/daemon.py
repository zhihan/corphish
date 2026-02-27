"""Daemon loop: polls Telegram, routes through Claude, replies."""

import asyncio
from typing import Callable, Optional

from telegram import Bot

from . import chat, config
from .claude_client import ClaudeClient


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
) -> None:
    """Runs the main daemon polling loop.

    Fetches Telegram updates for the configured chat_id, sends each
    message through Claude, and replies with the response.

    Args:
        get_token_fn: Returns the Telegram bot token.
        build_bot_fn: Builds a Bot from a token.
        load_config_fn: Returns the current config dict.
        send_message_fn: Sends a message via Telegram.
        poll_fn: Async callable(bot, offset) returning updates.
        claude: A ClaudeClient instance.
        once: If True, process one batch of updates and return (for testing).
    """
    token = get_token_fn()
    bot = build_bot_fn(token)
    cfg = load_config_fn()
    chat_id = cfg["chat_id"]
    poll = poll_fn or _poll_updates
    client = claude or ClaudeClient()
    offset = 0

    print(f"Daemon started, listening on chat {chat_id}")

    while True:
        updates = await poll(bot, offset)

        for update in updates:
            offset = update.update_id + 1

            if not update.message or not update.message.text:
                continue
            if update.message.chat.id != chat_id:
                continue

            user_text = update.message.text
            print(f"[user] {user_text}")

            async with client.lock:
                reply = await client.send(user_text)

            print(f"[assistant] {reply}")
            await send_message_fn(bot, chat_id, reply)

        if once:
            break

        await asyncio.sleep(1)
