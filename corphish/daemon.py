"""Daemon components: message consumer, processor, heartbeat, and integration via SQLite."""

import asyncio
import html
import logging
import re
import time
from pathlib import Path
from typing import Callable, Optional

from telegram import Bot

from . import chat, config, db
from . import cron as cron_module
from .claude_client import ClaudeClient, MODEL_HAIKU, MODEL_OPUS, MODEL_SONNET

logger = logging.getLogger(__name__)

_BACKOFF_BASE = 1
_BACKOFF_MAX = 60

_running_cron_tasks: set = set()
_CRON_LOCK_TIMEOUT = 300  # 5 minutes
_CRON_CATCH_UP_WINDOW = 300  # 5 minutes — don't fire jobs missed by more than this


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
    claude: Optional[ClaudeClient] = None,
    insert_outgoing_fn: Callable = db.insert_outgoing_message,
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
        claude: Shared ClaudeClient; if provided, stop commands signal it directly.
        insert_outgoing_fn: Function to insert outgoing messages to DB.
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

            if _is_stop_command(user_text):
                logger.info("[consumer] Stop command received")
                if claude is not None:
                    claude.request_stop()
                    try:
                        await insert_outgoing_fn(text="Stopped.", db_path=db_path)
                    except Exception:
                        logger.exception("Failed to insert stop response")
                continue

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
    get_max_turns_fn: Callable = config.get_max_conversation_turns,
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
        get_max_turns_fn: Function to get the max turns before auto-reset.
    """
    token = get_token_fn()
    bot = build_bot_fn(token)
    cfg = load_config_fn()
    chat_id = cfg["chat_id"]
    client = claude or ClaudeClient()
    turn_count = 0

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
                logger.info("[system] Reset conversation")
                await mark_processed_fn(message["id"], db_path=db_path)
                await insert_outgoing_fn(
                    text=(
                        "Context and conversation history have been reset. "
                        "Starting fresh while preserving any files created."
                    ),
                    db_path=db_path,
                )
            else:
                # Mark processed before streaming so a mid-stream restart
                # (e.g. Claude restarting its own daemon) cannot cause the
                # same message to be picked up and processed again.
                await mark_processed_fn(message["id"], db_path=db_path)

                # Clear any stale stop signal before starting a new stream
                client.clear_stop()

                try:
                    async with client.lock:
                        async for chunk in client.stream(
                            user_text, stop_event=client.stop_event
                        ):
                            logger.info("[assistant] %s", chunk[:50])
                            try:
                                outgoing_id = await insert_outgoing_fn(
                                    text=chunk, db_path=db_path
                                )
                            except Exception:
                                logger.exception("Failed to insert outgoing chunk")
                                continue
                            try:
                                sent_message = await send_message_fn(
                                    bot, chat_id, chunk
                                )
                                await mark_outgoing_sent_fn(
                                    outgoing_id,
                                    sent_message.message_id,
                                    db_path=db_path,
                                )
                            except Exception:
                                logger.exception(
                                    "Failed to send chunk via Telegram"
                                )
                            except asyncio.CancelledError:
                                logger.warning(
                                    "send_message cancelled (SDK cleanup leak)"
                                )
                except Exception:
                    logger.exception(
                        "Claude streaming failed for message: %s", user_text
                    )
                    continue
                except asyncio.CancelledError:
                    logger.warning(
                        "Claude streaming cancelled for message: %s", user_text
                    )
                    continue

                if client.stop_event.is_set():
                    client.clear_stop()
                    logger.info("[processor] Stream stopped by stop command")
                    continue

                turn_count += 1
                if turn_count >= get_max_turns_fn():
                    async with client.lock:
                        client.reset()
                    turn_count = 0
                    logger.info(
                        "[processor] Auto-reset conversation after %d turns",
                        get_max_turns_fn(),
                    )

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


_STOP_COMMANDS = frozenset([
    "stop", "/stop", "!stop",
    "kill", "/kill", "!kill",
])


def _is_stop_command(text: str) -> bool:
    """Returns True if the text is a stop/kill command (case-insensitive)."""
    return text.strip().lower() in _STOP_COMMANDS


_HEARTBEAT_TOKEN = "HEARTBEAT_OK"

_ACK_PHRASES = frozenset([
    "ok", "okay", "acknowledged", "noted",
    "nothing to report", "nothing to say", "nothing new", "no updates",
    "all clear", "no action needed", "no message", "no issues",
    "silence", "staying silent", "remain silent", "nothing worth",
    "no response", "no update", "waiting for",
    "i'm ready", "ready to", "all set",
])


def is_heartbeat_response(response: str) -> bool:
    """Returns True if the response is a heartbeat acknowledgment to be suppressed.

    A fast check: if the response contains HEARTBEAT_OK and is short (≤ 500
    characters), treat it as a heartbeat acknowledgment rather than real
    content — even if Claude narrated around the token.

    Args:
        response: The response text from Claude.

    Returns:
        True if the response should be treated as a heartbeat (suppress delivery).
    """
    if not response:
        return True
    return _HEARTBEAT_TOKEN in response and len(response) <= 500


def strip_heartbeat_token(response: str) -> Optional[str]:
    """Strips the HEARTBEAT_OK token and surrounding LLM narration.

    Returns None if nothing meaningful remains (suppress), or the content
    to deliver if real content is present. Processing steps:
    1. Normalize: unescape HTML entities, strip HTML tags and markdown.
    2. Strip HEARTBEAT_OK and surrounding punctuation/whitespace.
    3. Collapse whitespace.
    4. Suppress if nothing remains.
    5. Suppress if only a short acknowledgment phrase remains.
    6. Otherwise return the cleaned text for delivery.

    Args:
        response: The response text from Claude.

    Returns:
        None if the response should be suppressed, or the content to deliver.
    """
    if not response or not response.strip():
        return None

    # Strip HEARTBEAT_OK first (before markdown normalization, which would
    # destroy the underscore and prevent the token from being recognised)
    text = re.sub(
        r"[\s.,;:!\-\u2013\u2014]*HEARTBEAT_OK[\s.,;:!\-\u2013\u2014]*",
        " ",
        response,
        flags=re.IGNORECASE,
    )

    # Normalize: unescape HTML, strip tags and markdown formatting
    text = html.unescape(text)
    text = re.sub(r"<[^>]+>", "", text)           # strip HTML tags
    text = re.sub(r"[*_`#~]+", "", text)           # strip markdown formatting

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    if not text:
        return None

    # Suppress short acknowledgment phrases
    lowered = text.lower()
    if len(text) <= 120 and any(phrase in lowered for phrase in _ACK_PHRASES):
        return None

    return text


def _needs_escalation(response: str) -> bool:
    """Determines if a response signals that a more capable model is needed.

    Detects uncertainty patterns that suggest Haiku (or a smaller model)
    cannot adequately handle the request and should escalate to Opus.

    Args:
        response: The response text from Claude.

    Returns:
        True if the response indicates escalation is needed, False otherwise.
    """
    if not response or not response.strip():
        return False

    lowered = response.lower().strip()

    # Patterns indicating uncertainty or need for deeper analysis
    uncertainty_patterns = [
        "i'm not sure",
        "i am not sure",
        "not certain",
        "this needs deeper analysis",
        "deeper analysis",
        "needs more thought",
        "requires more context",
        "beyond my ability",
        "i cannot determine",
        "i can't determine",
        "uncertain about",
        "need to escalate",
        "escalate this",
        "more complex than",
        "this is complex",
        "i don't have enough information",
        "i do not have enough information",
        "requires further investigation",
    ]
    return any(pattern in lowered for pattern in uncertainty_patterns)


def _get_model_for_name(name: str) -> str:
    """Returns the model ID for a given model name.

    Args:
        name: Short model name ("haiku", "sonnet", or "opus").

    Returns:
        The full model ID string.
    """
    mapping = {
        "haiku": MODEL_HAIKU,
        "sonnet": MODEL_SONNET,
        "opus": MODEL_OPUS,
    }
    return mapping.get(name.lower(), MODEL_HAIKU)


async def run_heartbeat_runner(
    *,
    claude: ClaudeClient,
    once: bool = False,
    db_path: Optional[Path] = None,
    insert_outgoing_fn: Callable = db.insert_outgoing_message,
    get_interval_fn: Callable = config.get_heartbeat_interval,
    load_prompt_fn: Callable = _load_heartbeat_prompt,
    get_model_fn: Callable = config.get_heartbeat_model,
    log_usage_fn: Callable = db.log_model_usage,
) -> None:
    """Runs the heartbeat runner loop with dynamic model switching.

    Fires at configurable intervals (default 30 minutes) and sends a check-in
    prompt to Claude. Uses Haiku by default for cost efficiency, escalating
    to Opus if the response signals uncertainty or need for deeper reasoning.

    Args:
        claude: A ClaudeClient instance (shared with processor for lock check).
        once: If True, fire once and return (for testing).
        db_path: Path to the database file.
        insert_outgoing_fn: Function to insert outgoing message.
        get_interval_fn: Function to get heartbeat interval in seconds.
        load_prompt_fn: Function to load the heartbeat prompt.
        get_model_fn: Function to get the default heartbeat model name.
        log_usage_fn: Function to log model usage for cost tracking.
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

        # Get configured default model (defaults to Haiku)
        model_name = get_model_fn()
        model_id = _get_model_for_name(model_name)
        escalated = False

        try:
            async with claude.lock:
                response = await claude.send_heartbeat(prompt, model_id)

            # Log initial model usage
            await log_usage_fn(
                model=model_id,
                source="heartbeat",
                escalated=False,
                db_path=db_path,
            )

            # Check if response signals need for escalation
            if _needs_escalation(response) and model_id != MODEL_OPUS:
                logger.info(
                    "[heartbeat] Response signals uncertainty, escalating to Opus"
                )
                async with claude.lock:
                    response = await claude.send_heartbeat(prompt, MODEL_OPUS)

                # Log escalated usage
                await log_usage_fn(
                    model=MODEL_OPUS,
                    source="heartbeat",
                    escalated=True,
                    db_path=db_path,
                )
                escalated = True

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
        message_text = strip_heartbeat_token(response)
        if message_text is None:
            logger.info("[heartbeat] Response was trivial, suppressing")
        else:
            if escalated:
                logger.info(
                    "[heartbeat] Sending escalated response: %s", message_text[:50]
                )
            else:
                logger.info("[heartbeat] Sending response: %s", message_text[:50])
            await insert_outgoing_fn(text=message_text, db_path=db_path)

        if once:
            break


async def _run_cron_job(
    job: dict,
    *,
    claude: ClaudeClient,
    send_message_fn: Callable,
    bot,
    chat_id: int,
    db_path,
) -> None:
    """Executes a single cron job: calls Claude and delivers a non-trivial response.

    Args:
        job: The cron job dict from the database.
        claude: A ClaudeClient instance.
        send_message_fn: Sends a message via Telegram.
        bot: The Telegram Bot instance.
        chat_id: The Telegram chat ID.
        db_path: Path to the database file.
    """
    ran_at = int(time.time())
    try:
        try:
            async with asyncio.timeout(_CRON_LOCK_TIMEOUT):
                async with claude.lock:
                    response = await claude.send_heartbeat(job["prompt"], MODEL_SONNET)
        except TimeoutError:
            logger.warning("[cron] Job %r timed out waiting for lock, skipping", job["name"])
            await db.insert_cron_job_run(
                job["id"], ran_at, "skipped", "suppressed", db_path=db_path
            )
            return

        message_text = strip_heartbeat_token(response)
        if message_text:
            await send_message_fn(bot, chat_id, message_text)
            delivered = "delivered"
        else:
            delivered = "suppressed"

        await db.insert_cron_job_run(
            job["id"], ran_at, "completed", delivered,
            response[:200] if response else None,
            db_path=db_path,
        )
        logger.info("[cron] Job %r completed, delivered=%s", job["name"], delivered)

    except Exception:
        logger.exception("[cron] Job %r failed", job["name"])
        await db.insert_cron_job_run(
            job["id"], ran_at, "error", "suppressed", db_path=db_path
        )


async def run_cron_scheduler(
    *,
    get_token_fn: Callable = chat.get_bot_token,
    build_bot_fn: Callable = chat.build_bot,
    load_config_fn: Callable = config.load_config,
    send_message_fn: Callable = chat.send_message,
    claude: ClaudeClient,
    once: bool = False,
    db_path=None,
    get_timezone_fn: Callable = config.get_timezone,
    get_due_jobs_fn: Callable = db.get_due_cron_jobs,
    update_next_run_fn: Callable = db.update_cron_job_next_run,
    disable_job_fn: Callable = db.disable_cron_job,
    advance_stale_fn: Callable = db.advance_stale_cron_jobs,
    cron_prev_run_fn: Callable = cron_module.cron_prev_run,
) -> None:
    """Runs the cron scheduler loop.

    Polls for due cron jobs every 30 seconds, dispatches them as background
    tasks, and updates their next scheduled run times.

    Args:
        get_token_fn: Returns the Telegram bot token.
        build_bot_fn: Builds a Bot from a token.
        load_config_fn: Returns the current config dict.
        send_message_fn: Sends a message via Telegram.
        claude: A ClaudeClient instance.
        once: If True, run one iteration and return (for testing).
        db_path: Path to the database file.
        get_timezone_fn: Returns the configured timezone string.
        get_due_jobs_fn: Returns due cron jobs from the database.
        update_next_run_fn: Updates the next_run_epoch for a cron job.
        disable_job_fn: Disables a cron job.
        advance_stale_fn: Returns stale cron jobs for normalization.
    """
    token = get_token_fn()
    bot = build_bot_fn(token)
    cfg = load_config_fn()
    chat_id = cfg["chat_id"]
    tz = get_timezone_fn() or None

    logger.info("Cron scheduler started")

    # Startup normalization: advance stale next_run_epoch values
    now = int(time.time())
    cutoff = now - _CRON_CATCH_UP_WINDOW
    stale_jobs = await advance_stale_fn(cutoff, db_path=db_path)
    for job in stale_jobs:
        next_run = cron_module.cron_next_run(job["cron_expr"], now, tz)
        await update_next_run_fn(job["id"], next_run, db_path=db_path)
        logger.info("[cron] Normalized stale job %r → next run at %d", job["name"], next_run)

    while True:
        await asyncio.sleep(30)

        now = int(time.time())
        tz = get_timezone_fn() or None
        due_jobs = await get_due_jobs_fn(now, db_path=db_path)

        for job in due_jobs:
            # Verify the cron expression actually fired within the last poll
            # window. If the previous scheduled time is more than 2× the poll
            # interval ago, the job was inserted with next_run_epoch=unixepoch()
            # (i.e. "now") rather than a real scheduled time — advance it instead
            # of firing immediately.
            _POLL_INTERVAL = 30
            prev_fire = cron_prev_run_fn(job["cron_expr"], now, tz)
            if now - prev_fire > _POLL_INTERVAL * 2:
                # Not a genuine fire window — compute actual next occurrence
                next_run = cron_module.cron_next_run(job["cron_expr"], now, tz)
                await update_next_run_fn(job["id"], next_run, db_path=db_path)
                logger.info(
                    "[cron] Job %r inserted with next_run=now, advanced to %d",
                    job["name"], next_run,
                )
                continue

            # Advance next_run_epoch BEFORE dispatching (prevents double-fire)
            if job["schedule_type"] == "once":
                await disable_job_fn(job["id"], db_path=db_path)
            else:
                next_run = cron_module.cron_next_run(job["cron_expr"], now, tz)
                await update_next_run_fn(job["id"], next_run, db_path=db_path)

            # Dispatch as background task
            task = asyncio.create_task(
                _run_cron_job(
                    job,
                    claude=claude,
                    send_message_fn=send_message_fn,
                    bot=bot,
                    chat_id=chat_id,
                    db_path=db_path,
                )
            )
            _running_cron_tasks.add(task)
            task.add_done_callback(_running_cron_tasks.discard)
            logger.info("[cron] Dispatched job %r", job["name"])

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
    enable_cron: bool = True,
) -> None:
    """Runs message consumer, processor, heartbeat runner, and cron scheduler concurrently.

    This is the main entry point that starts the message consumer
    (polls Telegram), message processor (polls DB, processes via Claude),
    heartbeat runner (periodic check-ins), and cron scheduler (scheduled jobs)
    loops concurrently.

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
        enable_cron: If True, run the cron scheduler (default True).
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
            claude=client,
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

    if enable_cron:
        tasks.append(
            run_cron_scheduler(
                claude=client,
                once=once,
                db_path=db_path,
            )
        )

    await asyncio.gather(*tasks)
