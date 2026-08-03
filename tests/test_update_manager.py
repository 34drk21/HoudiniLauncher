from __future__ import annotations

import hashlib
import json
import sqlite3
from pathlib import Path

import pytest

from houd2launcher.application import load_or_create_launcher_settings
from houd2launcher.core.update_manager import UpdateManifest, UpdateService
from houd2launcher.database.connection import Database
from houd2launcher.database.migrations import migrate


def _write_channel(root: Path, version: str = "0.4.0") -> tuple[Path, bytes]:
    root.mkdir(parents=True)
    payload = b"mock windows installer\n" * 64
    installer = root / f"HouD2Launcher-{version}-Setup.exe"
    installer.write_bytes(payload)
    manifest = {
        "format": "houd2.update",
        "schema_version": 1,
        "version": version,
        "published_at": "2026-08-03T00:00:00Z",
        "installer_file": installer.name,
        "size_bytes": len(payload),
        "sha256": hashlib.sha256(payload).hexdigest(),
        "release_notes": "Test release",
    }
    (root / "latest.json").write_text(json.dumps(manifest), encoding="utf-8")
    return installer, payload


def test_update_check_and_stage_verify_shared_installer(tmp_path: Path) -> None:
    channel = tmp_path / "共有 Update Channel"
    _, payload = _write_channel(channel)
    service = UpdateService("0.3.0")

    update = service.check(channel)
    assert update is not None
    progress: list[int] = []
    staged = service.stage(
        update,
        tmp_path / "Local Data",
        lambda percent, _phase: progress.append(percent),
    )

    assert staged.read_bytes() == payload
    assert staged.parent.name == "0.4.0"
    assert progress[-1] == 100


def test_update_check_ignores_current_or_older_release(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    _write_channel(channel, "0.3.0")
    assert UpdateService("0.3.0").check(channel) is None


def test_update_manifest_refuses_nested_or_non_executable_paths() -> None:
    common = {
        "version": "0.4.0",
        "published_at": "2026-08-03T00:00:00Z",
        "size_bytes": 1,
        "sha256": "0" * 64,
    }
    with pytest.raises(ValueError):
        UpdateManifest.model_validate({**common, "installer_file": "..\\setup.exe"})
    with pytest.raises(ValueError):
        UpdateManifest.model_validate({**common, "installer_file": "setup.zip"})


def test_update_stage_rejects_checksum_mismatch(tmp_path: Path) -> None:
    channel = tmp_path / "channel"
    installer, _ = _write_channel(channel)
    service = UpdateService("0.3.0")
    update = service.check(channel)
    assert update is not None
    installer.write_bytes(b"x" * update.manifest.size_bytes)

    with pytest.raises(ValueError, match="checksum"):
        service.stage(update, tmp_path / "data")
    assert not list((tmp_path / "data").rglob("*.part"))


def test_update_backup_preserves_settings_and_consistent_database(tmp_path: Path) -> None:
    data_home = tmp_path / "data"
    settings = data_home / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text('{"display_name":"Artist"}', encoding="utf-8")
    database_path = data_home / "houd2launcher.db"
    database = Database(database_path)
    migrate(database)
    with database.connect() as connection:
        connection.execute("INSERT INTO ui_state(key, value) VALUES ('view', 'cards')")

    backup = UpdateService.backup_local_state(
        data_home, settings, database_path, "0.3.0", "0.4.0"
    )

    assert (backup / "settings.json").read_text(encoding="utf-8") == settings.read_text(
        encoding="utf-8"
    )
    with sqlite3.connect(backup / "houd2launcher.db") as connection:
        assert connection.execute("SELECT value FROM ui_state WHERE key='view'").fetchone()[0] == "cards"


def test_first_run_settings_and_legacy_migration(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("houd2launcher.application.getpass.getuser", lambda: "Test Artist")
    fresh_path = tmp_path / "fresh" / "settings.json"
    fresh = load_or_create_launcher_settings(fresh_path)
    assert fresh.display_name == "Test Artist"
    assert fresh.initials == "TA"
    assert fresh.onboarding_completed is False

    legacy_path = tmp_path / "legacy" / "settings.json"
    legacy_path.parent.mkdir()
    legacy_path.write_text(
        json.dumps(
            {
                "format": "houd2.launcher_settings",
                "schema_version": 1,
                "display_name": "Existing Artist",
                "initials": "EA",
            }
        ),
        encoding="utf-8",
    )
    migrated = load_or_create_launcher_settings(legacy_path)
    assert migrated.onboarding_completed is True


def test_database_migration_records_schema_version(tmp_path: Path) -> None:
    database = Database(tmp_path / "index.db")
    migrate(database)
    with database.connect() as connection:
        assert connection.execute("PRAGMA user_version").fetchone()[0] == 1
    migrate(database)
