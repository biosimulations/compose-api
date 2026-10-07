import logging
import os
import sys


def setup_logging(logger: logging.Logger) -> None:
    # Create a root logger
    log_level = os.getenv("LOGGER_LEVEL", logging.INFO)
    root_logger = logging.getLogger()
    root_logger.setLevel(log_level)

    # Create a console handler
    console_handler = logging.StreamHandler(stream=sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Create a formatter
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

    # Add the formatter to the console handler
    console_handler.setFormatter(formatter)

    # Add the console handler to the root logger and uvicorn logger
    root_logger.addHandler(console_handler)
    logger.addHandler(console_handler)
