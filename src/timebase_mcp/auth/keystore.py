"""Hashed API key store for inbound bearer authentication.

The server is a read-only consumer: it loads a JSON store of hashed keys and
verifies presented bearer tokens against it. Keys are generated and managed
out-of-band by the CLI.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

KEY_PREFIX = "tbk_"
_HASH_PREFIX = "sha256:"
_STORE_VERSION = 1
_KEY_ENTROPY_BYTES = 32


@dataclass(frozen=True, slots=True)
class ApiKeyRecord:
    id: str
    name: str
    hash: str
    scopes: tuple[str, ...] = ()
    created_at: str | None = None

    def to_json(self) -> dict[str, Any]:
        data: dict[str, Any] = {
            "id": self.id,
            "name": self.name,
            "hash": self.hash,
            "scopes": list(self.scopes),
        }
        if self.created_at is not None:
            data["created_at"] = self.created_at
        return data


def hash_key(raw_key: str) -> str:
    digest = hashlib.sha256(raw_key.encode("utf-8")).hexdigest()
    return f"{_HASH_PREFIX}{digest}"


def generate_key() -> str:
    """Generate a fresh, URL-safe API key with an identifying prefix."""
    return f"{KEY_PREFIX}{secrets.token_urlsafe(_KEY_ENTROPY_BYTES)}"


def generate_id() -> str:
    """Generate a short, stable record id."""
    return secrets.token_hex(4)


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_record(*, name: str, scopes: Sequence[str]) -> tuple[ApiKeyRecord, str]:
    raw_key = generate_key()
    record = ApiKeyRecord(
        id=generate_id(),
        name=name,
        hash=hash_key(raw_key),
        scopes=tuple(scopes),
        created_at=_utc_now_iso(),
    )
    return record, raw_key


def _parse_record(entry: Any) -> ApiKeyRecord:
    if not isinstance(entry, dict):
        raise ValueError("Each API key entry must be a JSON object.")

    id_ = entry.get("id")
    name = entry.get("name")
    hash_ = entry.get("hash")
    scopes = entry.get("scopes", [])
    created_at = entry.get("created_at")

    if not isinstance(id_, str) or not id_:
        raise ValueError("API key entry requires a non-empty 'id'.")
    if not isinstance(name, str) or not name:
        raise ValueError(f"API key '{id_}' requires a non-empty 'name'.")
    if not isinstance(hash_, str) or not hash_.startswith(_HASH_PREFIX):
        raise ValueError(
            f"API key '{id_}' requires a 'hash' of the form 'sha256:<hexdigest>'."
        )
    if not isinstance(scopes, list) or not all(isinstance(s, str) for s in scopes):
        raise ValueError(f"API key '{id_}' scopes must be a list of strings.")
    if created_at is not None and not isinstance(created_at, str):
        raise ValueError(f"API key '{id_}' 'created_at' must be a string.")

    return ApiKeyRecord(
        id=id_,
        name=name,
        hash=hash_,
        scopes=tuple(scopes),
        created_at=created_at,
    )


def parse_store(data: Any) -> tuple[ApiKeyRecord, ...]:
    """Validate and parse the in-memory representation of a key store."""
    if not isinstance(data, dict):
        raise ValueError("API key store must be a JSON object.")

    version = data.get("version")
    if version != _STORE_VERSION:
        raise ValueError(
            f"Unsupported API key store version {version!r} (expected {_STORE_VERSION})."
        )

    keys = data.get("keys")
    if not isinstance(keys, list):
        raise ValueError("API key store 'keys' must be a list.")

    records = tuple(_parse_record(entry) for entry in keys)
    ids = [record.id for record in records]
    if len(set(ids)) != len(ids):
        raise ValueError("API key store contains duplicate key ids.")
    return records


def load_store(path: str | Path) -> tuple[ApiKeyRecord, ...]:
    """Read and parse a key store from disk. Raises ``ValueError`` if invalid."""
    text = Path(path).read_text(encoding="utf-8")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError(f"API key store at {path} is not valid JSON: {exc}") from exc
    return parse_store(data)


def _dump_store(records: Sequence[ApiKeyRecord]) -> str:
    payload = {"version": _STORE_VERSION, "keys": [r.to_json() for r in records]}
    return json.dumps(payload, indent=2) + "\n"


def read_store_for_edit(path: Path) -> list[ApiKeyRecord]:
    """Read existing records for an edit; an absent file is an empty store."""
    if not path.exists():
        return []
    return list(load_store(path))


def write_store(path: Path, records: Sequence[ApiKeyRecord]) -> None:
    """Persist records to disk with owner-only permissions."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as handle:
        handle.write(_dump_store(records))
    os.chmod(path, 0o600)


def add_key(
    *, path: Path, name: str, scopes: Sequence[str]
) -> tuple[ApiKeyRecord, str]:
    """Generate a key, append its hashed record to the store, return both."""
    records = read_store_for_edit(path)
    record, raw_key = build_record(name=name, scopes=scopes)
    while any(existing.id == record.id for existing in records):
        record, raw_key = build_record(name=name, scopes=scopes)
    records.append(record)
    write_store(path, records)
    return record, raw_key


def remove_keys(*, path: Path, identifier: str) -> list[ApiKeyRecord]:
    """Remove records matching ``identifier`` (by id or name). Returns removed."""
    records = read_store_for_edit(path)
    removed = [r for r in records if r.id == identifier or r.name == identifier]
    if not removed:
        return []
    remaining = [r for r in records if r not in removed]
    write_store(path, remaining)
    return removed


class KeyStore:
    """Lazily (re)loads a key store file, caching by stat signature.

    The store is re-read only when its mtime/size changes, so rotating a mounted
    Secret applies without a restart. A missing or invalid store logs once and
    behaves as an empty store.
    """

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._records: tuple[ApiKeyRecord, ...] = ()
        self._signature: tuple[int, int] | None = None
        self._error_signature: str | None = None

    def records(self) -> tuple[ApiKeyRecord, ...]:
        try:
            stat = self._path.stat()
        except OSError as exc:
            self._on_error(f"unavailable: {exc}")
            return ()

        signature = (stat.st_mtime_ns, stat.st_size)
        if signature == self._signature:
            return self._records

        try:
            records = load_store(self._path)
        except ValueError as exc:
            self._signature = signature
            self._on_error(str(exc))
            return ()

        self._signature = signature
        self._records = records
        self._error_signature = None
        logger.info("Loaded %d API key(s) from %s.", len(records), self._path)
        return records

    def _on_error(self, message: str) -> None:
        self._records = ()
        if self._error_signature != message:
            logger.warning(
                "API key store %s is %s. Rejecting all API-key authentication.",
                self._path,
                message,
            )
            self._error_signature = message
        # Force a reload attempt next time a stat succeeds with a new signature.
        if message.startswith("unavailable"):
            self._signature = None
