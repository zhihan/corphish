"""Entry point for the corphish daemon."""

import asyncio
import logging
import sys

from . import config
from .bootstrap import run_bootstrap
from .daemon import run_daemon


def _configure_logging() -> None:
    """Sets up root logging to stdout/stderr for daemon mode."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _async_main() -> None:
    """Runs bootstrap on first launch, otherwise starts the daemon."""
    _configure_logging()
    if config.is_first_run():
        await run_bootstrap()
    else:
        await run_daemon()


def main() -> None:
    """Synchronous entry point called by the console script."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
