# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Corphish** is a daemon-based AI assistant that bridges Telegram with the Claude Agent SDK. It runs persistently on a server, polling a single Telegram chat for messages, routing them through Claude, and delivering responses back. It is a single-user, single-chat system.

## Architecture

The system is composed of four components that communicate through a shared SQLite database:

### Message Consumer (push-based ingestion)
- Uses `python-telegram-bot` polling to receive messages from Telegram
- Responsible only for ingestion — writes raw messages to the DB without processing

### Message Processor (polling loop)
- Polls the SQLite database every second for unprocessed messages
- Sends messages to Claude via the Claude Agent SDK
- Writes Claude's response back to SQLite and dispatches it via Telegram

### Heartbeat Runner (scheduled check-in)
- Fires every 30 minutes by default (configurable in config.toml)
- Sends a check-in prompt to Claude; only delivers a response if nontrivial
- Skipped if Claude is currently busy processing a message
- Provides proactive, unprompted communication from the assistant

### Local Text Command (CLI interface)
- A local CLI tool to send messages and read responses
- Useful for testing and direct interaction without Telegram

### Alpha vs Beta
- **Alpha**: The four components above
- **Beta**: Adds a responsive web app with a chat UI

## Key Design Decisions

- **SQLite as the integration bus**: all components read/write through a single SQLite file; this keeps the system simple and avoids a message broker dependency
- **`python-telegram-bot`**: used for all Telegram interaction (sending and receiving messages)
- **Claude Agent SDK**: used (not the raw Anthropic API) to preserve conversation context across the message processor and heartbeat runner
- **`asyncio` throughout**: all components are async; a shared `asyncio.Lock` serialises Claude calls so the heartbeat is skipped when Claude is busy
- **Single-chat, single-user**: no multi-tenancy; configuration binds the daemon to one Telegram chat
- **Bot token via environment**: `TELEGRAM_BOT_TOKEN` is read from the environment, never stored in config files
- **Anthropic API key via environment**: `ANTHROPIC_API_KEY` is read from the environment

## Bootstrap Flow

On first run, the daemon:
1. Verifies `TELEGRAM_BOT_TOKEN` and `ANTHROPIC_API_KEY` are set in the environment
2. Waits for the user to send the first message to the bot (this establishes the `chat_id`)
3. Saves `chat_id` to `config.toml`
4. Sends a greeting
5. Installs and loads the launchd plist so the daemon restarts automatically

## Technology Stack

- **Language**: Python 3.11+
- **Database**: SQLite (via `sqlite3` stdlib or `aiosqlite`)
- **Claude integration**: `anthropic` SDK with the agent/conversation API
- **Telegram integration**: `python-telegram-bot` library
- **Process management**: launchd (macOS) for the daemon components

## Development Workflow

- **Small changes**: implement one piece of functionality at a time
- **Extensive tests**: every change must have thorough test coverage
- **Always use PRs**: never commit directly to main; open a PR for every change so the user can review before merging
