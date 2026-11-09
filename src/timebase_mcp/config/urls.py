from urllib.parse import unquote, urlparse, urlsplit, urlunsplit

from timebase_mcp.config.types import _HTTP_TRANSPORTS, Transport
from timebase_mcp.constants import LOOPBACK_HOSTS


def sanitize_url_for_log(value: str) -> str:
    try:
        parsed = urlsplit(value)
        # An unescaped slash in credentials can put the password in the path.
        if parsed.scheme and parsed.netloc and "@" not in parsed.path:
            authority = parsed.netloc.rsplit("@", 1)[-1]
            for node in authority.split("|"):
                node_url = urlsplit("//" + node)
                _ = node_url.port  # urllib validates ports when this property is read.
                if not node_url.hostname:
                    return "**********"
            return urlunsplit((parsed.scheme, authority, parsed.path, "", ""))
    except ValueError:
        pass
    return "**********"


def split_authority_and_suffix(value: str) -> tuple[str, str]:
    delimiter_positions = [value.find(delimiter) for delimiter in ("/", "?", "#")]
    valid_positions = [position for position in delimiter_positions if position >= 0]
    if not valid_positions:
        return value, ""

    authority_end = min(valid_positions)
    return value[:authority_end], value[authority_end:]


def extract_timebase_url_credentials(
    tb_url: str,
) -> tuple[str, str | None, str | None]:
    prefix = ""
    remainder = tb_url
    if "://" in tb_url:
        scheme, remainder = tb_url.split("://", 1)
        prefix = f"{scheme}://"

    authority, suffix = split_authority_and_suffix(remainder)
    if "@" not in authority:
        return tb_url, None, None

    userinfo, host_part = authority.rsplit("@", 1)
    if not userinfo or not host_part:
        return tb_url, None, None

    username_part, separator, password_part = userinfo.partition(":")
    username = unquote(username_part)
    password = unquote(password_part) if separator else None
    sanitized_url = f"{prefix}{host_part}{suffix}"
    return sanitized_url, username, password


def is_loopback_host(host: str) -> bool:
    return host in LOOPBACK_HOSTS


def is_remote_http_bind(*, transport: Transport, host: str) -> bool:
    return transport in _HTTP_TRANSPORTS and not is_loopback_host(host)


def is_loopback_or_local_url(value: str) -> bool:
    try:
        parsed = urlparse(value)
    except ValueError:
        return False
    host = parsed.hostname
    return host is not None and is_loopback_host(host)


def is_https_url(value: str) -> bool:
    try:
        return urlparse(value).scheme.casefold() == "https"
    except ValueError:
        return False
