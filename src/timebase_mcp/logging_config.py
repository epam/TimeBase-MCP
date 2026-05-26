import logging

from timebase_mcp.config import MCPSettings

_LOG_FORMAT = "%(asctime)s %(name)s %(levelname)s %(message)s"


def configure_logging(settings: MCPSettings) -> None:
    level = getattr(logging, settings.log_level)
    root_logger = logging.getLogger()

    if not root_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter(_LOG_FORMAT))
        root_logger.addHandler(handler)

    root_logger.setLevel(level)
    logging.getLogger("timebase_mcp").setLevel(level)
