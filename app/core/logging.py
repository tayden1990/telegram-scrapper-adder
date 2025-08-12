import logging
from logging.config import dictConfig
import json


def setup_logging(level: str = "INFO"):
    dictConfig(
        {
            "version": 1,
            "disable_existing_loggers": False,
            "formatters": {
                "default": {
                    "format": "%(asctime)s | %(levelname)s | %(name)s | %(message)s",
                },
                "json": {
                    "()": "logging.Formatter",
                    "format": "{\"time\": \"%(asctime)s\", \"level\": \"%(levelname)s\", \"name\": \"%(name)s\", \"message\": \"%(message)s\"}",
                },
            },
            "handlers": {
                "console": {
                    "class": "logging.StreamHandler",
                    "formatter": "default",
                }
            },
            "root": {
                "level": level,
                "handlers": ["console"],
            },
        }
    )
    logging.getLogger(__name__).info("Logging configured")
