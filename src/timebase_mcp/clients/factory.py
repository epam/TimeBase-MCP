import logging
import importlib.util
from importlib import import_module
from typing import cast

from timebase_mcp.clients.base import TimeBaseClient
from timebase_mcp.config import Edition, MCPSettings
from timebase_mcp.errors import ConfigurationError, TimeBaseConnectionError

logger = logging.getLogger(__name__)

_ENTERPRISE_MODULE_NAME = "dxapi"
_COMMUNITY_MODULE_NAME = "dxapi_ce"
_AUTO_EDITION_ORDER: tuple[Edition, ...] = ("enterprise", "community")
_EDITION_DEPENDENCIES: dict[Edition, tuple[str, str]] = {
    "enterprise": (_ENTERPRISE_MODULE_NAME, "timebase-mcp[enterprise]"),
    "community": (_COMMUNITY_MODULE_NAME, "timebase-mcp[community]"),
}
_EDITION_CLIENTS: dict[Edition, tuple[str, str]] = {
    "enterprise": (
        "timebase_mcp.clients.enterprise",
        "EnterpriseTimeBaseClient",
    ),
    "community": (
        "timebase_mcp.clients.community",
        "CommunityTimeBaseClient",
    ),
}
_PROTOCOL_MISMATCH_MARKERS: tuple[str, ...] = (
    "enterprise version is required",
    "community version is required",
)


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

    available_editions = _available_editions()
    if not available_editions:
        raise ConfigurationError(
            "No TimeBase client is installed. Install timebase-mcp[community] or timebase-mcp[enterprise]."
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

        fallback_edition = _alternate_edition(preferred_edition)
        if fallback_edition not in available_editions:
            raise _missing_required_client_error(settings, fallback_edition) from exc

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
    client_class = _load_client_class(edition)

    match edition:
        case "enterprise":
            logger.debug(
                "Using enterprise client for %s",
                settings.tb_url,
            )
            _require_dependency(
                _ENTERPRISE_MODULE_NAME, "Enterprise", "timebase-mcp[enterprise]"
            )
            return client_class(settings, read_only=read_only)
        case "community":
            logger.debug(
                "Using community client for %s",
                settings.tb_url,
            )
            _require_dependency(
                _COMMUNITY_MODULE_NAME, "Community", "timebase-mcp[community]"
            )
            return client_class(settings, read_only=read_only)


def _load_client_class(edition: Edition) -> type[TimeBaseClient]:
    module_name, class_name = _EDITION_CLIENTS[edition]
    module = import_module(module_name)
    return cast(type[TimeBaseClient], getattr(module, class_name))


def _available_editions() -> tuple[Edition, ...]:
    return tuple(
        edition
        for edition in _AUTO_EDITION_ORDER
        if _has_dependency(_EDITION_DEPENDENCIES[edition][0])
    )


def _is_protocol_mismatch(message: str) -> bool:
    normalized_message = message.casefold()
    return any(marker in normalized_message for marker in _PROTOCOL_MISMATCH_MARKERS)


def _alternate_edition(edition: Edition) -> Edition:
    if edition == "enterprise":
        return "community"
    return "enterprise"


def _missing_required_client_error(
    settings: MCPSettings,
    edition: Edition,
) -> ConfigurationError:
    _, extra_name = _EDITION_DEPENDENCIES[edition]
    return ConfigurationError(
        f"TimeBase server at '{settings.tb_url}' requires the {edition} client. Install {extra_name}."
    )


def _require_dependency(module_name: str, edition: str, extra_name: str) -> None:
    if _has_dependency(module_name):
        return

    raise ConfigurationError(f"{edition} edition requires installing {extra_name}")


def _has_dependency(module_name: str) -> bool:
    return importlib.util.find_spec(module_name) is not None
