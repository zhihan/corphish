"""Tests for corphish.__main__."""

from unittest.mock import AsyncMock, patch

import pytest

from corphish.__main__ import _async_main


async def test_first_run_calls_bootstrap():
    with (
        patch("corphish.__main__.config") as mock_config,
        patch("corphish.__main__.run_bootstrap", new_callable=AsyncMock) as mock_boot,
        patch("corphish.__main__.run_daemon", new_callable=AsyncMock) as mock_daemon,
    ):
        mock_config.is_first_run.return_value = True
        await _async_main()

    mock_boot.assert_awaited_once()
    mock_daemon.assert_not_awaited()


async def test_subsequent_run_calls_daemon():
    with (
        patch("corphish.__main__.config") as mock_config,
        patch("corphish.__main__.run_bootstrap", new_callable=AsyncMock) as mock_boot,
        patch("corphish.__main__.run_daemon", new_callable=AsyncMock) as mock_daemon,
    ):
        mock_config.is_first_run.return_value = False
        await _async_main()

    mock_daemon.assert_awaited_once()
    mock_boot.assert_not_awaited()
