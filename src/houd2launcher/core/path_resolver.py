from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .exceptions import PathSafetyError
from .models import ProjectSettings, TaskSettings
from .validation import (
    ensure_within,
    validate_filename_component,
    validate_relative_path,
)


class PathResolver:
    """Resolve every project, task, metadata, thumbnail, and HIP path safely."""

    def resolve_project_root(self, project: ProjectSettings) -> Path:
        """Return the canonical project root."""
        return project.project_root.expanduser().resolve()

    def resolve_project_metadata_path(self, project: ProjectSettings) -> Path:
        """Return the canonical project settings path."""
        return self.resolve_project_root(project) / ".houd2" / "project.json"

    def resolve_task_root(self, project: ProjectSettings, task_name: str) -> Path:
        """Return a task root directly below its project root."""
        safe_name = validate_filename_component(task_name, "Task name")
        root = self.resolve_project_root(project)
        return ensure_within(root, root / safe_name)

    def resolve_houdini_root(
        self, project: ProjectSettings, task: TaskSettings | str
    ) -> Path:
        """Return the fixed Houdini directory for a task."""
        task_name = task.name if isinstance(task, TaskSettings) else task
        return self.resolve_task_root(project, task_name) / "houdini"

    def resolve_houdini_folder(
        self,
        project: ProjectSettings,
        task: TaskSettings | str,
        relative_path: str,
    ) -> Path:
        """Resolve a configured folder below a task's Houdini root."""
        relative = validate_relative_path(relative_path, "Houdini folder")
        houdini_root = self.resolve_houdini_root(project, task)
        return ensure_within(houdini_root, houdini_root.joinpath(*relative.split("/")))

    def resolve_role(
        self, project: ProjectSettings, task: TaskSettings | str, role: str
    ) -> Path:
        """Resolve an enabled project folder by logical role."""
        matches = [folder for folder in project.folders if folder.enabled and folder.role == role]
        if not matches:
            raise KeyError(f"Unknown or disabled folder role: {role}")
        if len(matches) > 1:
            raise PathSafetyError(f"Duplicate folder role: {role}")
        return self.resolve_houdini_folder(project, task, matches[0].relative_path)

    def resolve_task_metadata_path(
        self, project: ProjectSettings, task: TaskSettings | str
    ) -> Path:
        """Return the canonical task settings path."""
        task_name = task.name if isinstance(task, TaskSettings) else task
        return self.resolve_task_root(project, task_name) / ".houd2" / "task.json"

    def resolve_thumbnail_path(
        self,
        project: ProjectSettings,
        task: TaskSettings | str,
        version: int | None = None,
        extension: str = "jpg",
    ) -> Path:
        """Return the task or per-HIP thumbnail path."""
        task_name = task.name if isinstance(task, TaskSettings) else task
        metadata_root = self.resolve_task_root(project, task_name) / ".houd2"
        if version is None:
            return metadata_root / f"thumbnail.{extension}"
        return metadata_root / "thumbnails" / f"v{version:03d}.{extension}"

    def resolve_hip_metadata_path(
        self, project: ProjectSettings, task: TaskSettings, hip_path: Path
    ) -> Path:
        """Return the metadata JSON path for one HIP filename."""
        filename = validate_filename_component(hip_path.name, "HIP filename")
        root = self.resolve_task_root(project, task.name) / ".houd2" / "hips"
        return ensure_within(root, root / f"{filename}.json")

    def resolve_hip_path(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        version: int,
        user: str,
        extension: str | None = None,
        houdini_version: str = "unknown",
    ) -> Path:
        """Render a configured HIP filename inside the Houdini root."""
        if version < 1:
            raise ValueError("HIP version must be greater than zero")
        safe_user = validate_filename_component(user, "User")
        file_extension = extension or project.naming.default_extension
        if file_extension not in {"hip", "hiplc", "hipnc"}:
            raise ValueError("Unsupported HIP extension")
        try:
            filename = project.naming.hip_template.format(
                project=project.name,
                task=task.name,
                version=version,
                user=safe_user,
                date=datetime.now().strftime("%Y%m%d"),
                houdini_version=houdini_version,
                extension=file_extension,
            )
        except (KeyError, ValueError) as exc:
            raise ValueError(f"Invalid HIP naming template: {exc}") from exc
        filename = validate_filename_component(filename, "HIP filename")
        if Path(filename).suffix.lower() not in {".hip", ".hiplc", ".hipnc"}:
            raise ValueError("Rendered HIP filename has an unsupported extension")
        root = self.resolve_houdini_root(project, task)
        return ensure_within(root, root / filename)

