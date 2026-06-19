from dataclasses import dataclass, field

import pytest
from pydantic import SecretStr

from timebase_mcp.clients import factory
from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.config import Edition
from timebase_mcp.errors import ConfigurationError, TimeBaseConnectionError
from timebase_mcp.instance import (
    DEFAULT_INSTANCE_KEY,
    TimeBaseInstanceConfig,
    TimeBaseInstanceRuntime,
)

ClientOutcome = str | Exception


@dataclass
class ClientState:
    opened_editions: list[Edition] = field(default_factory=list)
    read_only_attempts: list[tuple[Edition, bool]] = field(default_factory=list)
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
        settings: TimeBaseInstanceConfig,
        *,
        state: ClientState,
        edition: Edition,
        read_only: bool = False,
    ) -> None:
        super().__init__(settings, read_only=read_only)
        self.edition = edition
        self.read_only = read_only
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
    instance: TimeBaseInstanceRuntime
    client_state: ClientState


def build_instance_config() -> TimeBaseInstanceConfig:
    return TimeBaseInstanceConfig(tb_url="dxtick://localhost:8011")


def build_oauth2_instance_config() -> TimeBaseInstanceConfig:
    return TimeBaseInstanceConfig(
        tb_url="dxtick://localhost:8011",
        tb_username="service-user",
        tb_oauth2_token_url="https://idp.example/token",
        tb_oauth2_client_id="client-id",
        tb_oauth2_client_secret=SecretStr("client-secret"),
    )


def build_instance_runtime(
    *,
    config: TimeBaseInstanceConfig | None = None,
    resolved_edition: Edition | None = None,
) -> TimeBaseInstanceRuntime:
    return TimeBaseInstanceRuntime(
        key=DEFAULT_INSTANCE_KEY,
        config=config or build_instance_config(),
        resolved_edition=resolved_edition,
    )


def patch_available_editions(
    monkeypatch: pytest.MonkeyPatch,
    *editions: Edition,
) -> None:
    monkeypatch.setattr(factory, "_available_editions", lambda _statuses=None: editions)


def patch_create_client(
    monkeypatch: pytest.MonkeyPatch,
    client_state: ClientState,
) -> None:
    def fake_create_client(
        config: TimeBaseInstanceConfig,
        edition: Edition,
        *,
        read_only: bool,
    ) -> StubTimeBaseClient:
        client_state.read_only_attempts.append((edition, read_only))
        return StubTimeBaseClient(
            config,
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
    instance = build_instance_runtime(resolved_edition=detected_edition)

    client_state = ClientState()
    if outcomes is not None:
        client_state.outcomes.update(outcomes)

    patch_available_editions(monkeypatch, *available_editions)
    patch_create_client(monkeypatch, client_state)
    return FactoryHarness(instance, client_state)


def test_create_timebase_client_raises_when_no_clients_are_installed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_available_editions(monkeypatch)

    with pytest.raises(ConfigurationError, match="No compatible TimeBase client"):
        factory.create_timebase_client(build_instance_runtime())


def test_create_timebase_client_reports_incompatible_installed_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_dependency_metadata(
        monkeypatch,
        requirements=["dxapi-ce===6.2.3 ; extra == 'community'"],
        versions={"dxapi-ce": "6.2.1"},
        modules={"dxapi_ce"},
    )

    with pytest.raises(
        ConfigurationError,
        match=r"Community edition requires dxapi-ce===6\.2\.3; found dxapi-ce 6\.2\.1",
    ):
        factory.create_timebase_client(build_instance_runtime())


def test_create_timebase_client_reports_all_incompatible_installed_clients(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_dependency_metadata(
        monkeypatch,
        requirements=[
            "dxapi-ee===5.5.74 ; extra == 'enterprise'",
            "dxapi-ce===6.2.3 ; extra == 'community'",
        ],
        versions={"dxapi-ee": "5.5.72", "dxapi-ce": "6.2.1"},
    )

    with pytest.raises(ConfigurationError) as exc_info:
        factory.create_timebase_client(build_instance_runtime())

    message = str(exc_info.value)
    assert (
        "Enterprise edition requires dxapi-ee===5.5.74; found dxapi-ee 5.5.72"
        in message
    )
    assert (
        "Community edition requires dxapi-ce===6.2.3; found dxapi-ce 6.2.1" in message
    )


def test_create_timebase_client_warns_about_ignored_incompatible_client(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    patch_dependency_metadata(
        monkeypatch,
        requirements=[
            "dxapi-ee===5.5.74 ; extra == 'enterprise'",
            "dxapi-ce===6.2.3 ; extra == 'community'",
        ],
        versions={"dxapi-ee": "5.5.72", "dxapi-ce": "6.2.3"},
    )
    client_state = ClientState()
    patch_create_client(monkeypatch, client_state)

    with caplog.at_level("WARNING"):
        client = factory.create_timebase_client(build_instance_runtime())

    assert isinstance(client, StubTimeBaseClient)
    assert client.edition == "community"
    assert "Ignoring incompatible enterprise TimeBase client" in caplog.text
    assert "found dxapi-ee 5.5.72" in caplog.text


def test_create_timebase_client_reports_incompatible_required_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_dependency_metadata(
        monkeypatch,
        requirements=[
            "dxapi-ee===5.5.74 ; extra == 'enterprise'",
            "dxapi-ce===6.2.3 ; extra == 'community'",
        ],
        versions={"dxapi-ee": "5.5.73", "dxapi-ce": "6.2.1"},
    )
    client_state = ClientState(
        outcomes={
            "enterprise": TimeBaseConnectionError("Community version is required")
        }
    )
    patch_create_client(monkeypatch, client_state)

    with pytest.raises(
        ConfigurationError,
        match=r"Community edition requires dxapi-ce===6\.2\.3; found dxapi-ce 6\.2\.1",
    ):
        factory.create_timebase_client(build_instance_runtime())


def test_create_timebase_client_prefers_enterprise_when_both_clients_connect(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        monkeypatch,
        available_editions=("enterprise", "community"),
    )

    client = factory.create_timebase_client(harness.instance)

    assert isinstance(client, StubTimeBaseClient)
    assert client.edition == "enterprise"
    assert client.read_only is False
    assert harness.client_state.opened_editions == ["enterprise"]
    assert harness.client_state.read_only_attempts == [("enterprise", False)]
    assert harness.instance.resolved_edition == "enterprise"


def test_get_detected_edition_returns_enterprise_for_oauth2_configuration() -> None:
    instance = build_instance_runtime(config=build_oauth2_instance_config())

    assert factory.get_detected_edition(instance) == "enterprise"


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

    client = factory.create_timebase_client(harness.instance)

    assert isinstance(client, StubTimeBaseClient)
    assert client.edition == "community"
    assert client.read_only is False
    assert harness.client_state.opened_editions == ["enterprise", "community"]
    assert harness.client_state.read_only_attempts == [
        ("enterprise", False),
        ("community", False),
    ]
    assert harness.instance.resolved_edition == "community"


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
        factory.create_timebase_client(harness.instance)

    assert harness.client_state.opened_editions == ["enterprise"]
    assert harness.client_state.read_only_attempts == [("enterprise", False)]


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
        factory.create_timebase_client(harness.instance)

    assert harness.client_state.opened_editions == ["enterprise"]
    assert harness.client_state.read_only_attempts == [("enterprise", False)]


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
    patch_available_editions(monkeypatch, *available_editions)
    instance = build_instance_runtime(resolved_edition=detected_edition)

    assert factory.get_detected_edition(instance) == expected


def test_create_timebase_client_uses_cached_detected_edition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    harness = build_harness(
        monkeypatch,
        available_editions=("enterprise", "community"),
        detected_edition="community",
    )

    client = factory.create_timebase_client(harness.instance)

    assert isinstance(client, StubTimeBaseClient)
    assert client.edition == "community"
    assert client.read_only is False
    assert harness.client_state.opened_editions == ["community"]
    assert harness.client_state.read_only_attempts == [("community", False)]


def patch_dependency_metadata(
    monkeypatch: pytest.MonkeyPatch,
    *,
    requirements: list[str],
    versions: dict[str, str],
    modules: set[str] | None = None,
) -> None:
    monkeypatch.setattr(
        factory,
        "_has_dependency",
        lambda module_name: modules is None or module_name in modules,
    )
    monkeypatch.setattr(factory.metadata, "requires", lambda _dist_name: requirements)
    monkeypatch.setattr(
        factory.metadata,
        "version",
        lambda distribution_name: versions[distribution_name],
    )


def test_dependency_status_allows_matching_enterprise_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_dependency_metadata(
        monkeypatch,
        requirements=["dxapi-ee===5.5.74 ; extra == 'enterprise'"],
        versions={"dxapi-ee": "5.5.74"},
    )

    status = factory._dependency_status("enterprise")

    assert status.compatible


def test_dependency_status_rejects_old_enterprise_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_dependency_metadata(
        monkeypatch,
        requirements=["dxapi-ee===5.5.74 ; extra == 'enterprise'"],
        versions={"dxapi-ee": "5.5.72"},
    )

    status = factory._dependency_status("enterprise")

    assert status.error is not None
    assert "dxapi-ee===5.5.74" in str(status.error)
    assert "found dxapi-ee 5.5.72" in str(status.error)
    assert "timebase-mcp[enterprise]" in str(status.error)


def test_dependency_status_uses_community_distribution_name(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checked_modules: list[str] = []
    checked_versions: list[str] = []

    def fake_has_dependency(module_name: str) -> bool:
        checked_modules.append(module_name)
        return True

    def fake_version(distribution_name: str) -> str:
        checked_versions.append(distribution_name)
        return "6.2.3"

    monkeypatch.setattr(factory, "_has_dependency", fake_has_dependency)
    monkeypatch.setattr(
        factory.metadata,
        "requires",
        lambda _dist_name: ["dxapi-ce===6.2.3 ; extra == 'community'"],
    )
    monkeypatch.setattr(factory.metadata, "version", fake_version)

    status = factory._dependency_status("community")

    assert status.compatible
    assert checked_modules == ["dxapi_ce"]
    assert checked_versions == ["dxapi-ce"]


@pytest.mark.parametrize(
    ("installed_version", "raises"),
    [
        pytest.param("6.2.3", False, id="minimum-compatible"),
        pytest.param("6.5.0", False, id="range-compatible"),
        pytest.param("7.0.0", True, id="range-incompatible"),
    ],
)
def test_dependency_status_supports_version_ranges(
    monkeypatch: pytest.MonkeyPatch,
    installed_version: str,
    raises: bool,
) -> None:
    patch_dependency_metadata(
        monkeypatch,
        requirements=["dxapi-ce>=6.2,<7 ; extra == 'community'"],
        versions={"dxapi-ce": installed_version},
    )

    status = factory._dependency_status("community")

    if raises:
        assert status.error is not None
        assert "dxapi-ce<7,>=6.2" in str(status.error)
    else:
        assert status.compatible


def test_available_editions_excludes_incompatible_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    patch_dependency_metadata(
        monkeypatch,
        requirements=[
            "dxapi-ee===5.5.74 ; extra == 'enterprise'",
            "dxapi-ce===6.2.3 ; extra == 'community'",
        ],
        versions={"dxapi-ee": "5.5.72", "dxapi-ce": "6.2.3"},
    )

    assert factory._available_editions() == ("community",)


def test_create_client_for_edition_validates_before_loading_client_class(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail_load_client_class(_edition: Edition) -> type[TimeBaseClient]:
        pytest.fail("_load_client_class should not be called before validation")

    monkeypatch.setattr(
        factory,
        "_dependency_status",
        lambda _edition: factory._DependencyStatus(
            installed=True,
            error=ConfigurationError("incompatible dependency"),
        ),
    )
    monkeypatch.setattr(factory, "_load_client_class", fail_load_client_class)

    with pytest.raises(ConfigurationError, match="incompatible dependency"):
        factory._create_client_for_edition(
            build_instance_config(),
            "enterprise",
            read_only=True,
        )
