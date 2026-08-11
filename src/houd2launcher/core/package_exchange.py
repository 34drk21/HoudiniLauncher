from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Literal
from uuid import uuid4

from pydantic import Field

from .config import atomic_write_model, load_model
from .exceptions import PathSafetyError
from .models import HipMetadata, ProjectSettings, StrictModel, TaskSettings
from .path_resolver import PathResolver
from .project_manager import ProjectManager
from .task_manager import TaskManager
from .task_package import TaskPackagePreview, TaskPackageService


_SECRET_MARKERS = ("PASSWORD", "PASS", "TOKEN", "SECRET", "API_KEY", "CREDENTIAL")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")


class ExchangePackageFile(StrictModel):
    relative_path: str
    size: int = Field(ge=0)
    modified_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class ExchangePackageManifest(StrictModel):
    format: Literal["houd2.package_exchange"] = "houd2.package_exchange"
    schema_version: Literal[1] = 1
    package_id: str = Field(default_factory=lambda: str(uuid4()))
    package_kind: Literal["project", "task"]
    published_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    publisher_user_id: str = ""
    publisher_name: str = ""
    source_project_id: str
    source_project_name: str
    source_task_id: str | None = None
    source_task_name: str | None = None
    excluded_roles: list[str] = Field(default_factory=list)
    files: list[ExchangePackageFile] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class PublishedPackageRecord:
    manifest_path: Path
    manifest: ExchangePackageManifest

    @property
    def package_root(self) -> Path:
        return self.manifest_path.parent

    @property
    def payload_root(self) -> Path:
        return self.package_root / "payload"

    @property
    def total_size(self) -> int:
        return sum(item.size for item in self.manifest.files)


@dataclass(frozen=True, slots=True)
class PackageImportPreview:
    published: PublishedPackageRecord
    target_root: Path
    target_name: str
    target_id: str
    renamed: bool
    total_size: int
    file_count: int
    task_preview: TaskPackagePreview | None = None


@dataclass(frozen=True, slots=True)
class PackageImportResult:
    package_kind: Literal["project", "task"]
    path: Path
    project: ProjectSettings
    task: TaskSettings | None = None


class PackageExchangeService:
    """Publish and import immutable Project and Task snapshots."""

    def __init__(
        self,
        resolver: PathResolver,
        projects: ProjectManager,
        tasks: TaskManager,
        task_packages: TaskPackageService,
    ) -> None:
        self.resolver = resolver
        self.projects = projects
        self.tasks = tasks
        self.task_packages = task_packages

    def publish_task(
        self,
        exchange_root: Path,
        project: ProjectSettings,
        task: TaskSettings,
        *,
        publisher_user_id: str = "",
        publisher_name: str = "",
    ) -> PublishedPackageRecord:
        exchange = self._prepare_exchange_root(exchange_root)
        source_root = self.resolver.resolve_task_root(project, task.name)
        _reject_link(source_root)
        _reject_nested_destination(source_root, exchange)
        package_id = str(uuid4())
        destination = self._destination(
            exchange, "tasks", project.name, project.project_id, task.name, package_id
        )
        staging = destination.with_name(destination.name + f".__writing__.{uuid4().hex}")
        try:
            staging.mkdir(parents=True)
            nested = self.task_packages.export(project, task, staging / "build")
            os.replace(nested, staging / "payload")
            shutil.rmtree(staging / "build")
            task_manifest = json.loads(
                (staging / "payload" / "manifest.json").read_text(encoding="utf-8")
            )
            manifest = ExchangePackageManifest(
                package_id=package_id,
                package_kind="task",
                publisher_user_id=publisher_user_id,
                publisher_name=publisher_name,
                source_project_id=project.project_id,
                source_project_name=project.name,
                source_task_id=task.task_id,
                source_task_name=task.name,
                excluded_roles=list(task_manifest.get("excluded_roles", [])),
                files=_inventory(staging / "payload"),
            )
            atomic_write_model(staging / "exchange_manifest.json", manifest)
            self._validate(staging)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
            return self._validate(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def publish_project(
        self,
        exchange_root: Path,
        project: ProjectSettings,
        *,
        publisher_user_id: str = "",
        publisher_name: str = "",
    ) -> PublishedPackageRecord:
        exchange = self._prepare_exchange_root(exchange_root)
        source_root = self.resolver.resolve_project_root(project)
        _reject_link(source_root)
        _reject_nested_destination(source_root, exchange)
        package_id = str(uuid4())
        destination = self._destination(
            exchange, "projects", project.name, project.project_id, None, package_id
        )
        staging = destination.with_name(destination.name + f".__writing__.{uuid4().hex}")
        payload = staging / "payload"
        task_builds = staging / "task_builds"
        try:
            payload.mkdir(parents=True)
            task_builds.mkdir()
            tasks = self._source_tasks(project)
            task_folders = {task.name.casefold() for task in tasks}
            for source in sorted(source_root.iterdir(), key=lambda item: item.name.casefold()):
                if source.name.casefold() in task_folders or source.name == ".trash":
                    continue
                if source.name == ".houd2":
                    _copy_tree(source, payload / source.name, skip_names={"project.json"})
                elif source.is_dir():
                    _copy_tree(source, payload / source.name)
                elif source.is_file():
                    _reject_link(source)
                    shutil.copy2(source, payload / source.name)
                else:
                    _reject_link(source)

            excluded_roles: set[str] = set()
            for task in tasks:
                nested = self.task_packages.export(project, task, task_builds)
                nested_manifest = json.loads(
                    (nested / "manifest.json").read_text(encoding="utf-8")
                )
                excluded_roles.update(nested_manifest.get("excluded_roles", []))
                shutil.copytree(nested / "task", payload / task.name)
                shutil.rmtree(nested)

            project_config = payload / ".houd2" / "project.json"
            project_config.parent.mkdir(parents=True, exist_ok=True)
            project_config.write_text(
                json.dumps(_portable_project(project), indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            shutil.rmtree(task_builds)
            manifest = ExchangePackageManifest(
                package_id=package_id,
                package_kind="project",
                publisher_user_id=publisher_user_id,
                publisher_name=publisher_name,
                source_project_id=project.project_id,
                source_project_name=project.name,
                excluded_roles=sorted(excluded_roles),
                files=_inventory(payload),
            )
            atomic_write_model(staging / "exchange_manifest.json", manifest)
            self._validate(staging)
            destination.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, destination)
            return self._validate(destination)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise

    def discover(self, exchange_root: Path) -> tuple[PublishedPackageRecord, ...]:
        root = exchange_root.expanduser().resolve()
        if not root.is_dir():
            return ()
        records: list[PublishedPackageRecord] = []
        for manifest_path in root.rglob("exchange_manifest.json"):
            if any(".__writing__." in part for part in manifest_path.parts):
                continue
            try:
                records.append(self._read_record(manifest_path.parent))
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return tuple(
            sorted(
                records,
                key=lambda item: item.manifest.published_at,
                reverse=True,
            )
        )

    def preview_import(
        self,
        published: PublishedPackageRecord,
        *,
        target_project: ProjectSettings | None = None,
        project_parent: Path | None = None,
    ) -> PackageImportPreview:
        checked = self._validate(published.package_root)
        manifest = checked.manifest
        if manifest.package_kind == "task":
            if target_project is None:
                raise ValueError("Select a target Project for this Task Package")
            task_preview = self.task_packages.preview_import(
                checked.payload_root, target_project
            )
            _ensure_free_space(target_project.project_root, checked.total_size)
            target_root = self.resolver.resolve_task_root(
                target_project, task_preview.target_task_name
            )
            _reject_nested_destination(checked.package_root, target_root)
            return PackageImportPreview(
                checked,
                target_root,
                task_preview.target_task_name,
                task_preview.target_task_id,
                task_preview.renamed,
                checked.total_size,
                len(manifest.files),
                task_preview,
            )

        if project_parent is None:
            raise ValueError("Select a local destination for this Project Package")
        parent = project_parent.expanduser().resolve()
        parent.mkdir(parents=True, exist_ok=True)
        _ensure_free_space(parent, checked.total_size)
        records = self.projects.repository.list_projects(include_archived=True)
        collision = any(
            str(item["project_id"]) == manifest.source_project_id
            or str(item["name"]).casefold() == manifest.source_project_name.casefold()
            for item in records
        )
        name = manifest.source_project_name
        if collision or (parent / name).exists():
            name = _copy_name(
                manifest.source_project_name,
                lambda candidate: (parent / candidate).exists()
                or any(str(item["name"]).casefold() == candidate.casefold() for item in records),
            )
        renamed = name != manifest.source_project_name or collision
        target_id = str(uuid4()) if renamed else manifest.source_project_id
        target_root = parent / name
        _reject_nested_destination(checked.package_root, target_root)
        return PackageImportPreview(
            checked,
            target_root,
            name,
            target_id,
            renamed,
            checked.total_size,
            len(manifest.files),
        )

    def import_package(
        self,
        preview: PackageImportPreview,
        *,
        target_project: ProjectSettings | None = None,
    ) -> PackageImportResult:
        checked = self._validate(preview.published.package_root)
        if checked.manifest.package_id != preview.published.manifest.package_id:
            raise ValueError("Published Package changed after Preview")
        if checked.manifest.package_kind == "task":
            if target_project is None or preview.task_preview is None:
                raise ValueError("Target Project is required for a Task Package")
            task = self.task_packages.import_package(
                checked.payload_root, target_project, preview.task_preview
            )
            return PackageImportResult("task", preview.target_root, target_project, task)
        return self._import_project(checked, preview)

    def _import_project(
        self, published: PublishedPackageRecord, preview: PackageImportPreview
    ) -> PackageImportResult:
        final = preview.target_root.resolve()
        if final.exists():
            raise FileExistsError(f"Project already exists: {final}")
        staging = final.with_name(f".{final.name}.import-{uuid4().hex}")
        try:
            shutil.copytree(published.payload_root, staging)
            config_path = staging / ".houd2" / "project.json"
            raw = json.loads(config_path.read_text(encoding="utf-8"))
            raw["project_root"] = str(final)
            raw["name"] = preview.target_name
            raw["project_id"] = preview.target_id
            project = ProjectSettings.model_validate(raw)
            task_ids_in_use = self._all_task_ids()
            for task_config in sorted(staging.glob("*/.houd2/task.json")):
                task = load_model(task_config, TaskSettings)
                replace_id = preview.renamed or task.task_id in task_ids_in_use
                task.project_id = project.project_id
                if replace_id:
                    task.task_id = str(uuid4())
                task.recommended_installation_id = None
                self._rewrite_hip_metadata(task_config.parent.parent, task)
                atomic_write_model(task_config, task)
            atomic_write_model(config_path, project)
            os.replace(staging, final)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        loaded = self.projects.add_existing(final)
        for task in self.tasks.discover(loaded):
            self.tasks.repository.record_activity(
                loaded.project_id,
                "project_package_task_imported",
                {"package_id": published.manifest.package_id, "name": task.name},
                task.task_id,
            )
        self.projects.repository.record_activity(
            loaded.project_id,
            "project_package_imported",
            {"package_id": published.manifest.package_id, "name": loaded.name},
        )
        return PackageImportResult("project", final, loaded)

    def _source_tasks(self, project: ProjectSettings) -> list[TaskSettings]:
        root = self.resolver.resolve_project_root(project)
        tasks: list[TaskSettings] = []
        for config in sorted(root.glob("*/.houd2/task.json")):
            task = load_model(config, TaskSettings)
            if config.parent.parent.name != task.name:
                raise ValueError(f"Task folder and settings name differ: {config}")
            if task.project_id != project.project_id:
                raise ValueError(f"Task belongs to a different Project: {task.name}")
            tasks.append(task)
        return tasks

    def _all_task_ids(self) -> set[str]:
        result: set[str] = set()
        for project in self.projects.repository.list_projects(include_archived=True):
            result.update(
                str(task["task_id"])
                for task in self.tasks.repository.list_tasks(str(project["project_id"]))
            )
        return result

    @staticmethod
    def _rewrite_hip_metadata(task_root: Path, task: TaskSettings) -> None:
        metadata_root = task_root / ".houd2" / "hips"
        if not metadata_root.is_dir():
            return
        for path in metadata_root.glob("*.json"):
            metadata = load_model(path, HipMetadata)
            metadata.task_id = task.task_id
            metadata.last_opened_with = None
            metadata.last_saved_with = None
            metadata.recommended_installation_id = None
            atomic_write_model(path, metadata)

    @staticmethod
    def _prepare_exchange_root(exchange_root: Path) -> Path:
        root = exchange_root.expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        return root

    @staticmethod
    def _destination(
        exchange: Path,
        kind_root: str,
        project_name: str,
        project_id: str,
        task_name: str | None,
        package_id: str,
    ) -> Path:
        destination = exchange / kind_root / f"{_slug(project_name)}__{project_id[:8]}"
        if task_name:
            destination /= _slug(task_name)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        return destination / f"{stamp}__{package_id[:8]}"

    def _validate(self, package_root: Path) -> PublishedPackageRecord:
        record = self._read_record(package_root)
        _validate_inventory(record.payload_root, record.manifest.files)
        return record

    def _read_record(self, package_root: Path) -> PublishedPackageRecord:
        _reject_link(package_root)
        root = package_root.expanduser().resolve()
        manifest_path = root / "exchange_manifest.json"
        raw_payload = root / "payload"
        _reject_link(raw_payload)
        payload = raw_payload.resolve()
        if not manifest_path.is_file() or not payload.is_dir():
            raise ValueError("Folder is not a complete HouD2 Exchange Package")
        manifest = load_model(manifest_path, ExchangePackageManifest)
        if manifest.format != "houd2.package_exchange" or manifest.schema_version != 1:
            raise ValueError("Unsupported Exchange Package format")
        if manifest.package_kind == "task":
            if not (payload / "manifest.json").is_file():
                raise ValueError("Task Exchange payload is incomplete")
        else:
            config = payload / ".houd2" / "project.json"
            if not config.is_file():
                raise ValueError("Project Exchange payload is incomplete")
            raw = json.loads(config.read_text(encoding="utf-8"))
            if raw.get("project_id") != manifest.source_project_id:
                raise ValueError("Manifest and Project settings do not match")
        return PublishedPackageRecord(manifest_path, manifest)


def _portable_project(project: ProjectSettings) -> dict[str, object]:
    data = project.model_dump(mode="json")
    data["project_root"] = "{import_root}"
    data["environment"] = {
        name: value
        for name, value in project.environment.items()
        if not any(marker in name.upper() for marker in _SECRET_MARKERS)
        and not _is_absolute_text(value)
    }
    data["search_paths"] = {
        name: [value for value in values if not _is_absolute_text(value)]
        for name, values in project.search_paths.model_dump(mode="python").items()
    }
    data["houdini"]["default_installation_id"] = None
    return data


def _inventory(root: Path) -> list[ExchangePackageFile]:
    files: list[ExchangePackageFile] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.as_posix().casefold()):
        _reject_link(path)
        if not path.is_file():
            continue
        stat = path.stat()
        files.append(
            ExchangePackageFile(
                relative_path=path.relative_to(root).as_posix(),
                size=stat.st_size,
                modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
                sha256=_sha256(path),
            )
        )
    return files


def _validate_inventory(root: Path, files: list[ExchangePackageFile]) -> None:
    declared: set[str] = set()
    for path in root.rglob("*"):
        _reject_link(path)
        _ensure_within(root, path)
    for entry in files:
        relative = _safe_relative(entry.relative_path)
        key = relative.as_posix().casefold()
        if key in declared:
            raise ValueError(f"Duplicate Package path: {entry.relative_path}")
        declared.add(key)
        candidate = root.joinpath(*relative.parts)
        _ensure_within(root, candidate)
        if not candidate.is_file():
            raise FileNotFoundError(f"Package file is missing: {entry.relative_path}")
        if candidate.stat().st_size != entry.size or _sha256(candidate) != entry.sha256:
            raise ValueError(f"Checksum mismatch: {entry.relative_path}")
    actual = {
        path.relative_to(root).as_posix().casefold()
        for path in root.rglob("*")
        if path.is_file()
    }
    if actual != declared:
        raise ValueError("Package file list does not match its payload")


def _copy_tree(source: Path, destination: Path, skip_names: set[str] | None = None) -> None:
    _reject_link(source)
    skip = {name.casefold() for name in (skip_names or set())}
    destination.mkdir(parents=True, exist_ok=True)
    for item in sorted(source.iterdir(), key=lambda path: path.name.casefold()):
        if item.name.casefold() in skip:
            continue
        target = destination / item.name
        _reject_link(item)
        if item.is_dir():
            _copy_tree(item, target)
        elif item.is_file():
            shutil.copy2(item, target)


def _reject_link(path: Path) -> None:
    is_junction = getattr(path, "is_junction", lambda: False)
    if path.is_symlink() or is_junction():
        raise PathSafetyError(f"Exchange Packages cannot contain links: {path}")


def _safe_relative(value: str) -> PurePosixPath:
    if "\\" in value or _WINDOWS_ABSOLUTE.match(value):
        raise PathSafetyError(f"Unsafe Package path: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise PathSafetyError(f"Unsafe Package path: {value}")
    return path


def _ensure_within(root: Path, path: Path) -> None:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise PathSafetyError(f"Package path escaped its root: {path}") from exc


def _reject_nested_destination(source: Path, destination: Path) -> None:
    try:
        destination.resolve().relative_to(source.resolve())
    except ValueError:
        return
    raise PathSafetyError("Package Exchange path cannot be inside the source folder")


def _copy_name(original: str, exists: object) -> str:
    index = 1
    while True:
        candidate = f"{original}_copy" if index == 1 else f"{original}_copy{index}"
        if callable(exists) and not exists(candidate):
            return candidate
        index += 1


def _slug(value: str) -> str:
    cleaned = "".join(
        character if character.isalnum() or character in "-_" else "_"
        for character in value.strip()
    )
    return cleaned or "unnamed"


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_absolute_text(value: str) -> bool:
    return bool(
        _WINDOWS_ABSOLUTE.match(value)
        or value.startswith("//")
        or value.startswith("\\\\")
    )


def _ensure_free_space(destination: Path, required: int) -> None:
    usage = shutil.disk_usage(destination)
    if usage.free < required:
        raise OSError(
            f"Not enough free space for Package import: {required} bytes required, "
            f"{usage.free} bytes available"
        )
