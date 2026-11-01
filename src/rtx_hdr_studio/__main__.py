"""Application entry point; importing the package does not initialize a GPU."""

import argparse
import logging
import sys
from logging.handlers import RotatingFileHandler

from . import __version__
from .runtime import cache_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Local NVIDIA TrueHDR image studio")
    parser.add_argument("files", nargs="*", help="SDR images to add to the queue")
    parser.add_argument("--version", action="version", version=__version__)
    args = parser.parse_args()
    if sys.platform != "win32":
        parser.error("The desktop application requires Windows 11 x64.")
    # Bounded log: 1 MiB plus three rotated files.
    handler = RotatingFileHandler(
        cache_dir() / "application.log", maxBytes=1024**2, backupCount=3, encoding="utf-8"
    )
    logging.basicConfig(
        handlers=[handler],
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from .ui.window import run

    return run(args.files)


if __name__ == "__main__":
    raise SystemExit(main())
