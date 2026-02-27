"""First-run bootstrap orchestration."""

import asyncio
import os
import subprocess
import sys
from pathlib import Path
from typing import Callable, Optional

from telegram import Bot

from . import chat, config

GREETING = (
    "Hello! I'm Corphish, your personal AI assistant. "
    "I'm set up and running. Send me a message to get started."
)

_PLIST_LABEL = "com.corphish.daemon"

_PLIST_TEMPLATE = """\
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"
    "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>{label}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{python}</string>
        <string>-m</string>
        <string>corphish</string>
    </array>
    <key>EnvironmentVariables</key>
    <dict>
        <key>TELEGRAM_BOT_TOKEN</key>
        <string>{bot_token}</string>
        <key>ANTHROPIC_API_KEY</key>
        <string>{anthropic_key}</string>
    </dict>
    <key>KeepAlive</key>
    <true/>
    <key>RunAtLoad</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{log_dir}/corphish.log</string>
    <key>StandardErrorPath</key>
    <string>{log_dir}/corphish.error.log</string>
</dict>
</plist>
"""


def _check_anthropic_key() -> None:
    """Verifies ANTHROPIC_API_KEY is set in the environment.

    Raises:
        RuntimeError: If ANTHROPIC_API_KEY is not set or empty.
    """
    if not os.environ.get("ANTHROPIC_API_KEY"):
        raise RuntimeError(
            "ANTHROPIC_API_KEY environment variable is not set.\n"
            "Get your API key from https://console.anthropic.com"
        )


async def _wait_for_first_message(bot: Bot) -> int:
    """Polls Telegram until a message arrives and returns the chat_id.

    Args:
        bot: The Telegram Bot instance.

    Returns:
        The chat_id of the first message received.
    """
    print("Send any message to your bot in Telegram to continue setup...")
    while True:
        updates = await bot.get_updates(timeout=10)
        for update in updates:
            if update.message:
                return update.message.chat.id
        await asyncio.sleep(1)


def _install_launchd() -> None:
    """Writes and loads the launchd plist for automatic daemon startup.

    Embeds TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY into the plist so the
    daemon has them available without relying on shell environment inheritance.
    """
    plist_content = _PLIST_TEMPLATE.format(
        label=_PLIST_LABEL,
        python=sys.executable,
        bot_token=os.environ["TELEGRAM_BOT_TOKEN"],
        anthropic_key=os.environ["ANTHROPIC_API_KEY"],
        log_dir=str(config.get_config_dir()),
    )

    launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
    launch_agents_dir.mkdir(parents=True, exist_ok=True)
    plist_path = launch_agents_dir / f"{_PLIST_LABEL}.plist"
    plist_path.write_text(plist_content)
    print(f"Installed launchd plist at {plist_path}")

    result = subprocess.run(
        ["launchctl", "load", str(plist_path)],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"Warning: launchctl load failed: {result.stderr}", file=sys.stderr)
    else:
        print("Daemon registered with launchd.")


async def run_bootstrap(
    *,
    get_token_fn: Callable = chat.get_bot_token,
    build_bot_fn: Callable = chat.build_bot,
    wait_for_message_fn: Callable = _wait_for_first_message,
    send_message_fn: Callable = chat.send_message,
    save_config_fn: Callable = config.save_config,
    install_launchd_fn: Optional[Callable] = None,
) -> None:
    """Runs the first-run bootstrap flow.

    Phases:
      1. Verify TELEGRAM_BOT_TOKEN and ANTHROPIC_API_KEY are set
      2. Wait for the user's first Telegram message (establishes chat_id)
      3. Save chat_id to config
      4. Send greeting
      5. Install and load the launchd plist

    All dependencies are injectable for testing.

    Args:
        get_token_fn: Callable returning the Telegram bot token.
        build_bot_fn: Callable(token) returning a Bot instance.
        wait_for_message_fn: Async callable(bot) returning a chat_id int.
        send_message_fn: Async callable(bot, chat_id, text) sending a message.
        save_config_fn: Callable(data) persisting config.
        install_launchd_fn: Callable() installing the launchd plist. Defaults
            to the real implementation.

    Raises:
        RuntimeError: If required environment variables are missing.
    """
    print("Starting Corphish first-run setup...")

    # Phase 1: Verify env vars.
    token = get_token_fn()
    _check_anthropic_key()

    # Phase 2: Wait for first message to get chat_id.
    bot = build_bot_fn(token)
    chat_id = await wait_for_message_fn(bot)

    # Phase 3: Persist chat_id.
    save_config_fn({"chat_id": chat_id})
    print(f"✓ Chat ID saved: {chat_id}")

    # Phase 4: Send greeting.
    await send_message_fn(bot, chat_id, GREETING)
    print("✓ Greeting sent")

    # Phase 5: Install launchd.
    install_fn = install_launchd_fn or _install_launchd
    install_fn()

    print("Bootstrap complete.")
