from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from timebase_mcp.auth import keystore


def parse_scopes(raw: str | None) -> list[str]:
    if not raw:
        return []
    return [scope for scope in raw.replace(",", " ").split() if scope]


def resolve_store_path(file_arg: str | None) -> Path | None:
    path = file_arg or os.environ.get("MCP_AUTH_API_KEYS_FILE")
    return Path(path) if path else None


def keys_generate(args: argparse.Namespace) -> int:
    scopes = parse_scopes(args.scopes)
    path = resolve_store_path(args.file)

    if args.stdout or path is None:
        record, raw_key = keystore.build_record(name=args.name, scopes=scopes)
        print(json.dumps(record.to_json(), indent=2))
        print(f"\nAPI key (shown once, store securely): {raw_key}", file=sys.stderr)
        if path is None and not args.stdout:
            print(
                "No key store path given (--file or MCP_AUTH_API_KEYS_FILE); the "
                "record above was not persisted.",
                file=sys.stderr,
            )
        return 0

    try:
        record, raw_key = keystore.add_key(path=path, name=args.name, scopes=scopes)
    except ValueError as exc:
        print(f"Failed to update key store {path}: {exc}", file=sys.stderr)
        return 1
    print(f"Added API key '{record.name}' (id {record.id}) to {path}.")
    print(f"API key (shown once, store securely): {raw_key}")
    return 0


def keys_list(args: argparse.Namespace) -> int:
    path = resolve_store_path(args.file)
    if path is None:
        print(
            "No key store specified. Use --file or set MCP_AUTH_API_KEYS_FILE.",
            file=sys.stderr,
        )
        return 2
    try:
        records = keystore.load_store(path) if path.exists() else ()
    except ValueError as exc:
        print(f"Invalid key store {path}: {exc}", file=sys.stderr)
        return 1
    if not records:
        print("No API keys.")
        return 0
    print(f"{'ID':<10} {'NAME':<24} {'SCOPES':<24} CREATED")
    for record in records:
        scopes = ",".join(record.scopes) or "-"
        print(
            f"{record.id:<10} {record.name:<24} {scopes:<24} {record.created_at or '-'}"
        )
    return 0


def keys_revoke(args: argparse.Namespace) -> int:
    path = resolve_store_path(args.file)
    if path is None:
        print(
            "No key store specified. Use --file or set MCP_AUTH_API_KEYS_FILE.",
            file=sys.stderr,
        )
        return 2
    if not path.exists():
        print(f"Key store {path} does not exist.", file=sys.stderr)
        return 1
    try:
        removed = keystore.remove_keys(path=path, identifier=args.identifier)
    except ValueError as exc:
        print(f"Invalid key store {path}: {exc}", file=sys.stderr)
        return 1
    if not removed:
        print(f"No API key matching '{args.identifier}'.", file=sys.stderr)
        return 1
    for record in removed:
        print(f"Revoked API key '{record.name}' (id {record.id}).")
    return 0
