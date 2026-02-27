"""CLI argument parsing and command dispatch for Corphish."""

import argparse
import asyncio
import logging
import os
import sys
from typing import Callable, Optional

from . import config
from .bootstrap import run_bootstrap
from .chat import build_bot, get_bot_token, send_message
from .claude_client import ClaudeClient
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

    send_parser = sub.add_parser(
        "send", help="Send a Telegram message to the configured chat"
    )
    send_parser.add_argument("text", nargs="+", help="Message text to send")

    run_once_parser = sub.add_parser(
        "run_once", help="Send a message to Claude and print the response"
    )
    run_once_parser.add_argument("text", nargs="+", help="Message text to send")

    sub.add_parser("status", help="Show current configuration status")

    return parser


async def cmd_send(
    text: str,
    *,
    load_config_fn: Callable = config.load_config,
    get_bot_token_fn: Callable = get_bot_token,
    build_bot_fn: Callable = build_bot,
    send_message_fn: Callable = send_message,
) -> None:
    """Sends a Telegram message to the configured chat.

    Args:
        text: The message text to send.
        load_config_fn: Returns the current config dict.
        get_bot_token_fn: Returns the Telegram bot token.
        build_bot_fn: Creates a Bot from a token.
        send_message_fn: Sends a message via a Bot.

    Raises:
        SystemExit: If TELEGRAM_BOT_TOKEN is not set or chat_id is not
            configured.
    """
    cfg = load_config_fn()
    chat_id = cfg.get("chat_id")
    if chat_id is None:
        logger.error("chat_id is not configured. Run bootstrap first.")
        sys.exit(1)

    try:
        token = get_bot_token_fn()
    except RuntimeError as exc:
        logger.error("%s", exc)
        sys.exit(1)

    bot = build_bot_fn(token)
    await send_message_fn(bot, chat_id, text)
    logger.info("Message sent to chat %s.", chat_id)


async def cmd_run_once(
    text: str,
    *,
    client_factory: Optional[Callable[[], ClaudeClient]] = None,
) -> str:
    """Sends a message to Claude and returns the response.

    Args:
        text: The message text to send.
        client_factory: Callable that returns a ClaudeClient instance.
            Defaults to creating a new ClaudeClient (reads ANTHROPIC_API_KEY
            from the environment).

    Returns:
        Claude's response text.

    Raises:
        SystemExit: If ANTHROPIC_API_KEY is not set.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        logger.error("ANTHROPIC_API_KEY is not set in the environment.")
        sys.exit(1)

    factory = client_factory or ClaudeClient
    client = factory()
    response = await client.send(text)
    return response


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
    elif command == "run_once":
        text = " ".join(args.text)
        response = await cmd_run_once(text)
        print(response)
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
