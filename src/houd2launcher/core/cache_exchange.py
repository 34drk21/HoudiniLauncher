from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Callable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from .cache_manager import CacheRecord
from .exceptions import PathSafetyError
from .models import ProjectSettings, TaskSettings
from .path_resolver import PathResolver


CacheImportProgress = Callable[[int, str], None]


class PublishedFile(BaseModel):
    model_config = ConfigDict(extra="forbid")
    path: str
    size: int = Field(ge=0)
    sha256: str


class CachePublishManifest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    format: str = "houd2.cache_publish"
    schema_version: int = 1
    publish_id: str = Field(default_factory=lambda: str(uuid4()))
    published_at: str
    project_id: str
    project_name: str
    task_id: str
    task_name: str
    cache_id: str
    cache_name: str
    version: int
    source_manifest: dict[str, object] = Field(default_factory=dict)
    files: list[PublishedFile]


@dataclass(frozen=True, slots=True)
class PublishedCacheRecord:
    manifest_path: Path
    manifest: CachePublishManifest

    @property
    def payload_root(self) -> Path:
        return self.manifest_path.parent / "payload"


@dataclass(frozen=True, slots=True)
class CacheImportResult:
    path: Path
    source_deleted: bool
    warning: str = ""


class CacheExchangeService:
    """Publish and import immutable cache versions through a shared folder."""

    def __init__(self, resolver: PathResolver) -> None:
        self.resolver = resolver

    def publish(
        self,
        exchange_root: Path,
        project: ProjectSettings,
        task: TaskSettings,
        records: list[CacheRecord],
    ) -> tuple[PublishedCacheRecord, ...]:
        if not records:
            raise ValueError("Select at least one Cache Version")
        exchange_root = exchange_root.expanduser().resolve()
        exchange_root.mkdir(parents=True, exist_ok=True)
        geo_root = self.resolver.resolve_role(project, task, "geo_cache").resolve()
        results: list[PublishedCacheRecord] = []
        for record in records:
            if record.version is None or not record.path.is_dir():
                raise ValueError(f"Cache {record.name} has no publishable Version folder")
            source = record.path.resolve()
            _ensure_within(geo_root, source)
            cache_id, source_manifest = _cache_identity(source, project, task, record)
            destination = (
                exchange_root
                / f"{_slug(project.name)}__{project.project_id[:8]}"
                / f"{_slug(task.name)}__{task.task_id[:8]}"
                / _slug(record.name)
                / f"v{record.version:03d}__{cache_id[:8]}"
            )
            staging = destination.with_name(destination.name + f".__writing__.{uuid4().hex}")
            try:
                payload = staging / "payload"
                shutil.copytree(source, payload)
                files = _inventory(payload)
                manifest = CachePublishManifest(
                    published_at=datetime.now(timezone.utc).isoformat(),
                    project_id=project.project_id,
                    project_name=project.name,
                    task_id=task.task_id,
                    task_name=task.name,
                    cache_id=cache_id,
                    cache_name=record.name,
                    version=record.version,
                    source_manifest=source_manifest,
                    files=files,
                )
                (staging / "publish_manifest.json").write_text(
                    manifest.model_dump_json(indent=2), encoding="utf-8"
                )
                self._validate(staging)
                if destination.exists():
                    existing = self._validate(destination)
                    if _signature(existing.manifest) == _signature(manifest):
                        shutil.rmtree(staging)
                        results.append(existing)
                        continue
                    raise FileExistsError(f"Published Version already differs: {destination}")
                destination.parent.mkdir(parents=True, exist_ok=True)
                os.replace(staging, destination)
                results.append(self._validate(destination))
            except Exception:
                shutil.rmtree(staging, ignore_errors=True)
                raise
        return tuple(results)

    def discover(self, exchange_root: Path) -> tuple[PublishedCacheRecord, ...]:
        root = exchange_root.expanduser().resolve()
        if not root.is_dir():
            return ()
        records: list[PublishedCacheRecord] = []
        for path in root.rglob("publish_manifest.json"):
            if any(".__writing__." in part for part in path.parts):
                continue
            try:
                records.append(self._validate(path.parent))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return tuple(sorted(records, key=lambda item: (
            item.manifest.project_name.casefold(), item.manifest.task_name.casefold(),
            item.manifest.cache_name.casefold(), -item.manifest.version,
        )))

    def import_cache(
        self,
        published: PublishedCacheRecord,
        project: ProjectSettings,
        task: TaskSettings,
        *,
        delete_source: bool = True,
        progress: CacheImportProgress | None = None,
    ) -> CacheImportResult:
        package_root = published.manifest_path.parent.resolve()
        preview_manifest = CachePublishManifest.model_validate_json(
            (package_root / "publish_manifest.json").read_text(encoding="utf-8")
        )
        payload_size = max(sum(item.size for item in preview_manifest.files), 1)
        geo_root = self.resolver.resolve_role(project, task, "geo_cache").resolve()
        destination = (
            geo_root
            / preview_manifest.cache_name
            / f"v{preview_manifest.version:03d}"
        ).resolve()
        _ensure_within(geo_root, destination)
        stage_count = 4 if destination.exists() else 3
        completed_bytes = 0
        last_report: tuple[int, str] | None = None

        def report(phase: str, amount: int = 0, *, finish_stage: int | None = None) -> None:
            nonlocal completed_bytes, last_report
            completed_bytes += amount
            if finish_stage is not None:
                completed_bytes = max(completed_bytes, payload_size * finish_stage)
            percent = min(100, int(completed_bytes * 100 / (payload_size * stage_count)))
            state = (percent, phase)
            if progress and state != last_report:
                progress(percent, phase)
                last_report = state

        report("Validating Published Cache")
        checked = self._validate(
            package_root,
            on_bytes=lambda amount: report("Validating Published Cache", amount),
        )
        report("Validating Published Cache", finish_stage=1)
        manifest = checked.manifest
        if manifest.project_id != project.project_id or manifest.task_id != task.task_id:
            raise ValueError("Published Cache belongs to a different Project or Task")
        staging = destination.with_name(destination.name + f".__importing__.{uuid4().hex}")
        try:
            staging.parent.mkdir(parents=True, exist_ok=True)
            report("Copying to Local")
            _copytree_with_progress(
                checked.payload_root,
                staging,
                lambda amount: report("Copying to Local", amount),
            )
            report("Copying to Local", finish_stage=2)
            report("Verifying Local Cache")
            if _inventory(
                staging,
                lambda amount: report("Verifying Local Cache", amount),
            ) != manifest.files:
                raise ValueError("Imported payload checksum verification failed")
            report("Verifying Local Cache", finish_stage=3)
            if destination.exists():
                report("Checking Local Version")
                if _inventory(
                    destination,
                    lambda amount: report("Checking Local Version", amount),
                ) != manifest.files:
                    raise FileExistsError(f"Local Version already differs: {destination}")
                report("Checking Local Version", finish_stage=4)
                shutil.rmtree(staging)
            else:
                os.replace(staging, destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        source_deleted = False
        warning = ""
        if delete_source:
            try:
                shutil.rmtree(checked.manifest_path.parent)
                source_deleted = True
            except OSError as exc:
                warning = f"Imported locally, but could not remove the published copy: {exc}"
        if progress:
            progress(100, "Cache Import Complete")
        return CacheImportResult(destination, source_deleted, warning)

    def _validate(
        self,
        package_root: Path,
        on_bytes: Callable[[int], None] | None = None,
    ) -> PublishedCacheRecord:
        root = package_root.resolve()
        manifest_path = root / "publish_manifest.json"
        manifest = CachePublishManifest.model_validate_json(
            manifest_path.read_text(encoding="utf-8")
        )
        if manifest.format != "houd2.cache_publish" or manifest.schema_version != 1:
            raise ValueError("Unsupported published Cache format")
        payload = (root / "payload").resolve()
        _ensure_within(root, payload)
        if not payload.is_dir() or _inventory(payload, on_bytes) != manifest.files:
            raise ValueError("Published Cache is incomplete or corrupt")
        return PublishedCacheRecord(manifest_path, manifest)


def _cache_identity(
    version_root: Path,
    project: ProjectSettings,
    task: TaskSettings,
    record: CacheRecord,
) -> tuple[str, dict[str, object]]:
    path = version_root / "cache_manifest.json"
    if path.is_file():
        data = json.loads(path.read_text(encoding="utf-8"))
        cache_id = str(data.get("cache_id", "")).strip()
        if cache_id:
            return cache_id, data
    return f"legacy-{project.project_id[:8]}-{task.task_id[:8]}-{_slug(record.name)}-{record.version:03d}", {}


def _inventory(
    root: Path,
    on_bytes: Callable[[int], None] | None = None,
) -> list[PublishedFile]:
    result: list[PublishedFile] = []
    for path in sorted((item for item in root.rglob("*") if item.is_file()), key=lambda item: item.as_posix().casefold()):
        relative = PurePosixPath(*path.relative_to(root).parts).as_posix()
        result.append(
            PublishedFile(
                path=relative,
                size=path.stat().st_size,
                sha256=_sha256(path, on_bytes),
            )
        )
    return result


def _sha256(path: Path, on_bytes: Callable[[int], None] | None = None) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
            if on_bytes:
                on_bytes(len(chunk))
    return digest.hexdigest()


def _copytree_with_progress(
    source: Path,
    destination: Path,
    on_bytes: Callable[[int], None],
) -> None:
    """Copy a directory while reporting the number of payload bytes written."""
    destination.mkdir(parents=True, exist_ok=False)
    paths = sorted(source.rglob("*"), key=lambda item: item.as_posix().casefold())
    for path in paths:
        target = destination / path.relative_to(source)
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if not path.is_file():
            continue
        target.parent.mkdir(parents=True, exist_ok=True)
        with path.open("rb") as source_stream, target.open("wb") as target_stream:
            for chunk in iter(lambda: source_stream.read(1024 * 1024), b""):
                target_stream.write(chunk)
                on_bytes(len(chunk))
        shutil.copystat(path, target)


def _signature(manifest: CachePublishManifest) -> tuple[tuple[str, int, str], ...]:
    return tuple((item.path, item.size, item.sha256) for item in manifest.files)


def _slug(value: str) -> str:
    cleaned = "".join(character if character.isalnum() or character in "-_" else "_" for character in value.strip())
    return cleaned or "unnamed"


def _ensure_within(root: Path, candidate: Path) -> None:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PathSafetyError(f"Path escapes its managed root: {candidate}") from exc
