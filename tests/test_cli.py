"""Tests for corphish.cli."""

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from corphish.cli import build_parser, cmd_send, cmd_status, dispatch


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

    def test_status_command(self):
        parser = build_parser()
        args = parser.parse_args(["status"])
        assert args.command == "status"

    def test_no_command_defaults_to_none(self):
        parser = build_parser()
        args = parser.parse_args([])
        assert args.command is None


# --- cmd_send tests ---


class TestCmdSend:
    async def test_send_message_success(self):
        mock_bot = MagicMock()
        mock_send = AsyncMock()

        await cmd_send(
            "hello world",
            get_token_fn=lambda: "fake-token",
            build_bot_fn=lambda token: mock_bot,
            load_config_fn=lambda: {"chat_id": 123},
            send_message_fn=mock_send,
        )

        mock_send.assert_awaited_once_with(mock_bot, 123, "hello world")

    async def test_send_exits_if_not_bootstrapped(self):
        with pytest.raises(SystemExit) as exc_info:
            await cmd_send(
                "hello",
                get_token_fn=lambda: "fake-token",
                build_bot_fn=lambda token: MagicMock(),
                load_config_fn=lambda: {},
                send_message_fn=AsyncMock(),
            )
        assert exc_info.value.code == 1

    async def test_send_does_not_call_bot_if_not_bootstrapped(self):
        mock_send = AsyncMock()
        with pytest.raises(SystemExit):
            await cmd_send(
                "hello",
                get_token_fn=lambda: "fake-token",
                build_bot_fn=lambda token: MagicMock(),
                load_config_fn=lambda: {},
                send_message_fn=mock_send,
            )
        mock_send.assert_not_awaited()


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
    async def test_dispatch_send(self):
        parser = build_parser()
        args = parser.parse_args(["send", "hi", "there"])

        with patch("corphish.cli.cmd_send", new_callable=AsyncMock) as mock_send:
            await dispatch(args)
            mock_send.assert_awaited_once_with("hi there")

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
