"""Daemon components: message consumer, processor, heartbeat, and integration via SQLite."""

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


def _load_heartbeat_prompt() -> str:
    """Loads the heartbeat prompt from HEARTBEAT.md.

    Returns:
        The contents of HEARTBEAT.md, or a minimal fallback.
    """
    heartbeat_path = Path(__file__).parent.parent / "HEARTBEAT.md"
    if heartbeat_path.exists():
        return heartbeat_path.read_text()
    return (
        "This is a periodic heartbeat. Decide if there is anything worth "
        "saying to the user unprompted. Default to silence."
    )


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


def _is_trivial_response(response: str) -> bool:
    """Determines if a heartbeat response is trivial and should be suppressed.

    A response is trivial if it's empty, just whitespace, or explicitly
    indicates the assistant chose to stay silent.

    Args:
        response: The response text from Claude.

    Returns:
        True if the response should be suppressed, False if it should be sent.
    """
    if not response or not response.strip():
        return True

    # Common patterns indicating intentional silence
    lowered = response.lower().strip()
    trivial_patterns = [
        "no message",
        "nothing to say",
        "staying silent",
        "stay silent",
        "no response",
        "no update",
        "silence",
    ]
    return any(pattern in lowered for pattern in trivial_patterns)


async def run_heartbeat_runner(
    *,
    claude: ClaudeClient,
    once: bool = False,
    db_path: Optional[Path] = None,
    insert_outgoing_fn: Callable = db.insert_outgoing_message,
    get_interval_fn: Callable = config.get_heartbeat_interval,
    load_prompt_fn: Callable = _load_heartbeat_prompt,
) -> None:
    """Runs the heartbeat runner loop.

    Fires at configurable intervals (default 30 minutes) and sends a check-in
    prompt to Claude. Only surfaces meaningful responses to users. Skips
    execution if Claude is currently busy processing a message.

    Args:
        claude: A ClaudeClient instance (shared with processor for lock check).
        once: If True, fire once and return (for testing).
        db_path: Path to the database file.
        insert_outgoing_fn: Function to insert outgoing message.
        get_interval_fn: Function to get heartbeat interval in seconds.
        load_prompt_fn: Function to load the heartbeat prompt.
    """
    prompt = load_prompt_fn()
    logger.info("Heartbeat runner started")

    while True:
        interval = get_interval_fn()
        logger.debug("Heartbeat sleeping for %d seconds", interval)
        await asyncio.sleep(interval)

        # Skip if Claude is busy processing a message
        if claude.busy:
            logger.info("[heartbeat] Skipping — Claude is busy")
            if once:
                break
            continue

        logger.info("[heartbeat] Firing heartbeat check-in")

        try:
            async with claude.lock:
                response = await claude.send(prompt)
        except Exception:
            logger.exception("Heartbeat Claude call failed")
            if once:
                break
            continue
        except asyncio.CancelledError:
            logger.warning("Heartbeat Claude call cancelled")
            if once:
                break
            continue

        # Only surface non-trivial responses
        if _is_trivial_response(response):
            logger.info("[heartbeat] Response was trivial, suppressing")
        else:
            logger.info("[heartbeat] Sending response: %s", response[:50])
            await insert_outgoing_fn(text=response, db_path=db_path)

        if once:
            break


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
    enable_heartbeat: bool = True,
) -> None:
    """Runs message consumer, processor, and heartbeat runner concurrently.

    This is the main entry point that starts the message consumer
    (polls Telegram), message processor (polls DB, processes via Claude),
    and heartbeat runner (periodic check-ins) loops concurrently.

    Args:
        get_token_fn: Returns the Telegram bot token.
        build_bot_fn: Builds a Bot from a token.
        load_config_fn: Returns the current config dict.
        send_message_fn: Sends a message via Telegram.
        poll_fn: Async callable(bot, offset) returning updates.
        claude: A ClaudeClient instance (shared between processor and heartbeat).
        once: If True, process one iteration and return (for testing).
        get_offset_fn: Returns the persisted update offset.
        save_offset_fn: Persists the update offset.
        db_path: Path to the database file.
        enable_heartbeat: If True, run the heartbeat runner (default True).
    """
    # Initialize database
    await db.init_db(db_path)

    # Create shared Claude client if not provided
    client = claude or ClaudeClient()

    logger.info("Daemon started")

    # Build list of tasks to run concurrently
    tasks = [
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
            claude=client,
            once=once,
            db_path=db_path,
        ),
    ]

    if enable_heartbeat:
        tasks.append(
            run_heartbeat_runner(
                claude=client,
                once=once,
                db_path=db_path,
            )
        )

    await asyncio.gather(*tasks)
