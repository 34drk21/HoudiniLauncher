from __future__ import annotations

import hashlib
import os
import re
import shutil
import sqlite3
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator


UpdateProgress = Callable[[int, str], None]
_VERSION = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_SHA256 = re.compile(r"^[0-9a-fA-F]{64}$")


class UpdateManifest(BaseModel):
    """Validated metadata describing one shared-folder Launcher release."""

    model_config = ConfigDict(extra="forbid")
    format: Literal["houd2.update"] = "houd2.update"
    schema_version: Literal[1] = 1
    version: str
    published_at: datetime
    installer_file: str
    size_bytes: int = Field(ge=1)
    sha256: str
    release_notes: str = ""

    @field_validator("version")
    @classmethod
    def validate_version(cls, value: str) -> str:
        if not _VERSION.fullmatch(value):
            raise ValueError("Version must use major.minor.patch")
        return value

    @field_validator("installer_file")
    @classmethod
    def validate_installer_file(cls, value: str) -> str:
        if (
            not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            or not value.casefold().endswith(".exe")
        ):
            raise ValueError("Installer must be one EXE filename")
        return value

    @field_validator("sha256")
    @classmethod
    def validate_sha256(cls, value: str) -> str:
        if not _SHA256.fullmatch(value):
            raise ValueError("Installer SHA-256 is invalid")
        return value.lower()


@dataclass(frozen=True, slots=True)
class AvailableUpdate:
    manifest: UpdateManifest
    channel_root: Path
    installer_path: Path


class UpdateService:
    """Check and stage private Launcher updates from a shared folder."""

    def __init__(self, current_version: str) -> None:
        self.current_version = current_version
        _version_key(current_version)

    def check(self, channel_root: Path) -> AvailableUpdate | None:
        root = channel_root.expanduser().resolve()
        if not root.is_dir():
            raise FileNotFoundError(f"Update Channel is unavailable: {root}")
        manifest_path = root / "latest.json"
        manifest = UpdateManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        installer = (root / manifest.installer_file).resolve()
        _ensure_within(root, installer)
        if not installer.is_file():
            raise FileNotFoundError(f"Update Installer is missing: {installer}")
        if installer.stat().st_size != manifest.size_bytes:
            raise ValueError("Update Installer size does not match latest.json")
        if _version_key(manifest.version) <= _version_key(self.current_version):
            return None
        return AvailableUpdate(manifest, root, installer)

    def stage(
        self,
        update: AvailableUpdate,
        data_home: Path,
        progress: UpdateProgress | None = None,
    ) -> Path:
        source = update.installer_path.resolve()
        _ensure_within(update.channel_root, source)
        manifest = update.manifest
        destination_root = data_home / "updates" / manifest.version
        destination_root.mkdir(parents=True, exist_ok=True)
        destination = destination_root / manifest.installer_file
        if destination.is_file() and _matches_manifest(destination, manifest):
            if progress:
                progress(100, "Update Ready")
            return destination

        temporary = destination.with_suffix(destination.suffix + ".part")
        temporary.unlink(missing_ok=True)
        digest = hashlib.sha256()
        copied = 0
        last_percent = -1
        try:
            with source.open("rb") as source_stream, temporary.open("wb") as target:
                for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                    target.write(chunk)
                    digest.update(chunk)
                    copied += len(chunk)
                    percent = min(99, int(copied * 100 / manifest.size_bytes))
                    if progress and percent != last_percent:
                        progress(percent, "Copying Launcher Update")
                        last_percent = percent
            if copied != manifest.size_bytes or digest.hexdigest() != manifest.sha256:
                raise ValueError("Update Installer checksum verification failed")
            os.replace(temporary, destination)
        except Exception:
            temporary.unlink(missing_ok=True)
            raise
        if progress:
            progress(100, "Update Ready")
        return destination

    @staticmethod
    def backup_local_state(
        data_home: Path,
        settings_path: Path,
        database_path: Path,
        from_version: str,
        to_version: str,
    ) -> Path:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        root = data_home / "updates" / "backups" / f"{from_version}_to_{to_version}_{timestamp}"
        root.mkdir(parents=True, exist_ok=False)
        if settings_path.is_file():
            shutil.copy2(settings_path, root / "settings.json")
        if database_path.is_file():
            with sqlite3.connect(database_path) as source, sqlite3.connect(
                root / "houd2launcher.db"
            ) as target:
                source.backup(target)
        return root

    @staticmethod
    def launch_installer(path: Path) -> subprocess.Popen[bytes]:
        if not path.is_file() or path.suffix.casefold() != ".exe":
            raise FileNotFoundError(path)
        return subprocess.Popen([str(path)])


def _version_key(value: str) -> tuple[int, int, int]:
    match = _VERSION.fullmatch(value)
    if not match:
        raise ValueError(f"Invalid Launcher version: {value}")
    return tuple(int(part) for part in match.groups())  # type: ignore[return-value]


def _matches_manifest(path: Path, manifest: UpdateManifest) -> bool:
    return path.stat().st_size == manifest.size_bytes and _sha256(path) == manifest.sha256


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _ensure_within(root: Path, candidate: Path) -> None:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError(f"Update path escapes its Channel: {candidate}") from exc
