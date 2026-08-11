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
from .task_manager import TaskManager


_SECRET_MARKERS = ("PASSWORD", "PASS", "TOKEN", "SECRET", "API_KEY", "CREDENTIAL")
_WINDOWS_ABSOLUTE = re.compile(r"^[A-Za-z]:[\\/]")
_CACHE_ROLES = {
    "geo_cache",
    "vdb_cache",
    "sim",
    "simulation",
    "alembic",
    "abc_cache",
}


class TaskPackageFile(StrictModel):
    relative_path: str
    size: int = Field(ge=0)
    modified_at: datetime
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class TaskPackageManifest(StrictModel):
    format: Literal["houd2.task_package"] = "houd2.task_package"
    schema_version: Literal[1] = 1
    package_id: str = Field(default_factory=lambda: str(uuid4()))
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    source_project_id: str
    source_project_name: str
    source_task_id: str
    source_task_name: str
    source_houdini_versions: list[str] = Field(default_factory=list)
    excluded_roles: list[str] = Field(default_factory=list)
    files: list[TaskPackageFile] = Field(default_factory=list)


@dataclass(frozen=True, slots=True)
class TaskPackagePreview:
    package_root: Path
    manifest: TaskPackageManifest
    target_task_name: str
    target_task_id: str
    renamed: bool
    total_size: int
    project_differences: tuple[str, ...]
    warnings: tuple[str, ...]


class TaskPackageService:
    """Export and import cache-free, checksum-verified task folders."""

    def __init__(self, resolver: PathResolver, task_manager: TaskManager) -> None:
        self.resolver = resolver
        self.task_manager = task_manager

    def export(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        destination_parent: Path,
        source_houdini_versions: list[str] | None = None,
    ) -> Path:
        source_root = self.resolver.resolve_task_root(project, task.name)
        if not source_root.is_dir():
            raise FileNotFoundError(f"Task folder is missing: {source_root}")
        destination_parent = destination_parent.expanduser().resolve()
        if _is_within(source_root, destination_parent):
            raise PathSafetyError("Task Package destination cannot be inside the source Task")
        destination_parent.mkdir(parents=True, exist_ok=True)
        final = destination_parent / f"{task.name}_houd2package"
        if final.exists():
            raise FileExistsError(f"Task Package already exists: {final}")
        staging = destination_parent / f".{final.name}.part-{uuid4().hex}"
        staging_task = staging / "task"
        excluded = self._excluded_paths(project, task)
        excluded_roles = sorted({role for role, _ in excluded})
        excluded_paths = [path.resolve() for _, path in excluded]
        files: list[TaskPackageFile] = []
        try:
            staging_task.mkdir(parents=True)
            try:
                geo_root = self.resolver.resolve_role(project, task, "geo_cache")
                (staging_task / geo_root.relative_to(source_root)).mkdir(parents=True, exist_ok=True)
            except (KeyError, ValueError):
                pass
            for source in source_root.rglob("*"):
                if _is_link(source):
                    raise PathSafetyError(f"Task Package cannot contain links: {source}")
                resolved = source.resolve()
                if any(_is_within(path, resolved) for path in excluded_paths):
                    continue
                relative = source.relative_to(source_root)
                destination = staging_task / relative
                if source.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)

            task_config = staging_task / ".houd2" / "task.json"
            atomic_write_model(task_config, _portable_task(task))
            files.extend(
                _file_entry(path, f"task/{path.relative_to(staging_task).as_posix()}")
                for path in sorted(staging_task.rglob("*"))
                if path.is_file()
            )

            context_path = staging / "project_context.json"
            context_path.write_text(
                json.dumps(_project_context(project), indent=2, ensure_ascii=True),
                encoding="utf-8",
            )
            files.append(_file_entry(context_path, "project_context.json"))
            manifest = TaskPackageManifest(
                source_project_id=project.project_id,
                source_project_name=project.name,
                source_task_id=task.task_id,
                source_task_name=task.name,
                source_houdini_versions=sorted(set(source_houdini_versions or [])),
                excluded_roles=excluded_roles,
                files=sorted(files, key=lambda item: item.relative_path.casefold()),
            )
            atomic_write_model(staging / "manifest.json", manifest)
            self._validate_files(staging, manifest)
            os.replace(staging, final)
        except Exception:
            if staging.exists():
                shutil.rmtree(staging)
            raise
        return final

    def preview_import(
        self, package_root: Path, target_project: ProjectSettings
    ) -> TaskPackagePreview:
        root, manifest, package_context = self._validate_package(package_root)
        target_name, target_id, renamed = self._target_identity(manifest, target_project)
        differences = tuple(_context_differences(package_context, _project_context(target_project)))
        warnings: list[str] = []
        unmanaged_hips = self._unmanaged_hips(root)
        if unmanaged_hips:
            warnings.append(
                f"{len(unmanaged_hips)} unmanaged HIP file(s) keep their original filenames."
            )
        return TaskPackagePreview(
            package_root=root,
            manifest=manifest,
            target_task_name=target_name,
            target_task_id=target_id,
            renamed=renamed,
            total_size=sum(item.size for item in manifest.files),
            project_differences=differences,
            warnings=tuple(warnings),
        )

    def import_package(
        self,
        package_root: Path,
        target_project: ProjectSettings,
        preview: TaskPackagePreview | None = None,
    ) -> TaskSettings:
        if preview is None:
            preview = self.preview_import(package_root, target_project)
        else:
            _, manifest, _ = self._validate_package(package_root)
            if preview.manifest.package_id != manifest.package_id:
                raise ValueError("Task Package changed after Preview")
            if self.resolver.resolve_task_root(target_project, preview.target_task_name).exists():
                raise FileExistsError("Target task changed after Preview")
        final = self.resolver.resolve_task_root(target_project, preview.target_task_name)
        if final.exists():
            raise FileExistsError(f"Task already exists: {final}")
        staging_root = target_project.project_root / f".{preview.target_task_name}.import-{uuid4().hex}"
        staging_task = staging_root / "task"
        try:
            shutil.copytree(preview.package_root / "task", staging_task)
            config_path = staging_task / ".houd2" / "task.json"
            task = load_model(config_path, TaskSettings)
            task.project_id = target_project.project_id
            task.name = preview.target_task_name
            task.task_id = preview.target_task_id
            task.recommended_installation_id = None
            self._update_hips(staging_task, target_project, task, preview.renamed)
            atomic_write_model(config_path, task)
            os.replace(staging_task, final)
            staging_root.rmdir()
        except Exception:
            if staging_root.exists():
                shutil.rmtree(staging_root)
            raise
        loaded = self.task_manager.load(
            target_project, self.resolver.resolve_task_metadata_path(target_project, task)
        )
        self.task_manager.repository.record_activity(
            target_project.project_id,
            "task_package_imported",
            {"package_id": preview.manifest.package_id, "name": loaded.name},
            loaded.task_id,
        )
        return loaded

    def _excluded_paths(
        self, project: ProjectSettings, task: TaskSettings
    ) -> list[tuple[str, Path]]:
        excluded: list[tuple[str, Path]] = []
        for folder in project.folders:
            role = folder.role.casefold()
            if folder.enabled and is_cache_role(role):
                excluded.append(
                    (folder.role, self.resolver.resolve_houdini_folder(project, task, folder.relative_path))
                )
        excluded.append(
            (
                ".houd2/trash/caches",
                self.resolver.resolve_task_root(project, task.name)
                / ".houd2"
                / "trash"
                / "caches",
            )
        )
        return excluded

    def _validate_package(
        self, package_root: Path
    ) -> tuple[Path, TaskPackageManifest, dict[str, object]]:
        root = package_root.expanduser().resolve()
        manifest_path = root / "manifest.json"
        context_path = root / "project_context.json"
        task_config = root / "task" / ".houd2" / "task.json"
        if not manifest_path.is_file() or not context_path.is_file() or not task_config.is_file():
            raise ValueError("Folder is not a complete HouD2 Task Package")
        manifest = load_model(manifest_path, TaskPackageManifest)
        self._validate_files(root, manifest)
        context = json.loads(context_path.read_text(encoding="utf-8"))
        if not isinstance(context, dict):
            raise ValueError("Project Context must be a JSON object")
        source_task = load_model(task_config, TaskSettings)
        if source_task.task_id != manifest.source_task_id or source_task.name != manifest.source_task_name:
            raise ValueError("Manifest and packaged Task settings do not match")
        return root, manifest, context

    def _validate_files(self, root: Path, manifest: TaskPackageManifest) -> None:
        for path in root.rglob("*"):
            if _is_link(path) or not _is_within(root, path):
                raise PathSafetyError(f"Task Package contains an unsafe link: {path}")
        declared: set[str] = set()
        for entry in manifest.files:
            relative = _safe_package_relative(entry.relative_path)
            key = relative.as_posix().casefold()
            if key in declared:
                raise ValueError(f"Duplicate package path: {entry.relative_path}")
            declared.add(key)
            candidate = root.joinpath(*relative.parts)
            if not _is_within(root, candidate) or _is_link(candidate):
                raise PathSafetyError(f"Unsafe package path: {entry.relative_path}")
            if not candidate.is_file():
                raise FileNotFoundError(f"Package file is missing: {entry.relative_path}")
            if candidate.stat().st_size != entry.size or _sha256(candidate) != entry.sha256:
                raise ValueError(f"Checksum mismatch: {entry.relative_path}")
        actual = {
            path.relative_to(root).as_posix().casefold()
            for path in root.rglob("*")
            if path.is_file() and path.relative_to(root).as_posix().casefold() != "manifest.json"
        }
        if actual != declared:
            missing = sorted(actual.symmetric_difference(declared))
            raise ValueError(f"Package file list does not match contents: {', '.join(missing[:5])}")

    def _target_identity(
        self, manifest: TaskPackageManifest, project: ProjectSettings
    ) -> tuple[str, str, bool]:
        original = manifest.source_task_name
        if (
            not self.resolver.resolve_task_root(project, original).exists()
            and not self.task_manager.repository.task_id_exists(manifest.source_task_id)
        ):
            return original, manifest.source_task_id, False
        index = 1
        while True:
            name = f"{original}_copy" if index == 1 else f"{original}_copy{index}"
            if not self.resolver.resolve_task_root(project, name).exists():
                return name, str(uuid4()), True
            index += 1

    def _update_hips(
        self,
        task_root: Path,
        project: ProjectSettings,
        task: TaskSettings,
        rename: bool,
    ) -> None:
        metadata_root = task_root / ".houd2" / "hips"
        if not metadata_root.is_dir():
            return
        for metadata_path in list(metadata_root.glob("*.json")):
            metadata = load_model(metadata_path, HipMetadata)
            old_name = metadata.hip_file
            new_name = old_name
            if rename:
                new_name = self.resolver.resolve_hip_path(
                    project,
                    task,
                    metadata.hip_version,
                    metadata.created_by,
                    Path(old_name).suffix.lower().lstrip("."),
                ).name
                source_hip = task_root / "houdini" / old_name
                target_hip = task_root / "houdini" / new_name
                if source_hip.is_file():
                    if target_hip.exists():
                        raise FileExistsError(f"Imported HIP filename collision: {target_hip.name}")
                    source_hip.rename(target_hip)
            metadata.task_id = task.task_id
            metadata.hip_file = new_name
            metadata.last_opened_with = None
            metadata.last_saved_with = None
            metadata.recommended_installation_id = None
            target_metadata = metadata_root / f"{new_name}.json"
            atomic_write_model(target_metadata, metadata)
            if target_metadata != metadata_path:
                metadata_path.unlink()

    @staticmethod
    def _unmanaged_hips(root: Path) -> list[Path]:
        managed = {
            path.name[: -len(".json")]
            for path in (root / "task" / ".houd2" / "hips").glob("*.json")
        }
        return [
            path
            for path in (root / "task" / "houdini").glob("*.hip*")
            if path.name not in managed
        ]


def _project_context(project: ProjectSettings) -> dict[str, object]:
    environment = {
        name: value
        for name, value in project.environment.items()
        if not any(marker in name.upper() for marker in _SECRET_MARKERS)
        and not _is_absolute_text(value)
    }
    search_paths = {
        key: [value for value in values if not _is_absolute_text(value)]
        for key, values in project.search_paths.model_dump(mode="python").items()
    }
    houdini = project.houdini.model_dump(mode="python")
    houdini.pop("default_installation_id", None)
    return {
        "project_id": project.project_id,
        "project_name": project.name,
        "default_frames": project.default_frames.model_dump(mode="json"),
        "folders": [folder.model_dump(mode="json") for folder in project.folders],
        "environment": environment,
        "search_paths": search_paths,
        "naming": project.naming.model_dump(mode="json"),
        "houdini_policy": houdini,
    }


def _portable_task(task: TaskSettings) -> TaskSettings:
    copy = task.model_copy(deep=True)
    copy.environment = {
        name: value
        for name, value in task.environment.items()
        if not any(marker in name.upper() for marker in _SECRET_MARKERS)
        and not _is_absolute_text(value)
    }
    copy.recommended_installation_id = None
    return copy


def is_cache_role(role: str) -> bool:
    """Return whether a folder role represents generated cache payload."""
    normalized = role.strip().casefold()
    return normalized in _CACHE_ROLES or normalized.endswith("_cache")


def _context_differences(
    package: dict[str, object], target: dict[str, object]
) -> list[str]:
    differences: list[str] = []
    for key in sorted(set(package) | set(target)):
        if key in {"project_id", "project_name"}:
            continue
        if package.get(key) != target.get(key):
            differences.append(f"{key}: Package and target Project differ")
    return differences


def _safe_package_relative(value: str) -> PurePosixPath:
    if "\\" in value or _WINDOWS_ABSOLUTE.match(value):
        raise PathSafetyError(f"Unsafe package path: {value}")
    path = PurePosixPath(value)
    if path.is_absolute() or not path.parts or any(part in {"", ".", ".."} for part in path.parts):
        raise PathSafetyError(f"Unsafe package path: {value}")
    return path


def _file_entry(path: Path, relative: str) -> TaskPackageFile:
    stat = path.stat()
    return TaskPackageFile(
        relative_path=relative,
        size=stat.st_size,
        modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc),
        sha256=_sha256(path),
    )


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _is_absolute_text(value: str) -> bool:
    return bool(_WINDOWS_ABSOLUTE.match(value) or value.startswith("//") or value.startswith("\\\\"))


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False


def _is_link(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)
