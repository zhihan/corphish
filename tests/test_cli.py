"""Tests for corphish.cli."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corphish.cli import (
    build_parser,
    cmd_join,
    cmd_run_once,
    cmd_send,
    cmd_skip_updates,
    cmd_status,
    dispatch,
)


# --- Parser tests ---


class TestBuildParser:
    def test_run_command(self):
        parser = build_parser()
        args = parser.parse_args(["run"])
        assert args.command == "run"

    def test_bootstrap_command(self):
        parser = build_parser()
        args = parser.parse_args(["bootstrap"])
        assert args.command == "bootstrap"

    def test_send_command_single_word(self):
        parser = build_parser()
        args = parser.parse_args(["send", "hello"])
        assert args.command == "send"
        assert args.text == ["hello"]

    def test_send_command_multiple_words(self):
        parser = build_parser()
        args = parser.parse_args(["send", "hello", "world"])
        assert args.command == "send"
        assert args.text == ["hello", "world"]

    def test_send_command_requires_text(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["send"])

    def test_run_once_command_single_word(self):
        parser = build_parser()
        args = parser.parse_args(["run_once", "hello"])
        assert args.command == "run_once"
        assert args.text == ["hello"]

    def test_run_once_command_multiple_words(self):
        parser = build_parser()
        args = parser.parse_args(["run_once", "hello", "world"])
        assert args.command == "run_once"
        assert args.text == ["hello", "world"]

    def test_run_once_command_requires_text(self):
        parser = build_parser()
        with pytest.raises(SystemExit):
            parser.parse_args(["run_once"])

    def test_status_command(self):
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_no_command_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None


# --- cmd_send tests (Telegram) ---


class TestCmdSend:
    async def test_send_delivers_to_telegram(self, monkeypatch):
        monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "fake-token")
        mock_bot = MagicMock()
        mock_send = AsyncMock()

        await cmd_send(
            "hello world",
            load_config_fn=lambda: {"chat_id": 42},
            get_bot_token_fn=lambda: "fake-token",
            build_bot_fn=lambda token: mock_bot,
            send_message_fn=mock_send,
        )

        mock_send.assert_awaited_once_with(mock_bot, 42, "hello world")

    async def test_send_exits_if_no_chat_id(self):
        with pytest.raises(SystemExit) as exc_info:
            await cmd_send(
                "hello",
                load_config_fn=lambda: {},
                get_bot_token_fn=lambda: "fake-token",
                build_bot_fn=lambda token: MagicMock(),
                send_message_fn=AsyncMock(),
            )
        assert exc_info.value.code == 1

    async def test_send_exits_if_no_bot_token(self):
        def raise_runtime():
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

        with pytest.raises(SystemExit) as exc_info:
            await cmd_send(
                "hello",
                load_config_fn=lambda: {"chat_id": 42},
                get_bot_token_fn=raise_runtime,
                build_bot_fn=lambda token: MagicMock(),
                send_message_fn=AsyncMock(),
            )
        assert exc_info.value.code == 1

    async def test_send_does_not_call_telegram_if_no_chat_id(self):
        mock_send = AsyncMock()
        with pytest.raises(SystemExit):
            await cmd_send(
                "hello",
                load_config_fn=lambda: {},
                get_bot_token_fn=lambda: "fake-token",
                build_bot_fn=lambda token: MagicMock(),
                send_message_fn=mock_send,
            )
        mock_send.assert_not_awaited()


# --- cmd_run_once tests (Claude) ---


class TestCmdRunOnce:
    async def test_run_once_returns_claude_response(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        mock_client = AsyncMock()
        mock_client.send.return_value = "Hello from Claude!"

        result = await cmd_run_once(
            "hello world",
            client_factory=lambda: mock_client,
        )

        mock_client.send.assert_awaited_once_with("hello world")
        assert result == "Hello from Claude!"

    async def test_run_once_exits_if_no_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        with pytest.raises(SystemExit) as exc_info:
            await cmd_run_once("hello", client_factory=lambda: AsyncMock())
        assert exc_info.value.code == 1

    async def test_run_once_does_not_call_claude_if_no_api_key(self, monkeypatch):
        monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
        mock_client = AsyncMock()
        with pytest.raises(SystemExit):
            await cmd_run_once("hello", client_factory=lambda: mock_client)
        mock_client.send.assert_not_awaited()

    async def test_run_once_passes_text_to_client(self, monkeypatch):
        monkeypatch.setenv("ANTHROPIC_API_KEY", "fake-key")
        mock_client = AsyncMock()
        mock_client.send.return_value = "response"

        await cmd_run_once(
            "multi word message", client_factory=lambda: mock_client
        )

        mock_client.send.assert_awaited_once_with("multi word message")


# --- cmd_status tests ---


class TestCmdStatus:
    def test_status_bootstrapped(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.touch()

        lines = []

        def capture(msg, *a):
            lines.append(msg % a)

        cmd_status(
            load_config_fn=lambda: {"chat_id": 42},
            get_config_path_fn=lambda: config_path,
            output_fn=capture,
        )

        assert any("42" in line for line in lines)
        assert any("bootstrapped" in line for line in lines)

    def test_status_not_bootstrapped_no_file(self, tmp_path):
        config_path = tmp_path / "config.toml"

        lines = []

        def capture(msg, *a):
            lines.append(msg % a)

        cmd_status(
            load_config_fn=lambda: {},
            get_config_path_fn=lambda: config_path,
            output_fn=capture,
        )

        assert any("not found" in line for line in lines)
        assert any("not bootstrapped" in line for line in lines)

    def test_status_file_exists_but_no_chat_id(self, tmp_path):
        config_path = tmp_path / "config.toml"
        config_path.touch()

        lines = []

        def capture(msg, *a):
            lines.append(msg % a)

        cmd_status(
            load_config_fn=lambda: {},
            get_config_path_fn=lambda: config_path,
            output_fn=capture,
        )

        assert any("not set" in line for line in lines)
        assert any("not bootstrapped" in line for line in lines)


# --- dispatch tests ---


class TestDispatch:
    async def test_dispatch_send_calls_telegram(self):
        parser = build_parser()
        args = parser.parse_args(["send", "hi", "there"])

        with patch(
            "corphish.cli.cmd_send", new_callable=AsyncMock
        ) as mock_send:
            await dispatch(args)
            mock_send.assert_awaited_once_with("hi there")

    async def test_dispatch_run_once_prints_response(self, capsys):
        parser = build_parser()
        args = parser.parse_args(["run_once", "hi", "there"])

        with patch(
            "corphish.cli.cmd_run_once", new_callable=AsyncMock
        ) as mock_run_once:
            mock_run_once.return_value = "Claude says hello"
            await dispatch(args)
            mock_run_once.assert_awaited_once_with("hi there")

        captured = capsys.readouterr()
        assert "Claude says hello" in captured.out

    async def test_dispatch_bootstrap(self):
        parser = build_parser()
        args = parser.parse_args(["bootstrap"])

        with patch(
            "corphish.cli.run_bootstrap", new_callable=AsyncMock
        ) as mock_boot:
            await dispatch(args)
            mock_boot.assert_awaited_once()

    async def test_dispatch_status(self):
        parser = build_parser()
        args = parser.parse_args(["status"])

        with patch("corphish.cli.cmd_status") as mock_status:
            await dispatch(args)
            mock_status.assert_called_once()

    async def test_dispatch_run_explicit(self):
        parser = build_parser()
        args = parser.parse_args(["run"])

        with (
            patch("corphish.cli.config") as mock_config,
            patch("corphish.cli.run_daemon", new_callable=AsyncMock) as mock_daemon,
            patch(
                "corphish.cli.run_bootstrap", new_callable=AsyncMock
            ) as mock_boot,
        ):
            mock_config.is_first_run.return_value = False
            await dispatch(args)
            mock_daemon.assert_awaited_once()
            mock_boot.assert_not_awaited()

    async def test_dispatch_default_no_command(self):
        parser = build_parser()
        args = parser.parse_args([])

        with (
            patch("corphish.cli.config") as mock_config,
            patch("corphish.cli.run_daemon", new_callable=AsyncMock) as mock_daemon,
            patch(
                "corphish.cli.run_bootstrap", new_callable=AsyncMock
            ) as mock_boot,
        ):
            mock_config.is_first_run.return_value = False
            await dispatch(args)
            mock_daemon.assert_awaited_once()

    async def test_dispatch_default_first_run(self):
        parser = build_parser()
        args = parser.parse_args([])

        with (
            patch("corphish.cli.config") as mock_config,
            patch("corphish.cli.run_daemon", new_callable=AsyncMock) as mock_daemon,
            patch(
                "corphish.cli.run_bootstrap", new_callable=AsyncMock
            ) as mock_boot,
        ):
            mock_config.is_first_run.return_value = True
            await dispatch(args)
            mock_boot.assert_awaited_once()
            mock_daemon.assert_not_awaited()

    async def test_dispatch_skip_updates(self):
        parser = build_parser()
        args = parser.parse_args(["skip-updates"])

        with patch(
            "corphish.cli.cmd_skip_updates", new_callable=AsyncMock
        ) as mock_skip:
            await dispatch(args)
            mock_skip.assert_awaited_once()

    async def test_dispatch_join(self):
        parser = build_parser()
        args = parser.parse_args(["join"])

        with patch("corphish.cli.cmd_join", new_callable=AsyncMock) as mock_join:
            await dispatch(args)
            mock_join.assert_awaited_once()


# --- Parser: skip-updates ---


class TestBuildParserSkipUpdates:
    def test_skip_updates_command(self):
        parser = build_parser()
        args = parser.parse_args(["skip-updates"])
        assert args.command == "skip-updates"

    def test_join_command(self):
        parser = build_parser()
        args = parser.parse_args(["join"])
        assert args.command == "join"


# --- cmd_skip_updates tests ---


class TestCmdSkipUpdates:
    async def test_skip_updates_advances_offset(self):
        mock_bot = MagicMock()
        update = MagicMock()
        update.update_id = 500
        mock_bot.get_updates = AsyncMock(return_value=[update])
        save_fn = MagicMock()

        await cmd_skip_updates(
            get_bot_token_fn=lambda: "fake-token",
            build_bot_fn=lambda token: mock_bot,
            save_offset_fn=save_fn,
        )

        mock_bot.get_updates.assert_awaited_once_with(offset=-1, timeout=0)
        save_fn.assert_called_once_with(501)

    async def test_skip_updates_no_pending(self):
        mock_bot = MagicMock()
        mock_bot.get_updates = AsyncMock(return_value=[])
        save_fn = MagicMock()

        await cmd_skip_updates(
            get_bot_token_fn=lambda: "fake-token",
            build_bot_fn=lambda token: mock_bot,
            save_offset_fn=save_fn,
        )

        save_fn.assert_not_called()

    async def test_skip_updates_exits_if_no_token(self):
        def raise_runtime():
            raise RuntimeError("TELEGRAM_BOT_TOKEN not set")

        with pytest.raises(SystemExit) as exc_info:
            await cmd_skip_updates(
                get_bot_token_fn=raise_runtime,
                build_bot_fn=lambda token: MagicMock(),
                save_offset_fn=MagicMock(),
            )
        assert exc_info.value.code == 1


# --- cmd_join tests ---


class TestCmdJoin:
    async def test_join_inserts_user_input(self):
        """cmd_join inserts lines from stdin as incoming messages."""
        insert_fn = AsyncMock()
        lines = iter(["hello from cli\n", ""])

        await cmd_join(
            db_path=None,
            init_db_fn=AsyncMock(),
            get_latest_outgoing_id_fn=AsyncMock(return_value=0),
            get_outgoing_after_fn=AsyncMock(side_effect=asyncio.CancelledError()),
            insert_incoming_fn=insert_fn,
            read_line_fn=lambda: next(lines),
            poll_interval=0,
        )

        insert_fn.assert_awaited_once_with(
            text="hello from cli",
            telegram_update_id=0,
            telegram_message_id=0,
            db_path=None,
        )

    async def test_join_empty_lines_not_inserted(self):
        """cmd_join does not insert blank lines."""
        insert_fn = AsyncMock()
        lines = iter(["", ""])

        await cmd_join(
            db_path=None,
            init_db_fn=AsyncMock(),
            get_latest_outgoing_id_fn=AsyncMock(return_value=0),
            get_outgoing_after_fn=AsyncMock(side_effect=asyncio.CancelledError()),
            insert_incoming_fn=insert_fn,
            read_line_fn=lambda: next(lines),
            poll_interval=0,
        )

        insert_fn.assert_not_awaited()

    async def test_join_prints_new_outgoing_messages(self, capsys):
        """cmd_join prints outgoing messages that appear after joining."""
        call_count = 0

        async def fake_get_outgoing(after_id, db_path):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return [{"id": 1, "text": "Hello from Claude", "created_at": "now"}]
            raise asyncio.CancelledError()

        await cmd_join(
            db_path=None,
            init_db_fn=AsyncMock(),
            get_latest_outgoing_id_fn=AsyncMock(return_value=0),
            get_outgoing_after_fn=fake_get_outgoing,
            insert_incoming_fn=AsyncMock(),
            read_line_fn=lambda: "",
            poll_interval=0,
        )

        captured = capsys.readouterr()
        assert "Hello from Claude" in captured.out

    async def test_join_tracks_last_seen_id(self, capsys):
        """cmd_join passes the last seen ID to subsequent polls."""
        poll_calls = []
        call_count = 0

        async def fake_get_outgoing(after_id, db_path):
            nonlocal call_count
            poll_calls.append(after_id)
            call_count += 1
            if call_count == 1:
                return [{"id": 5, "text": "Msg", "created_at": "now"}]
            raise asyncio.CancelledError()

        await cmd_join(
            db_path=None,
            init_db_fn=AsyncMock(),
            get_latest_outgoing_id_fn=AsyncMock(return_value=3),
            get_outgoing_after_fn=fake_get_outgoing,
            insert_incoming_fn=AsyncMock(),
            read_line_fn=lambda: "",
            poll_interval=0,
        )

        assert poll_calls[0] == 3
        assert poll_calls[1] == 5

    async def test_join_initializes_db(self):
        """cmd_join calls init_db_fn on startup."""
        init_fn = AsyncMock()

        await cmd_join(
            db_path=None,
            init_db_fn=init_fn,
            get_latest_outgoing_id_fn=AsyncMock(return_value=0),
            get_outgoing_after_fn=AsyncMock(side_effect=asyncio.CancelledError()),
            insert_incoming_fn=AsyncMock(),
            read_line_fn=lambda: "",
            poll_interval=0,
        )

        init_fn.assert_awaited_once_with(None)

