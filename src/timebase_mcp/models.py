from datetime import datetime

from pydantic import BaseModel, Field


class MCPServerConfiguration(BaseModel):
    transport: str
    tb_url: str
    tb_username: str | None = None
    edition: str | None = None


class StreamInfo(BaseModel):
    key: str
    description: str | None = None


class StreamSchema(BaseModel):
    stream_key: str
    schema_text: str


class StreamSymbols(BaseModel):
    stream_key: str
    symbols: list[str] = Field(default_factory=list)
    returned_count: int = 0
    symbols_changed_since_cursor: bool = False
    next_cursor: str | None = None


class StreamTimeRange(BaseModel):
    stream_key: str
    start: datetime | None = None
    end: datetime | None = None


class QQLErrorPosition(BaseModel):
    start_line: int
    start_column: int
    end_line: int
    end_column: int


class CompileQQLResult(BaseModel):
    valid: bool
    error: str | None = None
    error_token: str | None = Field(
        default=None,
        description="First unexpected token at parser failure point; may be downstream from root cause.",
    )
    error_context: str | None = Field(
        default=None,
        description="Short query snippet around parser failure position.",
    )
    error_position: QQLErrorPosition | None = None
