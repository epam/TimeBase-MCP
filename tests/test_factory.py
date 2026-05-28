from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from timebase_mcp.clients import factory
from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.config import Edition, MCPSettings
from timebase_mcp.errors import ConfigurationError, TimeBaseConnectionError


ClientOutcome = str | Exception


@dataclass
class ClientState:
    opened_editions: list[Edition] = field(default_factory=list)
    outcomes: dict[Edition, ClientOutcome] = field(
        default_factory=lambda: {
            "enterprise": "enterprise-db",
            "community": "community-db",
        }
    )


class StubTimeBaseClient(TimeBaseClient):
    edition: Edition

    def __init__(
        self,
        settings: MCPSettings,
        *,
        state: ClientState,
        edition: Edition,
        read_only: bool = True,
    ) -> None:
        super().__init__(settings, read_only=read_only)
        self.edition = edition
        self._state = state
        self._is_open = False

    def open(self) -> str:
        if self._is_open:
            return f"{self.edition}-db"

        self._state.opened_editions.append(self.edition)
        outcome = self._state.outcomes[self.edition]
        if isinstance(outcome, Exception):
            raise outcome
        self._is_open = True
        return str(outcome)

    def close(self) -> None:
        self._is_open = False

    def _require_db(self) -> str:
        if not self._is_open:
            return self.open()
        return f"{self.edition}-db"

    def get_stream(self, stream_key: str) -> object:
        raise NotImplementedError

    def _get_stream_schema_text(self, stream: object) -> str:
        raise NotImplementedError

    def _list_stream_symbols(self, stream: object) -> list[str]:
        raise NotImplementedError

    def _read_stream_messages(
        self,
        stream: object,
        reverse: bool,
        count: int,
    ) -> list[dict[str, object]]:
        raise NotImplementedError

    def _read_query_messages(
        self, query_text: str, limit: int
    ) -> list[dict[str, object]]:
        raise NotImplementedError

    def _compile_query_tokens(self, query_text: str) -> list[object]:
        raise NotImplementedError


@dataclass
class FactoryHarness:
    settings: MCPSettings
    client_state: ClientState


def build_settings() -> MCPSettings:
    return MCPSettings()


def build_oauth2_settings() -> MCPSettings:
    return MCPSettings(
        tb_username="service-user",
        tb_oauth2_token_url="https://idp.example/token",
        tb_oauth2_client_id="client-id",
        tb_oauth2_client_secret=SecretStr("client-secret"),
    )


def patch_available_editions(
    monkeypatch: pytest.MonkeyPatch,
    *editions: Edition,
) -> None:
    monkeypatch.setattr(factory, "_available_editions", lambda: editions)


def patch_create_client(
    monkeypatch: pytest.MonkeyPatch,
    client_state: ClientState,
) -> None:
    def fake_create_client(
        settings: MCPSettings,
        edition: Edition,
        *,
        read_only: bool,
    ) -> StubTimeBaseClient:
        return StubTimeBaseClient(
            settings,
            state=client_state,
            edition=edition,
            read_only=read_only,
        )

    monkeypatch.setattr(factory, "_create_client_for_edition", fake_create_client)


def build_harness(
    monkeypatch: pytest.MonkeyPatch,
    *,
    available_editions: tuple[Edition, ...],
    detected_edition: Edition | None = None,
    outcomes: dict[Edition, ClientOutcome] | None = None,
) -> FactoryHarness:
    settings = build_settings()
    if detected_edition is not None:
        settings.set_detected_edition(detected_edition)

    client_state = ClientState()
    if outcomes is not None:
        client_state.outcomes.update(outcomes)

    patch_available_editions(monkeypatch, *available_editions)
    patch_create_client(monkeypatch, client_state)
    return FactoryHarness(settings, client_state)


def test_create_timebase_client_raises_when_no_clients_are_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = build_settings()
    patch_available_editions(monkeypatch)

    with pytest.raises(ConfigurationError, match="No TimeBase client is installed"):
        factory.create_timebase_client(settings)


def test_create_timebase_client_prefers_enterprise_when_both_clients_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        monkeypatch,
        available_editions=("enterprise", "community"),
    )

    client = factory.create_timebase_client(harness.settings)

    assert isinstance(client, StubTimeBaseClient)
    assert client.edition == "enterprise"
    assert harness.client_state.opened_editions == ["enterprise"]
    assert harness.settings.detected_edition == "enterprise"


def test_get_detected_edition_returns_enterprise_for_oauth2_configuration() -> None:
    settings = build_oauth2_settings()

    assert factory.get_detected_edition(settings) == "enterprise"


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(
            "Failed to connect: Community version is required",
            id="community-marker",
        ),
        pytest.param(
            "Failed to connect: Enterprise version is required",
            id="enterprise-marker",
        ),
    ],
)
def test_create_timebase_client_falls_back_on_known_protocol_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    harness = build_harness(
        monkeypatch,
        available_editions=("enterprise", "community"),
        outcomes={"enterprise": TimeBaseConnectionError(message)},
    )

    client = factory.create_timebase_client(harness.settings)

    assert isinstance(client, StubTimeBaseClient)
    assert client.edition == "community"
    assert harness.client_state.opened_editions == ["enterprise", "community"]
    assert harness.settings.detected_edition == "community"


@pytest.mark.parametrize(
    "message",
    [
        pytest.param(
            "Failed to connect: Community version is required",
            id="community-marker",
        ),
        pytest.param(
            "Failed to connect: Enterprise version is required",
            id="enterprise-marker",
        ),
    ],
)
def test_create_timebase_client_raises_missing_dependency_for_alternate_edition(
    monkeypatch: pytest.MonkeyPatch,
    message: str,
) -> None:
    harness = build_harness(
        monkeypatch,
        available_editions=("enterprise",),
        outcomes={"enterprise": TimeBaseConnectionError(message)},
    )

    with pytest.raises(ConfigurationError, match=r"Install timebase-mcp\[community\]"):
        factory.create_timebase_client(harness.settings)

    assert harness.client_state.opened_editions == ["enterprise"]


def test_create_timebase_client_does_not_fallback_on_generic_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        monkeypatch,
        available_editions=("enterprise", "community"),
        outcomes={
            "enterprise": TimeBaseConnectionError(
                "Failed to connect: connection refused"
            )
        },
    )

    with pytest.raises(TimeBaseConnectionError, match="connection refused"):
        factory.create_timebase_client(harness.settings)

    assert harness.client_state.opened_editions == ["enterprise"]


@pytest.mark.parametrize(
    ("detected_edition", "available_editions", "expected"),
    [
        pytest.param(
            "community", ("enterprise", "community"), "community", id="cached"
        ),
        pytest.param(None, ("community",), "community", id="single-installed"),
        pytest.param(None, ("enterprise", "community"), None, id="unresolved"),
        pytest.param(None, tuple(), None, id="none-installed"),
    ],
)
def test_get_detected_edition(
    monkeypatch: pytest.MonkeyPatch,
    detected_edition: Edition | None,
    available_editions: tuple[Edition, ...],
    expected: Edition | None,
) -> None:
    settings = build_settings()
    patch_available_editions(monkeypatch, *available_editions)
    if detected_edition is not None:
        settings.set_detected_edition(detected_edition)

    assert factory.get_detected_edition(settings) == expected


def test_create_timebase_client_uses_cached_detected_edition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        monkeypatch,
        available_editions=("enterprise", "community"),
        detected_edition="community",
    )

    client = factory.create_timebase_client(harness.settings)

    assert isinstance(client, StubTimeBaseClient)
    assert client.edition == "community"
    assert harness.client_state.opened_editions == []

    with client as opened_client:
        assert opened_client is client

    assert harness.client_state.opened_editions == ["community"]
