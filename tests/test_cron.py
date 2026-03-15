"""Tests for corphish.cron."""

import time

import pytest

from corphish.cron import cron_next_run, cron_validate


def test_cron_next_run_basic():
    """cron_next_run should return a timestamp in the future."""
    now = time.time()
    # Every minute — will always fire within the next 60 seconds
    next_run = cron_next_run("*/1 * * * *", now)
    assert isinstance(next_run, int)
    assert next_run > now


def test_cron_next_run_every_minute():
    """*/1 * * * * fires within 60 seconds of the search start."""
    now = time.time()
    next_run = cron_next_run("*/1 * * * *", now)
    assert next_run <= now + 60


def test_cron_next_run_hourly():
    """0 * * * * fires at a round hour boundary."""
    now = time.time()
    next_run = cron_next_run("0 * * * *", now)
    import datetime

    dt = datetime.datetime.fromtimestamp(next_run)
    assert dt.minute == 0
    assert dt.second == 0


def test_cron_next_run_is_strictly_after():
    """cron_next_run should always be strictly after the search start."""
    now = time.time()
    next_run = cron_next_run("* * * * *", now)
    assert next_run > now


def test_cron_next_run_with_timezone():
    """cron_next_run with a timezone string should return a valid future timestamp."""
    now = time.time()
    next_run = cron_next_run("*/5 * * * *", now, tz="America/New_York")
    assert isinstance(next_run, int)
    assert next_run > now
    assert next_run <= now + 300  # within 5 minutes


def test_cron_validate_valid():
    """cron_validate should return True for valid 5-field cron expressions."""
    assert cron_validate("0 9 * * 1-5") is True
    assert cron_validate("*/30 * * * *") is True
    assert cron_validate("0 8 * * 1") is True
    assert cron_validate("0 9 15 * *") is True
    assert cron_validate("* * * * *") is True
    assert cron_validate("0 0 1 1 *") is True


def test_cron_validate_invalid():
    """cron_validate should return False for invalid cron expressions."""
    assert cron_validate("not a cron") is False
    assert cron_validate("99 * * * *") is False  # minute 99 is invalid
    assert cron_validate("* * * * * *") is False  # 6 fields (not supported)


def test_cron_validate_empty():
    """cron_validate should return False for empty or whitespace strings."""
    assert cron_validate("") is False
    assert cron_validate("   ") is False
