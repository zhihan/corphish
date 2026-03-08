"""Database layer for Corphish — SQLite integration bus.

All system components (message consumer, processor, heartbeat) communicate
through a shared SQLite database. This module provides the async interface
for message persistence and retrieval.
"""

import asyncio
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import aiosqlite

from . import config

logger = logging.getLogger(__name__)

# Schema version for migrations
SCHEMA_VERSION = 2


def get_db_path() -> Path:
    """Returns the path to the SQLite database file.

    Returns:
        Path to corphish.db in the config directory.
    """
    return config.get_config_dir() / "corphish.db"


async def init_db(db_path: Optional[Path] = None) -> None:
    """Initializes the database schema if not already present.

    Creates the messages table and schema_version table.

    Args:
        db_path: Path to the database file. Defaults to get_db_path().
    """
    path = db_path or get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(path) as db:
        # Create schema_version table
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS schema_version (
                version INTEGER PRIMARY KEY,
                applied_at TEXT NOT NULL
            )
            """
        )

        # Check current schema version
        cursor = await db.execute("SELECT version FROM schema_version ORDER BY version DESC LIMIT 1")
        row = await cursor.fetchone()
        current_version = row[0] if row else 0

        # Apply migrations incrementally
        if current_version < 1:
            logger.info("Applying database schema version 1")

            # Create messages table
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    direction TEXT NOT NULL CHECK(direction IN ('incoming', 'outgoing')),
                    telegram_update_id INTEGER,
                    telegram_message_id INTEGER,
                    text TEXT NOT NULL,
                    processed BOOLEAN NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    processed_at TEXT
                )
                """
            )

            # Create indices for common queries
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_processed ON messages(processed, created_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_messages_direction ON messages(direction, created_at)"
            )

            # Record schema version
            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (1, datetime.now(timezone.utc).isoformat()),
            )

            await db.commit()
            logger.info("Database schema version 1 applied")

        if current_version < 2:
            logger.info("Applying database schema version 2 (model usage tracking)")

            # Create model_usage table for cost tracking
            await db.execute(
                """
                CREATE TABLE IF NOT EXISTS model_usage (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    model TEXT NOT NULL,
                    source TEXT NOT NULL,
                    escalated BOOLEAN NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL
                )
                """
            )

            # Create index for querying usage by model and source
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_usage_model ON model_usage(model, created_at)"
            )
            await db.execute(
                "CREATE INDEX IF NOT EXISTS idx_model_usage_source ON model_usage(source, created_at)"
            )

            # Record schema version
            await db.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
                (2, datetime.now(timezone.utc).isoformat()),
            )

            await db.commit()
            logger.info("Database schema version 2 applied")


async def insert_incoming_message(
    text: str,
    telegram_update_id: int,
    telegram_message_id: int,
    db_path: Optional[Path] = None,
) -> int:
    """Inserts an incoming message from Telegram into the database.

    Args:
        text: The message text.
        telegram_update_id: The Telegram update ID.
        telegram_message_id: The Telegram message ID.
        db_path: Path to the database file. Defaults to get_db_path().

    Returns:
        The database ID of the inserted message.
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        cursor = await db.execute(
            """
            INSERT INTO messages (direction, telegram_update_id, telegram_message_id, text, created_at)
            VALUES (?, ?, ?, ?, ?)
            """,
            (
                "incoming",
                telegram_update_id,
                telegram_message_id,
                text,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def insert_outgoing_message(
    text: str,
    db_path: Optional[Path] = None,
) -> int:
    """Inserts an outgoing message (to be sent to Telegram) into the database.

    Args:
        text: The message text.
        db_path: Path to the database file. Defaults to get_db_path().

    Returns:
        The database ID of the inserted message.
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        cursor = await db.execute(
            """
            INSERT INTO messages (direction, text, created_at)
            VALUES (?, ?, ?)
            """,
            (
                "outgoing",
                text,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def get_next_unprocessed_message(
    db_path: Optional[Path] = None,
) -> Optional[dict]:
    """Retrieves the next unprocessed incoming message.

    Returns the oldest unprocessed message by created_at.

    Args:
        db_path: Path to the database file. Defaults to get_db_path().

    Returns:
        A dict with keys: id, text, telegram_update_id, telegram_message_id, created_at
        Returns None if no unprocessed messages exist.
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, text, telegram_update_id, telegram_message_id, created_at
            FROM messages
            WHERE direction = 'incoming' AND processed = 0
            ORDER BY created_at ASC
            LIMIT 1
            """
        )
        row = await cursor.fetchone()
        return dict(row) if row else None


async def mark_message_processed(
    message_id: int,
    db_path: Optional[Path] = None,
) -> None:
    """Marks a message as processed.

    Args:
        message_id: The database ID of the message.
        db_path: Path to the database file. Defaults to get_db_path().
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """
            UPDATE messages
            SET processed = 1, processed_at = ?
            WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), message_id),
        )
        await db.commit()


async def get_unsent_outgoing_messages(
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Retrieves all outgoing messages that haven't been sent yet.

    Returns messages ordered by created_at.

    Args:
        db_path: Path to the database file. Defaults to get_db_path().

    Returns:
        A list of dicts with keys: id, text, created_at
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, text, created_at
            FROM messages
            WHERE direction = 'outgoing' AND processed = 0
            ORDER BY created_at ASC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_latest_outgoing_id(
    db_path: Optional[Path] = None,
) -> int:
    """Returns the ID of the most recent outgoing message, or 0 if none.

    Args:
        db_path: Path to the database file. Defaults to get_db_path().

    Returns:
        The maximum outgoing message ID, or 0 if the table is empty.
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        cursor = await db.execute(
            "SELECT MAX(id) FROM messages WHERE direction = 'outgoing'"
        )
        row = await cursor.fetchone()
        return row[0] if row and row[0] is not None else 0


async def get_outgoing_messages_after(
    after_id: int,
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Returns outgoing messages with id > after_id, ordered by id.

    Args:
        after_id: Only return messages with id strictly greater than this.
        db_path: Path to the database file. Defaults to get_db_path().

    Returns:
        A list of dicts with keys: id, text, created_at
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT id, text, created_at
            FROM messages
            WHERE direction = 'outgoing' AND id > ?
            ORDER BY id ASC
            """,
            (after_id,),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def mark_outgoing_message_sent(
    message_id: int,
    telegram_message_id: int,
    db_path: Optional[Path] = None,
) -> None:
    """Marks an outgoing message as sent via Telegram.

    Args:
        message_id: The database ID of the message.
        telegram_message_id: The Telegram message ID after sending.
        db_path: Path to the database file. Defaults to get_db_path().
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        await db.execute(
            """
            UPDATE messages
            SET processed = 1, processed_at = ?, telegram_message_id = ?
            WHERE id = ?
            """,
            (datetime.now(timezone.utc).isoformat(), telegram_message_id, message_id),
        )
        await db.commit()


async def log_model_usage(
    model: str,
    source: str,
    escalated: bool = False,
    db_path: Optional[Path] = None,
) -> int:
    """Logs a model usage event for cost tracking.

    Args:
        model: The model ID used (e.g., "claude-haiku-4-5-20251001").
        source: The component that used the model (e.g., "heartbeat", "processor").
        escalated: Whether this was an escalation from a cheaper model.
        db_path: Path to the database file. Defaults to get_db_path().

    Returns:
        The database ID of the inserted usage record.
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        cursor = await db.execute(
            """
            INSERT INTO model_usage (model, source, escalated, created_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                model,
                source,
                1 if escalated else 0,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        await db.commit()
        return cursor.lastrowid


async def get_model_usage_summary(
    db_path: Optional[Path] = None,
) -> list[dict]:
    """Returns a summary of model usage grouped by model and source.

    Args:
        db_path: Path to the database file. Defaults to get_db_path().

    Returns:
        A list of dicts with keys: model, source, count, escalated_count
    """
    path = db_path or get_db_path()
    async with aiosqlite.connect(path) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT model, source, COUNT(*) as count, SUM(escalated) as escalated_count
            FROM model_usage
            GROUP BY model, source
            ORDER BY count DESC
            """
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]
