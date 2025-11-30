#!/usr/bin/env python3
"""
pymobiledevice3 REST API Server

A REST API wrapper for pymobiledevice3 to manage iOS devices.
"""

import logging
import sys
import uvicorn
from config import settings


def setup_logging():
    """Configure logging for the application."""
    log_level = getattr(logging, settings.log_level.upper(), logging.INFO)

    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        handlers=[logging.StreamHandler(sys.stdout)],
    )

    # Set specific log levels for verbose libraries
    logging.getLogger("pymobiledevice3").setLevel(logging.WARNING)
    logging.getLogger("uvicorn.access").setLevel(logging.WARNING)


def main():
    """Main entry point for the application."""
    setup_logging()
    logger = logging.getLogger(__name__)

    logger.info(f"Starting server on {settings.host}:{settings.port}")
    logger.info(f"Log level: {settings.log_level}")

    try:
        uvicorn.run(
            "api:app",
            host=settings.host,
            port=settings.port,
            log_level=settings.log_level.lower(),
            access_log=False,
        )
    except KeyboardInterrupt:
        logger.info("Server stopped by user")
    except Exception as e:
        logger.error(f"Server error: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
