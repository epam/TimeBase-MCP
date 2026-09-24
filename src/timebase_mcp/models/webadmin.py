from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class WebAdminTimeBaseInfo(BaseModel):
    model_config = ConfigDict(json_schema_mode_override="serialization")

    connected: bool | None = None
    client_version: str | None = Field(default=None, validation_alias="clientVersion")
    server_version: str | None = Field(default=None, validation_alias="serverVersion")


class WebAdminAuthenticationInfo(BaseModel):
    provider_type: str | None = None
    oauth_server: str | None = None
    token_endpoint: str | None = None
    scopes: list[str] = Field(default_factory=list)


class WebAdminInfo(BaseModel):
    instance_key: str
    url: str
    name: str | None = None
    version: str | None = None
    timestamp: int | None = None
    authentication_enabled: bool | None = None
    timebase: WebAdminTimeBaseInfo | None = None
    authentication: WebAdminAuthenticationInfo


class WebAdminView(BaseModel):
    model_config = ConfigDict(json_schema_mode_override="serialization")

    id: str
    stream: str | None = None
    live: bool = False
    state: str | None = None
    paused: bool = False
    description: str | None = None
    info: str | None = None
    last_timestamp: int | None = Field(default=None, validation_alias="lastTimestamp")
    query: str | None = None


class WebAdminViews(BaseModel):
    items: list[WebAdminView]
    returned_count: int
    truncated: bool


class WebAdminTopics(BaseModel):
    items: list[str]
    returned_count: int
    truncated: bool


class WebAdminSchema(BaseModel):
    types: list[dict[str, Any]]
    all: list[dict[str, Any]]


class WebAdminError(BaseModel):
    name: str | None = None
    message: str | None = None


class WebAdminBackgroundTask(BaseModel):
    model_config = ConfigDict(json_schema_mode_override="serialization")

    refer_to_stream: str | None = Field(default=None, validation_alias="referToStream")
    name: str | None = None
    is_finished: bool = Field(validation_alias="isFinished")
    progress: float
    error: WebAdminError | None = None
    status: str | None = None
    start_time: str | None = Field(default=None, validation_alias="startTime")
    end_time: str | None = Field(default=None, validation_alias="endTime")


class OrderBookValidationIssue(BaseModel):
    model_config = ConfigDict(json_schema_mode_override="serialization")

    timestamp_ns: str | None = Field(default=None, validation_alias="timestampNs")
    symbol: str | None = None
    severity: str | None = None
    message: str | None = None
    source: str | None = None


class OrderBookValidationIssues(BaseModel):
    model_config = ConfigDict(json_schema_mode_override="serialization")

    issues: list[OrderBookValidationIssue] = Field(default_factory=list)
    offset: int
    rows: int
    has_more: bool = Field(validation_alias="hasMore")
    inline_only: bool = Field(validation_alias="inlineOnly")
    warning_message: str | None = Field(
        default=None,
        validation_alias="warningMessage",
    )
