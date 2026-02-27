# Corphish

Corphish is a daemon-based AI assistant that bridges Telegram with the Claude Agent SDK. It runs persistently on macOS, polling a single Telegram chat for messages, routing them through Claude, and delivering responses back. Think of it as a personal AI companion that lives in your Telegram — always on, always listening.

## How it works

The daemon has three main components:

- **Message consumer** — uses `python-telegram-bot` polling to receive incoming Telegram messages and hand them off for processing.
- **Message processor** — sends messages to Claude via the Agent SDK and replies with Claude's response. An `asyncio.Lock` ensures one Claude call at a time.
- **Heartbeat runner** — fires every 30 minutes to give Claude a chance to reach out proactively. Skipped if Claude is already busy. Only delivers a response if it has something meaningful to say.

All state lives in a single SQLite file — no message broker, no external services beyond Telegram and the Anthropic API.

### Alpha limitations

This is alpha software. Current constraints:

- **Single-user, single-chat** — the daemon binds to one Telegram chat established during first-run bootstrap. There is no multi-tenancy.
- **macOS only** — process management uses launchd. Other platforms would need a different supervisor.
- **No web UI** — interaction is Telegram-only (a web UI is planned for beta).

## Setup

### Prerequisites

- Python 3.11 or later
- A Telegram bot token (from [@BotFather](https://t.me/BotFather))
- An Anthropic API key (from [console.anthropic.com](https://console.anthropic.com))

### Install

```bash
git clone https://github.com/zhihan/corphish.git
cd corphish
python -m venv .venv
source .venv/bin/activate
pip install -e .
```

### Environment variables

Set these before running:

```bash
export TELEGRAM_BOT_TOKEN="your-telegram-bot-token"
export ANTHROPIC_API_KEY="your-anthropic-api-key"
```

### First run (bootstrap)

Start the daemon for the first time:

```bash
corphish
```

On first run, the bootstrap flow will:

1. Verify that `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY` are set.
2. Wait for you to send the first message to your bot in Telegram — this establishes the `chat_id`.
3. Save the `chat_id` to `~/.config/corphish/config.toml`.
4. Send a greeting back in the chat.
5. Install and load a launchd plist (`~/Library/LaunchAgents/com.corphish.daemon.plist`) so the daemon starts automatically at login and restarts if it exits.

After bootstrap completes, the daemon is running and managed by launchd. You don't need to start it manually again.

## CLI commands

Corphish provides a set of subcommands for interacting with the daemon and Telegram:

```bash
# Run the daemon loop (default behavior when no command is given)
corphish run

# Run first-time bootstrap setup explicitly
corphish bootstrap

# Send a message to Claude and print the response (local chat, no Telegram)
corphish send Hello from the CLI!

# Check configuration status (config path, chat_id, bootstrap state)
corphish status
```

`corphish send` is a local chat — it sends your message directly to Claude via the API and prints the response to stdout. It does not go through Telegram. Requires `ANTHROPIC_API_KEY` to be set.

Running `corphish` with no subcommand is equivalent to `corphish run` — it auto-bootstraps on first run.

### Running thereafter

The daemon starts automatically at login via launchd. To manage it manually:

```bash
# Stop
launchctl unload ~/Library/LaunchAgents/com.corphish.daemon.plist

# Start
launchctl load ~/Library/LaunchAgents/com.corphish.daemon.plist
```

### Logs

Logs are written to `~/.config/corphish/`:

- `corphish.log` — standard output
- `corphish.error.log` — standard error (includes all application logging)

## Security

- **Never paste API keys or tokens into the Telegram chat.** The bot token and API key are read from environment variables only.
- **Environment variables are embedded in the launchd plist** at bootstrap time. The plist file is stored in `~/Library/LaunchAgents/` with your user's default permissions.
- **If a secret is leaked**, rotate it immediately: generate a new bot token via @BotFather, generate a new API key via the Anthropic console, then re-run bootstrap or update the plist manually.

## Development

Install dev dependencies:

```bash
pip install -e ".[dev]"
```

Run tests:

```bash
pytest
```
