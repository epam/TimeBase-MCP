from __future__ import annotations

import re
from collections.abc import Sequence
from urllib.parse import quote, urlsplit

from timebase_mcp.config.env import dxapi_ssl_termination_enabled

_AUTHORITY_RE = re.compile(r"^[a-zA-Z0-9.+-]+://([^/?#]+)")
_SCHEME_RE = re.compile(r"^([a-zA-Z0-9.+-]+)://")
_SSL_SCHEMES = frozenset({"dstick", "dsctick"})


def _normalize_http_base_url(http_base_url: str) -> str:
    return http_base_url.rstrip("/")


def http_base_url_candidates(value: str | Sequence[str] | None) -> tuple[str, ...]:
    """Return ordered HTTP base URL candidates, preserving distinct paths."""
    if value is None:
        return ()
    if isinstance(value, str):
        candidates = (value,)
    else:
        candidates = tuple(value)

    return tuple(
        normalized
        for candidate in candidates
        if (normalized := _normalize_http_base_url(candidate))
    )


def quote_path_segment(value: str) -> str:
    """Escape a caller-supplied value used as a single URL path segment."""
    return quote(value, safe="")


def build_tb_url(http_base_url: str, endpoint: str) -> str:
    """Build a URL under TimeBase's /tb HTTP API.

    ``http_base_url`` may be the HTTP root or may already include a trailing
    ``/tb`` path, which is common behind reverse proxies.
    """
    base_url = _normalize_http_base_url(http_base_url)
    path = endpoint.strip("/")
    if path == "tb":
        path = ""
    elif path.startswith("tb/"):
        path = path[3:]

    tb_base = base_url if base_url.endswith("/tb") else base_url + "/tb"
    return tb_base if not path else tb_base + "/" + path


def derive_http_base_urls(tb_url: str) -> tuple[str, ...]:
    """Best-effort ordered HTTP base URL candidates for a TimeBase native URL."""
    match = _AUTHORITY_RE.match(tb_url)
    if match is None:
        return ()

    authority = match.group(1)
    if "|" in authority:
        return ()
    if not authority:
        return ()

    scheme_match = _SCHEME_RE.match(tb_url)
    scheme = scheme_match.group(1).casefold() if scheme_match is not None else ""
    https_first = dxapi_ssl_termination_enabled() or scheme in _SSL_SCHEMES
    schemes = ("https", "http") if https_first else ("http", "https")
    authorities = _derived_authorities(authority)

    return tuple(
        f"{http_scheme}://{candidate_authority}"
        for http_scheme in schemes
        for candidate_authority in authorities
    )


def _derived_authorities(first_node_authority: str) -> tuple[str, ...]:
    authorities = [first_node_authority]
    fallback_authority = _authority_with_port(first_node_authority, 8021)
    if _authority_port(first_node_authority) == 8011 and fallback_authority is not None:
        authorities.append(fallback_authority)
    return tuple(authorities)


def _authority_port(authority: str) -> int | None:
    try:
        return urlsplit("//" + authority).port
    except ValueError:
        return None


def _authority_with_port(authority: str, port: int) -> str | None:
    try:
        parsed = urlsplit("//" + authority)
    except ValueError:
        return None

    host = parsed.hostname
    if not host:
        return None

    if ":" in host and not host.startswith("["):
        host = f"[{host}]"

    return f"{host}:{port}"
