"""Daemon components: message consumer, processor, and integration via SQLite."""

import asyncio
import logging
from pathlib import Path
from typing import Callable, Optional

from telegram import Bot

from . import chat, config, db
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


async def run_message_consumer(
    *,
    get_token_fn: Callable = chat.get_bot_token,
    build_bot_fn: Callable = chat.build_bot,
    load_config_fn: Callable = config.load_config,
    poll_fn: Optional[Callable] = None,
    once: bool = False,
    get_offset_fn: Callable = config.get_update_offset,
    save_offset_fn: Callable = config.save_update_offset,
    db_path: Optional[Path] = None,
    insert_incoming_fn: Callable = db.insert_incoming_message,
) -> None:
    """Runs the message consumer loop.

    Polls Telegram for updates and writes incoming messages to the database.
    This component is responsible only for ingestion — it does not process
    messages or interact with Claude.

    Args:
        get_token_fn: Returns the Telegram bot token.
        build_bot_fn: Builds a Bot from a token.
        load_config_fn: Returns the current config dict.
        poll_fn: Async callable(bot, offset) returning updates.
        once: If True, process one batch of updates and return (for testing).
        get_offset_fn: Returns the persisted update offset.
        save_offset_fn: Persists the update offset.
        db_path: Path to the database file.
        insert_incoming_fn: Function to insert incoming messages to DB.
    """
    token = get_token_fn()
    bot = build_bot_fn(token)
    cfg = load_config_fn()
    chat_id = cfg["chat_id"]
    poll = poll_fn or _poll_updates
    offset = get_offset_fn()
    poll_backoff = 0

    logger.info("Message consumer started, listening on chat %s", chat_id)

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
            logger.info("[consumer] Received message: %s", user_text[:50])

            try:
                await insert_incoming_fn(
                    text=user_text,
                    telegram_update_id=update.update_id,
                    telegram_message_id=update.message.message_id,
                    db_path=db_path,
                )
            except Exception:
                logger.exception("Failed to insert message to database")

        if once:
            break

        await asyncio.sleep(1)


async def run_message_processor(
    *,
    get_token_fn: Callable = chat.get_bot_token,
    build_bot_fn: Callable = chat.build_bot,
    load_config_fn: Callable = config.load_config,
    send_message_fn: Callable = chat.send_message,
    claude: Optional[ClaudeClient] = None,
    once: bool = False,
    db_path: Optional[Path] = None,
    get_next_unprocessed_fn: Callable = db.get_next_unprocessed_message,
    mark_processed_fn: Callable = db.mark_message_processed,
    insert_outgoing_fn: Callable = db.insert_outgoing_message,
    get_unsent_outgoing_fn: Callable = db.get_unsent_outgoing_messages,
    mark_outgoing_sent_fn: Callable = db.mark_outgoing_message_sent,
) -> None:
    """Runs the message processor loop.

    Polls the database for unprocessed messages, sends them to Claude,
    writes responses to the database, and dispatches them via Telegram.

    Args:
        get_token_fn: Returns the Telegram bot token.
        build_bot_fn: Builds a Bot from a token.
        load_config_fn: Returns the current config dict.
        send_message_fn: Sends a message via Telegram.
        claude: A ClaudeClient instance.
        once: If True, process one message and return (for testing).
        db_path: Path to the database file.
        get_next_unprocessed_fn: Function to get next unprocessed message.
        mark_processed_fn: Function to mark message as processed.
        insert_outgoing_fn: Function to insert outgoing message.
        get_unsent_outgoing_fn: Function to get unsent outgoing messages.
        mark_outgoing_sent_fn: Function to mark outgoing message as sent.
    """
    token = get_token_fn()
    bot = build_bot_fn(token)
    cfg = load_config_fn()
    chat_id = cfg["chat_id"]
    client = claude or ClaudeClient()

    logger.info("Message processor started")

    while True:
        # Process incoming messages
        message = await get_next_unprocessed_fn(db_path=db_path)

        if message:
            user_text = message["text"]
            logger.info("[processor] Processing: %s", user_text[:50])

            # Handle /reset command
            if user_text.strip().startswith("/reset"):
                async with client.lock:
                    client.reset()
                reply = (
                    "Context and conversation history have been reset. "
                    "Starting fresh while preserving any files created."
                )
                logger.info("[system] Reset conversation")
            else:
                try:
                    async with client.lock:
                        reply = await client.send(user_text)
                except Exception:
                    logger.exception("Claude call failed for message: %s", user_text)
                    await mark_processed_fn(message["id"], db_path=db_path)
                    continue
                except asyncio.CancelledError:
                    logger.warning(
                        "Claude call cancelled (SDK cleanup leak) for message: %s",
                        user_text,
                    )
                    await mark_processed_fn(message["id"], db_path=db_path)
                    continue

            logger.info("[assistant] %s", reply[:50])

            # Mark incoming message as processed
            await mark_processed_fn(message["id"], db_path=db_path)

            # Insert outgoing message to database
            await insert_outgoing_fn(text=reply, db_path=db_path)

        # Send any unsent outgoing messages
        outgoing = await get_unsent_outgoing_fn(db_path=db_path)
        for msg in outgoing:
            try:
                sent_message = await send_message_fn(bot, chat_id, msg["text"])
                await mark_outgoing_sent_fn(
                    msg["id"], sent_message.message_id, db_path=db_path
                )
            except Exception:
                logger.exception("Failed to send message via Telegram")
            except asyncio.CancelledError:
                logger.warning("send_message cancelled (SDK cleanup leak)")

        if once:
            break

        await asyncio.sleep(1)


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
    db_path: Optional[Path] = None,
) -> None:
    """Runs both message consumer and processor concurrently.

    This is the main entry point that starts both the message consumer
    (polls Telegram) and message processor (polls DB, processes via Claude)
    loops concurrently.

    Args:
        get_token_fn: Returns the Telegram bot token.
        build_bot_fn: Builds a Bot from a token.
        load_config_fn: Returns the current config dict.
        send_message_fn: Sends a message via Telegram.
        poll_fn: Async callable(bot, offset) returning updates.
        claude: A ClaudeClient instance.
        once: If True, process one iteration and return (for testing).
        get_offset_fn: Returns the persisted update offset.
        save_offset_fn: Persists the update offset.
        db_path: Path to the database file.
    """
    # Initialize database
    await db.init_db(db_path)

    logger.info("Daemon started")

    # Run consumer and processor concurrently
    await asyncio.gather(
        run_message_consumer(
            get_token_fn=get_token_fn,
            build_bot_fn=build_bot_fn,
            load_config_fn=load_config_fn,
            poll_fn=poll_fn,
            once=once,
            get_offset_fn=get_offset_fn,
            save_offset_fn=save_offset_fn,
            db_path=db_path,
        ),
        run_message_processor(
            get_token_fn=get_token_fn,
            build_bot_fn=build_bot_fn,
            load_config_fn=load_config_fn,
            send_message_fn=send_message_fn,
            claude=claude,
            once=once,
            db_path=db_path,
        ),
    )
