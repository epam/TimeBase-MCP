class TimeBaseMCPError(Exception):
    """Base class for MCP server errors"""


class ConfigurationError(TimeBaseMCPError):
    """Raised when the server configuration is invalid"""


class TimeBaseConnectionError(TimeBaseMCPError):
    """Raised when the server cannot connect to TimeBase."""


class TimeBaseOperationError(TimeBaseMCPError):
    """Raised when a TimeBase operation fails during execution."""


class TimeBaseOperationTimeoutError(TimeBaseOperationError):
    """Raised when a TimeBase operation exceeds the configured timeout."""


class TimeBaseOperationLimitError(TimeBaseOperationError):
    """Raised when the server rejects a TimeBase operation due to admission limits."""


class TimeBaseOperationStateError(TimeBaseOperationError):
    """Raised when runtime lifecycle state prevents an operation from proceeding."""


class StreamNotFoundError(TimeBaseMCPError):
    """Raised when a requested stream does not exist."""

    def __init__(self, stream_key: str) -> None:
        super().__init__(f"Stream '{stream_key}' was not found.")


class InvalidStreamTimeRangeError(TimeBaseMCPError):
    """Raised when a stream reports an invalid time range."""

    def __init__(self, stream_key: str, time_range_ms: object) -> None:
        super().__init__(
            f"Stream '{stream_key}' returned an invalid time range in ms: "
            f"{time_range_ms!r}."
        )
