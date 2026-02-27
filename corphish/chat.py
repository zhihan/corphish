"""Telegram bot operations."""

import os

from telegram import Bot


def get_bot_token() -> str:
    """Returns the Telegram bot token from the environment.

    Returns:
        The bot token string.

    Raises:
        RuntimeError: If TELEGRAM_BOT_TOKEN is not set or empty.
    """
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN environment variable is not set.\n"
            "Create a bot via @BotFather in Telegram and set the token."
        )
    return token


def build_bot(token: str) -> Bot:
    """Creates a Telegram Bot instance.

    Args:
        token: The bot token obtained from @BotFather.

    Returns:
        A telegram.Bot instance.
    """
    return Bot(token=token)


async def send_message(bot: Bot, chat_id: int, text: str) -> None:
    """Sends a text message to a Telegram chat.

    Args:
        bot: The Telegram Bot instance.
        chat_id: The target chat ID.
        text: The message text to send.

    Raises:
        ValueError: If text is empty.
    """
    if not text:
        raise ValueError("text must not be empty")
    await bot.send_message(chat_id=chat_id, text=text)
