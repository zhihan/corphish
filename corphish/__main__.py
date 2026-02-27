"""Entry point for the corphish daemon."""

import asyncio
import logging
import sys

from .cli import build_parser, dispatch


def _configure_logging() -> None:
    """Sets up root logging to stdout/stderr for daemon mode."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        stream=sys.stderr,
    )


async def _async_main(argv: list[str] | None = None) -> None:
    """Parses CLI arguments and dispatches to the appropriate command."""
    _configure_logging()
    parser = build_parser()
    args = parser.parse_args(argv)
    await dispatch(args)


def main() -> None:
    """Synchronous entry point called by the console script."""
    asyncio.run(_async_main())


if __name__ == "__main__":
    main()
