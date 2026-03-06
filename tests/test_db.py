"""Tests for corphish.db."""

import asyncio
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from corphish.db import (
    get_db_path,
    get_next_unprocessed_message,
    get_unsent_outgoing_messages,
    init_db,
    insert_incoming_message,
    insert_outgoing_message,
    mark_message_processed,
    mark_outgoing_message_sent,
)


@pytest.fixture
async def temp_db(tmp_path):
    """Creates a temporary database for testing."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    return db_path


def test_get_db_path_uses_config_dir():
    """get_db_path() should return path in config directory."""
    with patch("corphish.db.config.get_config_dir") as mock_get_dir:
        mock_get_dir.return_value = Path("/tmp/corphish")
        path = get_db_path()
        assert path == Path("/tmp/corphish/corphish.db")


async def test_init_db_creates_schema(tmp_path):
    """init_db() should create the schema_version and messages tables."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)

    import aiosqlite

    async with aiosqlite.connect(db_path) as db:
        # Check schema_version table
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_version'"
        )
        row = await cursor.fetchone()
        assert row is not None

        # Check messages table
        cursor = await db.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='messages'"
        )
        row = await cursor.fetchone()
        assert row is not None


async def test_init_db_idempotent(tmp_path):
    """init_db() should be safe to call multiple times."""
    db_path = tmp_path / "test.db"
    await init_db(db_path)
    await init_db(db_path)  # Should not raise


async def test_insert_incoming_message(temp_db):
    """insert_incoming_message() should add a message to the database."""
    message_id = await insert_incoming_message(
        text="Hello",
        telegram_update_id=123,
        telegram_message_id=456,
        db_path=temp_db,
    )

    assert message_id > 0

    import aiosqlite

    async with aiosqlite.connect(temp_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row["direction"] == "incoming"
        assert row["text"] == "Hello"
        assert row["telegram_update_id"] == 123
        assert row["telegram_message_id"] == 456
        assert row["processed"] == 0


async def test_insert_outgoing_message(temp_db):
    """insert_outgoing_message() should add an outgoing message."""
    message_id = await insert_outgoing_message(
        text="World",
        db_path=temp_db,
    )

    assert message_id > 0

    import aiosqlite

    async with aiosqlite.connect(temp_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = await cursor.fetchone()
        assert row is not None
        assert row["direction"] == "outgoing"
        assert row["text"] == "World"
        assert row["telegram_update_id"] is None
        assert row["processed"] == 0


async def test_get_next_unprocessed_message_empty(temp_db):
    """get_next_unprocessed_message() returns None when no messages exist."""
    message = await get_next_unprocessed_message(db_path=temp_db)
    assert message is None


async def test_get_next_unprocessed_message_returns_oldest(temp_db):
    """get_next_unprocessed_message() should return the oldest unprocessed message."""
    # Insert multiple messages
    id1 = await insert_incoming_message("First", 1, 10, db_path=temp_db)
    await asyncio.sleep(0.01)  # Ensure different timestamps
    id2 = await insert_incoming_message("Second", 2, 20, db_path=temp_db)

    message = await get_next_unprocessed_message(db_path=temp_db)

    assert message is not None
    assert message["id"] == id1
    assert message["text"] == "First"
    assert message["telegram_update_id"] == 1
    assert message["telegram_message_id"] == 10


async def test_get_next_unprocessed_message_skips_processed(temp_db):
    """get_next_unprocessed_message() should skip processed messages."""
    id1 = await insert_incoming_message("First", 1, 10, db_path=temp_db)
    await mark_message_processed(id1, db_path=temp_db)
    await asyncio.sleep(0.01)
    id2 = await insert_incoming_message("Second", 2, 20, db_path=temp_db)

    message = await get_next_unprocessed_message(db_path=temp_db)

    assert message is not None
    assert message["id"] == id2
    assert message["text"] == "Second"


async def test_get_next_unprocessed_message_ignores_outgoing(temp_db):
    """get_next_unprocessed_message() should ignore outgoing messages."""
    await insert_outgoing_message("Outgoing", db_path=temp_db)

    message = await get_next_unprocessed_message(db_path=temp_db)

    assert message is None


async def test_mark_message_processed(temp_db):
    """mark_message_processed() should mark a message as processed."""
    message_id = await insert_incoming_message("Test", 1, 10, db_path=temp_db)

    await mark_message_processed(message_id, db_path=temp_db)

    import aiosqlite

    async with aiosqlite.connect(temp_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = await cursor.fetchone()
        assert row["processed"] == 1
        assert row["processed_at"] is not None


async def test_get_unsent_outgoing_messages_empty(temp_db):
    """get_unsent_outgoing_messages() returns empty list when no messages exist."""
    messages = await get_unsent_outgoing_messages(db_path=temp_db)
    assert messages == []


async def test_get_unsent_outgoing_messages_returns_all(temp_db):
    """get_unsent_outgoing_messages() should return all unsent outgoing messages."""
    id1 = await insert_outgoing_message("First", db_path=temp_db)
    await asyncio.sleep(0.01)
    id2 = await insert_outgoing_message("Second", db_path=temp_db)

    messages = await get_unsent_outgoing_messages(db_path=temp_db)

    assert len(messages) == 2
    assert messages[0]["id"] == id1
    assert messages[0]["text"] == "First"
    assert messages[1]["id"] == id2
    assert messages[1]["text"] == "Second"


async def test_get_unsent_outgoing_messages_skips_sent(temp_db):
    """get_unsent_outgoing_messages() should skip sent messages."""
    id1 = await insert_outgoing_message("First", db_path=temp_db)
    await mark_outgoing_message_sent(id1, 123, db_path=temp_db)
    await asyncio.sleep(0.01)
    id2 = await insert_outgoing_message("Second", db_path=temp_db)

    messages = await get_unsent_outgoing_messages(db_path=temp_db)

    assert len(messages) == 1
    assert messages[0]["id"] == id2


async def test_get_unsent_outgoing_messages_ignores_incoming(temp_db):
    """get_unsent_outgoing_messages() should ignore incoming messages."""
    await insert_incoming_message("Incoming", 1, 10, db_path=temp_db)

    messages = await get_unsent_outgoing_messages(db_path=temp_db)

    assert messages == []


async def test_mark_outgoing_message_sent(temp_db):
    """mark_outgoing_message_sent() should mark message as sent and store telegram_message_id."""
    message_id = await insert_outgoing_message("Test", db_path=temp_db)

    await mark_outgoing_message_sent(message_id, 999, db_path=temp_db)

    import aiosqlite

    async with aiosqlite.connect(temp_db) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM messages WHERE id = ?", (message_id,))
        row = await cursor.fetchone()
        assert row["processed"] == 1
        assert row["processed_at"] is not None
        assert row["telegram_message_id"] == 999
