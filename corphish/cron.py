"""Cron expression utilities."""
import datetime

from croniter import CroniterBadCronError, croniter


def cron_next_run(expr: str, after: float, tz=None) -> int:
    """Returns the next fire time as a unix epoch (int).

    Args:
        expr: 5-field cron expression.
        after: Search start as unix timestamp.
        tz: Optional timezone string (e.g. "America/New_York"). Uses system local if None.

    Returns:
        The next scheduled fire time as a unix epoch integer.
    """
    if tz:
        import zoneinfo

        tzinfo = zoneinfo.ZoneInfo(tz)
        start_dt = datetime.datetime.fromtimestamp(after, tz=tzinfo)
    else:
        start_dt = datetime.datetime.fromtimestamp(after)

    cron = croniter(expr, start_dt)
    next_dt = cron.get_next(datetime.datetime)
    return int(next_dt.timestamp())


def cron_prev_run(expr: str, before: float, tz=None) -> int:
    """Returns the most recent fire time before *before* as a unix epoch (int).

    Args:
        expr: 5-field cron expression.
        before: Search end as unix timestamp.
        tz: Optional timezone string. Uses system local if None.

    Returns:
        The most recent scheduled fire time before *before* as a unix epoch integer.
    """
    if tz:
        import zoneinfo

        tzinfo = zoneinfo.ZoneInfo(tz)
        start_dt = datetime.datetime.fromtimestamp(before, tz=tzinfo)
    else:
        start_dt = datetime.datetime.fromtimestamp(before)

    cron = croniter(expr, start_dt)
    prev_dt = cron.get_prev(datetime.datetime)
    return int(prev_dt.timestamp())


def cron_validate(expr: str) -> bool:
    """Returns True if expr is a valid 5-field cron expression.

    Args:
        expr: The cron expression string to validate.

    Returns:
        True if the expression is valid, False otherwise.
    """
    if not expr or not expr.strip():
        return False
    # Require exactly 5 fields
    if len(expr.split()) != 5:
        return False
    try:
        croniter(expr)
        return True
    except (CroniterBadCronError, ValueError, KeyError):
        return False
