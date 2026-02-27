"""Entry point for the corphish daemon."""

import asyncio

from . import config
from .bootstrap import run_bootstrap
from .daemon import run_daemon


async def _async_main() -> None:
    """Runs bootstrap on first launch, otherwise starts the daemon."""
    if config.is_first_run():
        await run_bootstrap()
    else:
        await run_daemon()


def main() -> None:
    """Synchronous entry point called by the console script."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
