"""Consistent logging across scripts, notebooks and the API."""

from __future__ import annotations

import logging
import sys

_CONFIGURED = False


def setup_logging(level: int | str = logging.INFO) -> None:
    """Install a single stream handler with a compact, readable format."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s  %(levelname)-7s  %(name)-28s  %(message)s",
            datefmt="%H:%M:%S",
        )
    )
    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(level)

    # These are chatty and never tell us anything we want during a data build.
    for noisy in ("matplotlib", "PIL", "pdfminer", "fontTools"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    setup_logging()
    return logging.getLogger(name)
