"""Logging setup shared by the CLI, API server and collector."""

import logging
import sys

from app_collector.config import settings

logger = logging.getLogger("app_collector")

if not logger.handlers:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("[%(asctime)s] %(levelname)s %(name)s - %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(settings.log_level)
    logger.propagate = False
