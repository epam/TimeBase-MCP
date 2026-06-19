from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from timebase_mcp.auth import keystore
from timebase_mcp.main import _keys_generate, _keys_list, _keys_revoke


def test_hash_key_format() -> None:
    h = keystore.hash_key("any-key")
    assert h.startswith("sha256:")
    assert len(h) == len("sha256:") + 64


def test_hash_key_is_deterministic() -> None:
    assert keystore.hash_key("key") == keystore.hash_key("key")


def test_hash_key_differs_for_different_inputs() -> None:
    assert keystore.hash_key("key-a") != keystore.hash_key("key-b")


def test_generate_key_has_prefix() -> None:
    key = keystore.generate_key()
    assert key.startswith(keystore.KEY_PREFIX)


def test_generate_key_is_unique() -> None:
    assert keystore.generate_key() != keystore.generate_key()


def test_build_record_hash_matches_key() -> None:
    record, raw_key = keystore.build_record(name="alice", scopes=["read"])
    assert record.hash == keystore.hash_key(raw_key)
    assert record.name == "alice"
    assert record.scopes == ("read",)
    assert record.id
    assert record.created_at


def test_build_record_empty_scopes() -> None:
    record, _ = keystore.build_record(name="svc", scopes=[])
    assert record.scopes == ()


def test_write_and_load_roundtrip(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    r1, _ = keystore.build_record(name="alice", scopes=["read"])
    r2, _ = keystore.build_record(name="bob", scopes=[])
    keystore.write_store(path, [r1, r2])

    loaded = keystore.load_store(path)

    assert len(loaded) == 2
    assert loaded[0].id == r1.id
    assert loaded[0].name == r1.name
    assert loaded[0].hash == r1.hash
    assert loaded[0].scopes == r1.scopes
    assert loaded[1].id == r2.id


def test_write_store_creates_owner_only_file(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    keystore.write_store(path, [])

    mode = path.stat().st_mode & 0o777
    assert mode == 0o600


def test_write_store_empty_is_valid(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    keystore.write_store(path, [])

    loaded = keystore.load_store(path)
    assert loaded == ()


def test_load_store_raises_on_bad_json(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("not-json", encoding="utf-8")

    with pytest.raises(ValueError, match="not valid JSON"):
        keystore.load_store(path)


def test_load_store_raises_on_wrong_version(tmp_path: Path) -> None:
    path = tmp_path / "v2.json"
    path.write_text(json.dumps({"version": 99, "keys": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="version"):
        keystore.load_store(path)


def test_load_store_raises_on_duplicate_ids(tmp_path: Path) -> None:
    path = tmp_path / "dup.json"
    r, _ = keystore.build_record(name="alice", scopes=[])
    payload = {"version": 1, "keys": [r.to_json(), r.to_json()]}
    path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate"):
        keystore.load_store(path)


def test_add_key_appends_to_store(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    record, raw_key = keystore.add_key(path=path, name="alice", scopes=["read"])

    loaded = keystore.load_store(path)
    assert len(loaded) == 1
    assert loaded[0].id == record.id
    assert loaded[0].hash == keystore.hash_key(raw_key)


def test_add_key_appends_to_existing(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    keystore.add_key(path=path, name="alice", scopes=[])
    keystore.add_key(path=path, name="bob", scopes=[])

    loaded = keystore.load_store(path)
    assert len(loaded) == 2


def test_remove_keys_by_id(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    r1, _ = keystore.add_key(path=path, name="alice", scopes=[])
    keystore.add_key(path=path, name="bob", scopes=[])

    removed = keystore.remove_keys(path=path, identifier=r1.id)

    assert len(removed) == 1 and removed[0].id == r1.id
    remaining = keystore.load_store(path)
    assert len(remaining) == 1
    assert remaining[0].name == "bob"


def test_remove_keys_by_name(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    keystore.add_key(path=path, name="alice", scopes=[])

    removed = keystore.remove_keys(path=path, identifier="alice")

    assert len(removed) == 1
    assert keystore.load_store(path) == ()


def test_remove_keys_unknown_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    keystore.add_key(path=path, name="alice", scopes=[])

    removed = keystore.remove_keys(path=path, identifier="nobody")

    assert removed == []
    assert len(keystore.load_store(path)) == 1


def test_keystore_returns_records(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    r, _ = keystore.build_record(name="alice", scopes=["read"])
    keystore.write_store(path, [r])
    store = keystore.KeyStore(path)

    records = store.records()

    assert len(records) == 1
    assert records[0].name == "alice"


def test_keystore_missing_file_returns_empty(tmp_path: Path) -> None:
    store = keystore.KeyStore(tmp_path / "nonexistent.json")

    assert store.records() == ()


def test_keystore_invalid_file_returns_empty(tmp_path: Path) -> None:
    path = tmp_path / "bad.json"
    path.write_text("{invalid}", encoding="utf-8")
    store = keystore.KeyStore(path)

    assert store.records() == ()


def test_keystore_live_reload_on_file_change(tmp_path: Path) -> None:
    r1, _ = keystore.build_record(name="alice", scopes=[])
    path = tmp_path / "keys.json"
    keystore.write_store(path, [r1])
    store = keystore.KeyStore(path)

    v1 = store.records()
    assert len(v1) == 1 and v1[0].name == "alice"

    r2, _ = keystore.build_record(name="bob", scopes=[])
    keystore.write_store(path, [r2])

    v2 = store.records()
    assert len(v2) == 1 and v2[0].name == "bob"


def test_keystore_no_reload_when_unchanged(tmp_path: Path) -> None:
    path = tmp_path / "keys.json"
    r, _ = keystore.build_record(name="alice", scopes=[])
    keystore.write_store(path, [r])
    store = keystore.KeyStore(path)

    v1 = store.records()
    v2 = store.records()

    assert v1 is v2


def _args(**kwargs) -> argparse.Namespace:
    return argparse.Namespace(**kwargs)


def test_cli_generate_writes_to_file(
    tmp_path: Path, capsys: pytest.CaptureFixture
) -> None:
    path = tmp_path / "keys.json"
    args = _args(name="alice", scopes="timebase.read", file=str(path), stdout=False)

    exit_code = _keys_generate(args)

    assert exit_code == 0
    records = keystore.load_store(path)
    assert len(records) == 1
    assert records[0].name == "alice"
    assert records[0].scopes == ("timebase.read",)
    captured = capsys.readouterr()
    assert keystore.KEY_PREFIX in captured.out


def test_cli_generate_stdout_emits_json_and_key(
    capsys: pytest.CaptureFixture,
) -> None:
    args = _args(name="ci", scopes=None, file=None, stdout=True)

    exit_code = _keys_generate(args)

    assert exit_code == 0
    captured = capsys.readouterr()
    record_data = json.loads(captured.out)
    assert record_data["name"] == "ci"
    assert record_data["hash"].startswith("sha256:")
    assert keystore.KEY_PREFIX in captured.err


def test_cli_list_shows_records(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "keys.json"
    r, _ = keystore.build_record(name="alice", scopes=["timebase.read"])
    keystore.write_store(path, [r])

    exit_code = _keys_list(_args(file=str(path)))

    assert exit_code == 0
    out = capsys.readouterr().out
    assert "alice" in out
    assert "timebase.read" in out


def test_cli_list_empty_store(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    args = _args(file=str(tmp_path / "keys.json"))

    exit_code = _keys_list(args)

    assert exit_code == 0
    assert "No API keys" in capsys.readouterr().out


def test_cli_list_no_file_specified(capsys: pytest.CaptureFixture) -> None:
    exit_code = _keys_list(_args(file=None))

    assert exit_code == 2


def test_cli_revoke_removes_key(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    path = tmp_path / "keys.json"
    r, _ = keystore.build_record(name="alice", scopes=[])
    keystore.write_store(path, [r])

    exit_code = _keys_revoke(_args(identifier="alice", file=str(path)))

    assert exit_code == 0
    assert keystore.load_store(path) == ()


def test_cli_revoke_unknown_returns_nonzero(
    tmp_path: Path,
) -> None:
    path = tmp_path / "keys.json"
    r, _ = keystore.build_record(name="alice", scopes=[])
    keystore.write_store(path, [r])

    exit_code = _keys_revoke(_args(identifier="nobody", file=str(path)))

    assert exit_code == 1


def test_cli_revoke_no_file_specified() -> None:
    exit_code = _keys_revoke(_args(identifier="alice", file=None))

    assert exit_code == 2
