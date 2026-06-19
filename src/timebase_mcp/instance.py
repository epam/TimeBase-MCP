from __future__ import annotations

import asyncio
import dataclasses
import logging
import time
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from pydantic import SecretStr

from timebase_mcp.auth.oauth2 import (
    OAuth2AccessTokenProvider,
    OAuth2ClientCredentialsConfig,
)
from timebase_mcp.config import Edition, InboundAuthMode, OutboundAuthMode, ServerConfig
from timebase_mcp.constants import DEFAULT_INSTANCE_KEY, SHARED_PRINCIPAL_KEY
from timebase_mcp.pool import TimeBaseConnectionPool, TimeBaseOperationBudget

if TYPE_CHECKING:
    from timebase_mcp.clients.base import TimeBaseClient

logger = logging.getLogger(__name__)

# Bounds for ``forward_identity`` per-principal pools so a busy multi-user server
# does not accumulate unbounded TimeBase connections.
DEFAULT_MAX_PRINCIPAL_POOLS = 64
DEFAULT_PRINCIPAL_IDLE_TTL_SECONDS = 300.0

__all__ = [
    "DEFAULT_INSTANCE_KEY",
    "DEFAULT_MAX_PRINCIPAL_POOLS",
    "DEFAULT_PRINCIPAL_IDLE_TTL_SECONDS",
    "TimeBaseInstanceConfig",
    "TimeBaseInstanceRuntime",
]


@dataclass(frozen=True, slots=True)
class TimeBaseInstanceConfig:
    """Connection settings for one TimeBase server identity."""

    tb_url: str
    description: str | None = None
    auth_mode: OutboundAuthMode = "none"
    tb_username: str | None = None
    tb_password: SecretStr | None = None
    tb_oauth2_token_url: str | None = None
    tb_oauth2_client_id: str | None = None
    tb_oauth2_client_secret: SecretStr | None = None
    tb_oauth2_scope: str | None = None
    tb_oauth2_token_params: dict[str, str] | None = None
    http_base_url: str | None = None
    # Bearer token forwarded from the authenticated MCP caller (forward_identity).
    access_token: str | None = None
    access_token_username: str | None = None
    # Last failed auto-auth discovery reason; used only for diagnostics before an
    # anonymous fallback connection fails against a protected TimeBase.
    auto_auth_error: str | None = None

    @classmethod
    def from_server_config(cls, server: ServerConfig) -> TimeBaseInstanceConfig:
        return cls(
            tb_url=server.url,
            description=server.description,
            auth_mode=server.auth_mode or "none",
            tb_username=server.username,
            tb_password=server.password,
            tb_oauth2_token_url=server.oauth2_token_url,
            tb_oauth2_client_id=server.oauth2_client_id,
            tb_oauth2_client_secret=server.oauth2_client_secret,
            tb_oauth2_scope=server.oauth2_scope,
            tb_oauth2_token_params=server.oauth2_token_params,
            http_base_url=server.http_base_url,
        )

    @property
    def oauth2_config(self) -> OAuth2ClientCredentialsConfig | None:
        token_url = self.tb_oauth2_token_url
        client_id = self.tb_oauth2_client_id
        client_secret = self.tb_oauth2_client_secret

        if token_url is None or client_id is None or client_secret is None:
            return None

        return OAuth2ClientCredentialsConfig(
            token_url=token_url,
            client_id=client_id,
            client_secret=client_secret.get_secret_value(),
            scope=self.tb_oauth2_scope,
            token_params=self.tb_oauth2_token_params,
        )

    @property
    def requires_enterprise_client(self) -> bool:
        """Token-based auth is only supported by the enterprise client."""
        return (
            self.oauth2_config is not None
            or self.access_token is not None
            or self.auth_mode
            in ("oauth2_client_credentials", "forward_identity", "interactive")
        )

    def with_access_token(
        self,
        token: str,
        username: str | None = None,
    ) -> TimeBaseInstanceConfig:
        return dataclasses.replace(
            self,
            access_token=token,
            access_token_username=username or self.access_token_username,
        )


@dataclass(slots=True)
class _ForwardedIdentity:
    """Latest bearer token/username for a forward_identity principal pool."""

    token: str
    username: str | None


@dataclass(slots=True)
class _PrincipalPool:
    pool: TimeBaseConnectionPool["TimeBaseClient"]
    last_used_monotonic: float
    identity: _ForwardedIdentity | None = None


@dataclass(slots=True)
class TimeBaseInstanceRuntime:
    """Runtime state for a single TimeBase server instance.

    A single instance corresponds to one configured TimeBase server. Within it,
    connections are pooled per principal: a single shared pool for the
    process-wide identity modes and one pool per authenticated caller for
    ``forward_identity``.
    """

    key: str
    config: TimeBaseInstanceConfig
    interactive_redirect_uri: str | None = None
    runtime_auth_enabled: bool = False
    runtime_is_http_transport: bool = False
    runtime_inbound_auth_mode: InboundAuthMode = "none"
    runtime_is_remote_http_bind: bool = False
    resolved_edition: Edition | None = None
    operation_budget: TimeBaseOperationBudget = field(
        default_factory=TimeBaseOperationBudget,
        repr=False,
    )
    max_principal_pools: int = DEFAULT_MAX_PRINCIPAL_POOLS
    principal_idle_ttl_seconds: float = DEFAULT_PRINCIPAL_IDLE_TTL_SECONDS
    interactive_provider: OAuth2AccessTokenProvider | None = field(
        default=None,
        init=False,
        repr=False,
    )
    _principal_pools: dict[str, _PrincipalPool] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _eviction_tasks: set[asyncio.Task[None]] = field(
        default_factory=set,
        init=False,
        repr=False,
    )

    @property
    def connection_pool(self) -> TimeBaseConnectionPool["TimeBaseClient"] | None:
        entry = self._principal_pools.get(SHARED_PRINCIPAL_KEY)
        return entry.pool if entry is not None else None

    def get_connection_pool(self) -> TimeBaseConnectionPool["TimeBaseClient"]:
        """Return the shared, process-identity connection pool."""
        entry = self._principal_pools.get(SHARED_PRINCIPAL_KEY)
        if entry is not None:
            return entry.pool

        pool = TimeBaseConnectionPool(
            self.key,
            self.open_client,
            self.operation_budget,
        )
        self._principal_pools[SHARED_PRINCIPAL_KEY] = _PrincipalPool(
            pool=pool,
            last_used_monotonic=time.monotonic(),
        )
        return pool

    def get_principal_pool(
        self,
        principal_key: str,
        access_token: str,
        access_username: str | None,
    ) -> TimeBaseConnectionPool["TimeBaseClient"]:
        """Return (creating if needed) a per-principal pool for forward_identity."""
        now = time.monotonic()
        entry = self._principal_pools.get(principal_key)
        if entry is not None and entry.identity is not None:
            if entry.identity.token == access_token:
                entry.last_used_monotonic = now
                entry.identity.username = access_username
                return entry.pool

            # Bearer tokens are connection credentials. Reusing an idle TimeBase
            # client opened with the previous token can continue operating as an
            # expired/revoked identity, so rotate the whole principal pool when
            # the caller's token changes. Existing checked-out operations finish
            # on the old pool; new operations use the new token.
            self._principal_pools.pop(principal_key, None)
            self._schedule_close(entry.pool)

        identity = _ForwardedIdentity(token=access_token, username=access_username)
        pool = TimeBaseConnectionPool(
            self.key,
            self._make_forwarded_creator(identity),
            self.operation_budget,
        )
        self._principal_pools[principal_key] = _PrincipalPool(
            pool=pool,
            last_used_monotonic=now,
            identity=identity,
        )
        self._evict_principal_pools(now)
        return pool

    def open_client(self) -> "TimeBaseClient":
        from timebase_mcp.clients.factory import create_timebase_client

        return create_timebase_client(self, read_only=False)

    def _make_forwarded_creator(self, identity: _ForwardedIdentity):
        instance = self

        def create() -> "TimeBaseClient":
            from timebase_mcp.clients.factory import create_timebase_client

            connection_config = instance.config.with_access_token(
                identity.token,
                identity.username,
            )
            return create_timebase_client(
                instance,
                read_only=False,
                config=connection_config,
            )

        return create

    def get_interactive_provider(self) -> OAuth2AccessTokenProvider:
        if self.interactive_provider is None:
            from timebase_mcp.auth.interactive import build_interactive_provider

            self.interactive_provider = build_interactive_provider(
                self.config,
                redirect_uri=self.interactive_redirect_uri,
            )
        return self.interactive_provider

    def _evict_principal_pools(self, now: float) -> None:
        principal_keys = [
            key for key in self._principal_pools if key != SHARED_PRINCIPAL_KEY
        ]
        to_evict: list[str] = [
            key
            for key in principal_keys
            if now - self._principal_pools[key].last_used_monotonic
            > self.principal_idle_ttl_seconds
        ]

        remaining = [key for key in principal_keys if key not in to_evict]
        overflow = len(remaining) - self.max_principal_pools
        if overflow > 0:
            lru_order = sorted(
                remaining,
                key=lambda key: self._principal_pools[key].last_used_monotonic,
            )
            to_evict.extend(lru_order[:overflow])

        for key in dict.fromkeys(to_evict):
            entry = self._principal_pools.pop(key, None)
            if entry is not None:
                self._schedule_close(entry.pool)

    def _schedule_close(
        self,
        pool: TimeBaseConnectionPool["TimeBaseClient"],
    ) -> None:
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return

        task = loop.create_task(pool.aclose())
        self._eviction_tasks.add(task)
        task.add_done_callback(self._eviction_tasks.discard)

    async def reset_connection_state(
        self,
        principal_key: str = SHARED_PRINCIPAL_KEY,
    ) -> None:
        entry = self._principal_pools.pop(principal_key, None)
        if entry is None:
            return

        await entry.pool.aclose()

    async def aclose(self) -> None:
        pools = [entry.pool for entry in self._principal_pools.values()]
        self._principal_pools.clear()

        if pools:
            await asyncio.gather(
                *(pool.aclose() for pool in pools),
                return_exceptions=True,
            )

        if self._eviction_tasks:
            await asyncio.gather(
                *tuple(self._eviction_tasks),
                return_exceptions=True,
            )
