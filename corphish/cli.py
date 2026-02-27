"""CLI argument parsing and command dispatch for Corphish."""

import argparse
import asyncio
import logging
import sys
from typing import Callable, Optional

from . import config
from .bootstrap import run_bootstrap
from .chat import build_bot, get_bot_token, send_message
from .daemon import run_daemon

logger = logging.getLogger(__name__)


def build_parser() -> argparse.ArgumentParser:
    """Builds the argparse parser for the corphish CLI.

    Returns:
        Configured ArgumentParser.
    """
    parser = argparse.ArgumentParser(
        prog="corphish",
        description="Corphish — daemon-based AI assistant for Telegram.",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("run", help="Run the daemon loop (default)")
    sub.add_parser("bootstrap", help="Run first-time bootstrap setup")

    send_parser = sub.add_parser("send", help="Send a message to the configured chat")
    send_parser.add_argument("text", nargs="+", help="Message text to send")

    sub.add_parser("status", help="Show current configuration status")

    return parser


async def cmd_send(
    text: str,
    *,
    get_token_fn: Callable = get_bot_token,
    build_bot_fn: Callable = build_bot,
    load_config_fn: Callable = config.load_config,
    send_message_fn: Callable = send_message,
) -> None:
    """Sends a message to the configured Telegram chat.

    Args:
        text: The message text to send.
        get_token_fn: Returns the Telegram bot token.
        build_bot_fn: Builds a Bot from a token.
        load_config_fn: Returns the current config dict.
        send_message_fn: Sends a message via Telegram.

    Raises:
        SystemExit: If not bootstrapped (no chat_id configured).
    """
    cfg = load_config_fn()
    chat_id = cfg.get("chat_id")
    if chat_id is None:
        logger.error(
            "Not bootstrapped yet. Run 'corphish bootstrap' first to configure a chat."
        )
        sys.exit(1)

    token = get_token_fn()
    bot = build_bot_fn(token)
    await send_message_fn(bot, chat_id, text)
    logger.info("Message sent to chat %s", chat_id)


def cmd_status(
    *,
    load_config_fn: Callable = config.load_config,
    get_config_path_fn: Callable = config.get_config_path,
    output_fn: Optional[Callable] = None,
) -> None:
    """Prints configuration status.

    Args:
        load_config_fn: Returns the current config dict.
        get_config_path_fn: Returns the path to config.toml.
        output_fn: Callable for printing output (defaults to logger.info).
    """
    out = output_fn or logger.info
    path = get_config_path_fn()
    cfg = load_config_fn()

    if not path.exists():
        out("Config file: not found (%s)", path)
        out("Status: not bootstrapped")
        return

    out("Config file: %s", path)
    chat_id = cfg.get("chat_id")
    if chat_id is not None:
        out("Chat ID: %s", chat_id)
        out("Status: bootstrapped")
    else:
        out("Chat ID: not set")
        out("Status: not bootstrapped")


async def dispatch(args: argparse.Namespace) -> None:
    """Dispatches to the appropriate command handler.

    Args:
        args: Parsed CLI arguments.
    """
    command = args.command

    if command == "send":
        text = " ".join(args.text)
        await cmd_send(text)
    elif command == "bootstrap":
        await run_bootstrap()
    elif command == "status":
        cmd_status()
    else:
        # Default: run daemon (auto-bootstrap on first run)
        if config.is_first_run():
            await run_bootstrap()
        else:
            await run_daemon()
