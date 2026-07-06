from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class TimeBaseLicenseSummary(BaseModel):
    valid: bool | None = None
    valid_until: str | None = None
    expiration_time: str | None = None
    days_valid: int | None = None
    last_validate_time: str | None = None
    error: str | None = None


class TimeBaseRuntimeSummary(BaseModel):
    timestamp: int | None = None
    cpu_count: int | None = None
    max_memory_mb: int | None = None
    used_memory_mb: int | None = None
    current_memory_mb: int | None = None
    available_memory_mb: int | None = None
    os_name: str | None = None
    os_version: str | None = None
    os_arch: str | None = None
    java_name: str | None = None
    java_version: str | None = None
    java_vendor: str | None = None


class TimeBaseSecuritySummary(BaseModel):
    enabled: bool | None = None
    controller_type: str | None = None


class TimeBaseStatus(BaseModel):
    instance_key: str
    http_url: str | None = None
    version: str | None = None
    security: TimeBaseSecuritySummary | None = None
    license: TimeBaseLicenseSummary | None = None
    runtime: TimeBaseRuntimeSummary | None = None
    warnings: list[str] = Field(default_factory=list)


class TimeBaseCursorActivity(BaseModel):
    id: int
    user: str | None = None
    application: str | None = None
    source_stream_keys: list[str] = Field(default_factory=list)
    open_time: int | None = None
    total_messages: int | None = None
    last_message_timestamp: int | None = None
    last_message_sys_time: int | None = None


class TimeBaseLoaderActivity(BaseModel):
    id: int
    user: str | None = None
    application: str | None = None
    target_stream_key: str | None = None
    open_time: int | None = None
    total_messages: int | None = None
    last_message_timestamp: int | None = None
    last_message_sys_time: int | None = None
    progress: float | None = None


class TimeBaseConnectionActivity(BaseModel):
    client_id: str
    application_id: str | None = None
    creation_time: int | None = None
    remote_address: str | None = None
    num_transport_channels: int | None = None
    throughput: int | None = None
    average_throughput: float | None = None


class TimeBaseLockActivity(BaseModel):
    id: int
    guid: str | None = None
    type: str | None = None
    client_id: str | None = None
    stream_key: str | None = None
    application: str | None = None
    user: str | None = None
    host: str | None = None


class TimeBaseActivityCounts(BaseModel):
    cursors: int = 0
    loaders: int = 0
    connections: int = 0
    locks: int = 0


class TimeBaseActivityList(BaseModel):
    instance_key: str
    counts: TimeBaseActivityCounts = Field(default_factory=TimeBaseActivityCounts)
    cursors: list[TimeBaseCursorActivity] = Field(default_factory=list)
    loaders: list[TimeBaseLoaderActivity] = Field(default_factory=list)
    connections: list[TimeBaseConnectionActivity] = Field(default_factory=list)
    locks: list[TimeBaseLockActivity] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class TimeBaseActivityDetail(BaseModel):
    instance_key: str
    kind: Literal["cursor", "loader", "connection", "lock"]
    detail: dict[str, Any]
    instruments: dict[str, Any] | None = None
    warnings: list[str] = Field(default_factory=list)
