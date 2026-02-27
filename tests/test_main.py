"""Tests for corphish.__main__."""

from unittest.mock import AsyncMock, patch

from corphish.__main__ import _async_main


async def test_no_args_dispatches_to_default():
    with patch("corphish.__main__.dispatch", new_callable=AsyncMock) as mock_dispatch:
        await _async_main([])

    mock_dispatch.assert_awaited_once()
    args = mock_dispatch.call_args[0][0]
    assert args.command is None


async def test_run_command_dispatches():
    with patch("corphish.__main__.dispatch", new_callable=AsyncMock) as mock_dispatch:
        await _async_main(["run"])

    args = mock_dispatch.call_args[0][0]
    assert args.command == "run"


async def test_send_command_dispatches():
    with patch("corphish.__main__.dispatch", new_callable=AsyncMock) as mock_dispatch:
        await _async_main(["send", "hello"])

    args = mock_dispatch.call_args[0][0]
    assert args.command == "send"
    assert args.text == ["hello"]


async def test_bootstrap_command_dispatches():
    with patch("corphish.__main__.dispatch", new_callable=AsyncMock) as mock_dispatch:
        await _async_main(["bootstrap"])

    args = mock_dispatch.call_args[0][0]
    assert args.command == "bootstrap"


async def test_status_command_dispatches():
    with patch("corphish.__main__.dispatch", new_callable=AsyncMock) as mock_dispatch:
        await _async_main(["status"])

    args = mock_dispatch.call_args[0][0]
    assert args.command == "status"
