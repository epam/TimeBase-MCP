import importlib.util
import logging
from dataclasses import dataclass
from importlib import import_module, metadata
from typing import cast

from packaging.markers import default_environment
from packaging.requirements import InvalidRequirement, Requirement
from packaging.utils import canonicalize_name

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.config import Edition, MCPSettings
from timebase_mcp.errors import ConfigurationError, TimeBaseConnectionError

logger = logging.getLogger(__name__)

_DIST_NAME = "timebase-mcp"
_AUTO_EDITION_ORDER: tuple[Edition, ...] = ("enterprise", "community")
_PROTOCOL_MISMATCH_MARKERS: tuple[str, ...] = (
    "enterprise version is required",
    "community version is required",
)


@dataclass(frozen=True)
class _EditionInfo:
    label: str
    module_name: str
    distribution_name: str
    extra_name: str
    client_module: str
    client_class: str


_EDITION_INFO: dict[Edition, _EditionInfo] = {
    "enterprise": _EditionInfo(
        label="Enterprise",
        module_name="dxapi",
        distribution_name="dxapi",
        extra_name="timebase-mcp[enterprise]",
        client_module="timebase_mcp.clients.enterprise",
        client_class="EnterpriseTimeBaseClient",
    ),
    "community": _EditionInfo(
        label="Community",
        module_name="dxapi_ce",
        distribution_name="dxapi-ce",
        extra_name="timebase-mcp[community]",
        client_module="timebase_mcp.clients.community",
        client_class="CommunityTimeBaseClient",
    ),
}


@dataclass(frozen=True)
class _DependencyStatus:
    installed: bool
    error: ConfigurationError | None = None

    @property
    def compatible(self) -> bool:
        return self.installed and self.error is None


def create_timebase_client(
    settings: MCPSettings,
    *,
    read_only: bool = True,
) -> TimeBaseClient:
    if settings.oauth2_config is not None:
        settings.set_detected_edition("enterprise")

    detected_edition = settings.detected_edition
    if detected_edition is not None:
        logger.debug(
            "Using %s client for %s",
            detected_edition,
            settings.tb_url,
        )
        return _create_client_for_edition(
            settings,
            detected_edition,
            read_only=read_only,
        )

    statuses = _dependency_statuses()
    _log_incompatible_dependencies(statuses)
    available_editions = _available_editions(statuses)
    if not available_editions:
        incompatibility_error = _incompatible_clients_error(statuses)
        if incompatibility_error is not None:
            raise incompatibility_error

        raise ConfigurationError(
            "No compatible TimeBase client is installed. Install or upgrade timebase-mcp[community] or timebase-mcp[enterprise]."
        )

    return _create_auto_detected_client(
        settings,
        read_only=read_only,
        available_editions=available_editions,
    )


def get_detected_edition(settings: MCPSettings) -> Edition | None:
    if settings.detected_edition is not None:
        return settings.detected_edition

    if settings.oauth2_config is not None:
        return "enterprise"

    available_editions = _available_editions()
    if len(available_editions) == 1:
        return available_editions[0]

    return None


def _create_auto_detected_client(
    settings: MCPSettings,
    *,
    read_only: bool,
    available_editions: tuple[Edition, ...],
) -> TimeBaseClient:
    preferred_edition = available_editions[0]
    client = _create_client_for_edition(
        settings,
        preferred_edition,
        read_only=read_only,
    )

    try:
        client.open()
    except TimeBaseConnectionError as exc:
        client.close()
        if not _is_protocol_mismatch(str(exc)):
            raise

        fallback_edition: Edition = (
            "community" if preferred_edition == "enterprise" else "enterprise"
        )
        if fallback_edition not in available_editions:
            raise _required_client_error(settings, fallback_edition) from exc

        logger.info(
            "Retrying TimeBase connection to %s with %s client after protocol mismatch",
            settings.tb_url,
            fallback_edition,
        )

        client = _create_client_for_edition(
            settings,
            fallback_edition,
            read_only=read_only,
        )
        client.open()
        preferred_edition = fallback_edition
    except Exception as exc:
        client.close()
        logger.debug(
            "Unexpected error when connecting with %s client: %s",
            preferred_edition,
            exc,
        )
        raise

    settings.set_detected_edition(preferred_edition)
    return client


def _create_client_for_edition(
    settings: MCPSettings,
    edition: Edition,
    *,
    read_only: bool,
) -> TimeBaseClient:
    logger.debug("Using %s client for %s", edition, settings.tb_url)
    status = _dependency_status(edition)
    if not status.installed:
        raise ConfigurationError(
            f"{_EDITION_INFO[edition].label} edition requires installing {_EDITION_INFO[edition].extra_name}"
        )
    if status.error is not None:
        raise status.error

    client_class = _load_client_class(edition)
    return client_class(settings, read_only=read_only)


def _load_client_class(edition: Edition) -> type[TimeBaseClient]:
    info = _EDITION_INFO[edition]
    module = import_module(info.client_module)
    return cast(type[TimeBaseClient], getattr(module, info.client_class))


def _available_editions(
    statuses: dict[Edition, _DependencyStatus] | None = None,
) -> tuple[Edition, ...]:
    if statuses is None:
        statuses = _dependency_statuses()

    return tuple(
        edition for edition in _AUTO_EDITION_ORDER if statuses[edition].compatible
    )


def _is_protocol_mismatch(message: str) -> bool:
    normalized_message = message.casefold()
    return any(marker in normalized_message for marker in _PROTOCOL_MISMATCH_MARKERS)


def _required_client_error(
    settings: MCPSettings,
    edition: Edition,
) -> ConfigurationError:
    status = _dependency_status(edition)
    if status.error is not None:
        return status.error

    return ConfigurationError(
        f"TimeBase server at '{settings.tb_url}' requires the {edition} client. Install {_EDITION_INFO[edition].extra_name}."
    )


def _dependency_statuses() -> dict[Edition, _DependencyStatus]:
    return {edition: _dependency_status(edition) for edition in _AUTO_EDITION_ORDER}


def _dependency_status(edition: Edition) -> _DependencyStatus:
    info = _EDITION_INFO[edition]
    if not _has_dependency(info.module_name):
        return _DependencyStatus(installed=False)

    requirement = _dependency_requirement(info.distribution_name, edition)
    if requirement is None:
        return _DependencyStatus(installed=True)

    try:
        installed_version = metadata.version(info.distribution_name)
    except metadata.PackageNotFoundError:
        return _DependencyStatus(
            installed=True,
            error=ConfigurationError(
                f"{info.label} edition requires installing {info.extra_name}; found importable module "
                f"{info.module_name!r}, but package metadata for {info.distribution_name!r} is unavailable."
            ),
        )

    if requirement.specifier and not requirement.specifier.contains(
        installed_version,
        prereleases=True,
    ):
        return _DependencyStatus(
            installed=True,
            error=ConfigurationError(
                f"{info.label} edition requires {requirement.name}{requirement.specifier}; "
                f"found {info.distribution_name} {installed_version}. Install or upgrade {info.extra_name}."
            ),
        )

    return _DependencyStatus(installed=True)


def _incompatible_clients_error(
    statuses: dict[Edition, _DependencyStatus],
) -> ConfigurationError | None:
    messages = [
        str(status.error)
        for status in (statuses[edition] for edition in _AUTO_EDITION_ORDER)
        if status.installed and status.error is not None
    ]
    if not messages:
        return None

    return ConfigurationError(" ".join(messages))


def _log_incompatible_dependencies(statuses: dict[Edition, _DependencyStatus]) -> None:
    for edition in _AUTO_EDITION_ORDER:
        status = statuses[edition]
        if status.error is not None:
            logger.warning(
                "Ignoring incompatible %s TimeBase client: %s", edition, status.error
            )


def _dependency_requirement(distribution_name: str, extra: str) -> Requirement | None:
    try:
        requirements = metadata.requires(_DIST_NAME) or []
    except metadata.PackageNotFoundError:
        return None

    expected_name = canonicalize_name(distribution_name)
    environment = cast(dict[str, str], default_environment()) | {"extra": extra}

    for requirement_text in requirements:
        try:
            requirement = Requirement(requirement_text)
        except InvalidRequirement:
            continue

        if canonicalize_name(requirement.name) != expected_name:
            continue

        if requirement.marker is not None and not requirement.marker.evaluate(
            environment
        ):
            continue

        return requirement

    return None


def _has_dependency(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None
