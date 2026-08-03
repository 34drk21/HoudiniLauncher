from __future__ import annotations

import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import atomic_write_model, load_model
from .models import HipMetadata, ProjectSettings, TaskSettings
from .path_resolver import PathResolver
from .versioning import next_version, parse_managed_hip_name
from ..database.repositories import LauncherRepository


@dataclass(frozen=True, slots=True)
class HipRecord:
    """One discovered HIP file and its launcher metadata."""

    path: Path
    version: int
    user: str
    modified_at: datetime
    size: int
    metadata: HipMetadata


class HipManager:
    """Discover, version, and index HIP files without using Houdini HOM."""

    def __init__(self, repository: LauncherRepository, resolver: PathResolver) -> None:
        self.repository = repository
        self.resolver = resolver

    def list_hips(self, project: ProjectSettings, task: TaskSettings) -> list[HipRecord]:
        """List managed HIP files directly below the task Houdini folder only."""
        houdini_root = self.resolver.resolve_houdini_root(project, task)
        if not houdini_root.is_dir():
            return []
        records: list[HipRecord] = []
        for path in houdini_root.iterdir():
            if not path.is_file():
                continue
            parsed = parse_managed_hip_name(path, project, task)
            if parsed is None:
                continue
            metadata_path = self.resolver.resolve_hip_metadata_path(project, task, path)
            if metadata_path.is_file():
                metadata = load_model(metadata_path, HipMetadata)
                changed = False
                if metadata.task_id != task.task_id:
                    metadata.task_id = task.task_id
                    changed = True
                if metadata.hip_file != path.name:
                    metadata.hip_file = path.name
                    changed = True
                if metadata.hip_version != parsed.version:
                    metadata.hip_version = parsed.version
                    changed = True
                if changed:
                    atomic_write_model(metadata_path, metadata)
            else:
                metadata = HipMetadata(
                    task_id=task.task_id,
                    hip_file=path.name,
                    hip_version=parsed.version,
                    created_by=parsed.user,
                )
                atomic_write_model(metadata_path, metadata)
            stat = path.stat()
            record = HipRecord(
                path=path,
                version=parsed.version,
                user=metadata.created_by,
                modified_at=datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
                size=stat.st_size,
                metadata=metadata,
            )
            records.append(record)
            self.repository.upsert_hip(
                path, task.task_id, record.version, record.user, metadata_path
            )
        return sorted(records, key=lambda item: item.version, reverse=True)

    def next_path(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        user: str,
        extension: str | None = None,
        houdini_version: str = "unknown",
    ) -> tuple[int, Path]:
        """Return the next available version and configured HIP path."""
        versions = [record.version for record in self.list_hips(project, task)]
        version = next_version(versions)
        return version, self.resolver.resolve_hip_path(
            project, task, version, user, extension, houdini_version
        )

    def register_created(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        hip_path: Path,
        version: int,
        user: str,
        installation_id: str | None,
        comment: str = "",
    ) -> HipMetadata:
        """Register metadata after an external creator produces a valid HIP file."""
        if not hip_path.is_file():
            raise FileNotFoundError(hip_path)
        metadata = HipMetadata(
            task_id=task.task_id,
            hip_file=hip_path.name,
            hip_version=version,
            created_by=user,
            last_saved_with=installation_id,
            recommended_installation_id=installation_id,
            comment=comment,
        )
        metadata_path = self.resolver.resolve_hip_metadata_path(project, task, hip_path)
        atomic_write_model(metadata_path, metadata)
        self.repository.upsert_hip(
            hip_path, task.task_id, version, user, metadata_path
        )
        self.repository.record_activity(
            project.project_id,
            "hip_created",
            {"path": str(hip_path), "version": version},
            task.task_id,
        )
        return metadata

    def version_up(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        source: HipRecord,
        user: str,
        comment: str = "",
    ) -> HipRecord:
        """Copy a HIP to the next version and write new launcher metadata."""
        version, destination = self.next_path(
            project,
            task,
            user,
            source.path.suffix.lower().lstrip("."),
        )
        if destination.exists():
            raise FileExistsError(destination)
        shutil.copy2(source.path, destination)
        metadata = self.register_created(
            project,
            task,
            destination,
            version,
            user,
            source.metadata.last_saved_with,
            comment,
        )
        self.repository.record_activity(
            project.project_id,
            "hip_version_up",
            {"source": str(source.path), "destination": str(destination)},
            task.task_id,
        )
        stat = destination.stat()
        return HipRecord(
            destination,
            version,
            user,
            datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc),
            stat.st_size,
            metadata,
        )

    def save_metadata(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        hip_path: Path,
        metadata: HipMetadata,
    ) -> Path:
        """Atomically update launcher metadata for one HIP."""
        path = self.resolver.resolve_hip_metadata_path(project, task, hip_path)
        atomic_write_model(path, metadata)
        return path
