"""Tests for corphish.chat."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corphish.chat import build_bot, get_bot_token, send_message


def test_get_bot_token_returns_token(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    assert get_bot_token() == "123:abc"


def test_get_bot_token_raises_when_unset(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        get_bot_token()


def test_get_bot_token_raises_when_empty(monkeypatch):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "")
    with pytest.raises(RuntimeError, match="TELEGRAM_BOT_TOKEN"):
        get_bot_token()


def test_build_bot_returns_bot_instance(monkeypatch):
    with patch("corphish.chat.Bot") as mock_bot_cls:
        mock_bot_cls.return_value = MagicMock()
        bot = build_bot("123:abc")
    mock_bot_cls.assert_called_once_with(token="123:abc")
    assert bot is mock_bot_cls.return_value


async def test_send_message_calls_bot(monkeypatch):
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    await send_message(mock_bot, chat_id=42, text="hello")
    mock_bot.send_message.assert_awaited_once_with(chat_id=42, text="hello")


async def test_send_message_empty_text_raises():
    mock_bot = MagicMock()
    with pytest.raises(ValueError, match="text must not be empty"):
        await send_message(mock_bot, chat_id=42, text="")


async def test_send_message_does_not_call_bot_on_empty_text():
    mock_bot = MagicMock()
    mock_bot.send_message = AsyncMock()
    with pytest.raises(ValueError):
        await send_message(mock_bot, chat_id=42, text="")
    mock_bot.send_message.assert_not_awaited()
