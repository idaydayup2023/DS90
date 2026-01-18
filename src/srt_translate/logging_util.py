from __future__ import annotations

import logging
import os


def setup_logging(level: str | None = None) -> None:
    level = level or os.environ.get("SRT_TRANSLATE_LOG_LEVEL", "INFO")
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )

