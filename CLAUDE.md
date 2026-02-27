# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

**Corphish** is a daemon-based AI assistant that bridges Google Chat with the Claude Agent SDK. It runs persistently on a server, polling a single Google Chat Space for messages, routing them through Claude, and delivering responses back. It is a single-user, single-space system.

## Architecture

The system is composed of four components that communicate through a shared SQLite database:

### Message Consumer (push-based ingestion)
- Runs `gchat --tail json` as a subprocess and pipes its output into SQLite
- Responsible only for ingestion — writes raw messages to the DB without processing

### Message Processor (polling loop)
- Polls the SQLite database every second for unprocessed messages
- Sends messages to Claude via the Claude Agent SDK
- Writes Claude's response back to SQLite and dispatches it to GChat

### Heartbeat Runner (scheduled check-in)
- Fires every 5 minutes
- Sends a check-in prompt to Claude; only delivers a response to GChat if it is nontrivial
- Provides proactive, unprompted communication from the assistant

### Local Text Command (CLI interface)
- A local CLI tool to send messages to the space and read responses
- Useful for testing and direct interaction without GChat

### Alpha vs Beta
- **Alpha**: The four components above
- **Beta**: Adds a responsive web app with a chat UI

## Key Design Decisions

- **SQLite as the integration bus**: all components read/write through a single SQLite file; this keeps the system simple and avoids a message broker dependency
- **`gchat --tail json`**: the Google Chat CLI is used for GChat access; the Iris consumer wraps it as a subprocess
- **Claude Agent SDK**: used (not the raw Anthropic API) to preserve conversation context across the message processor and heartbeat runner
- **Single-space, single-user**: no multi-tenancy; configuration binds the daemon to one GChat space

## Technology Stack

- **Language**: Python
- **Database**: SQLite (via `sqlite3` stdlib or `aiosqlite`)
- **Claude integration**: `anthropic` SDK with the agent/conversation API
- **GChat integration**: `gchat` CLI tool (invoked as a subprocess)
- **Process management**: launchd (macOS) for the daemon components

## Development Workflow

- **Small changes**: implement one piece of functionality at a time
- **Extensive tests**: every change must have thorough test coverage
- **Always use PRs**: never commit directly to main; open a PR for every change so the user can review before merging
