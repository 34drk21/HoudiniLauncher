from __future__ import annotations

import os
import shutil
from pathlib import Path

from .config import atomic_write_model, load_model
from .exceptions import PathSafetyError
from .models import ProjectSettings, TaskSettings, utc_now
from .path_resolver import PathResolver
from ..database.repositories import LauncherRepository


class TaskManager:
    """Manage task folders and canonical task settings."""

    def __init__(self, repository: LauncherRepository, resolver: PathResolver) -> None:
        self.repository = repository
        self.resolver = resolver

    def create(self, project: ProjectSettings, task: TaskSettings) -> TaskSettings:
        """Create a task, its Houdini structure, and its JSON settings."""
        if task.project_id != project.project_id:
            raise ValueError("Task project ID does not match the selected project")
        task_root = self.resolver.resolve_task_root(project, task.name)
        if task_root.exists():
            raise FileExistsError(f"Task folder already exists: {task_root}")
        try:
            self._initialize(project, task)
        except OSError:
            if task_root.exists():
                shutil.rmtree(task_root)
            raise
        self._index(project, task)
        self.repository.record_activity(
            project.project_id, "task_created", {"name": task.name}, task.task_id
        )
        return task

    def adopt_existing(
        self, project: ProjectSettings, task: TaskSettings
    ) -> TaskSettings:
        """Adopt an existing direct-child folder without removing its contents."""
        if task.project_id != project.project_id:
            raise ValueError("Task project ID does not match the selected project")
        task_root = self.resolver.resolve_task_root(project, task.name)
        metadata = self.resolver.resolve_task_metadata_path(project, task)
        if not task_root.is_dir():
            raise FileNotFoundError(task_root)
        if metadata.exists():
            raise FileExistsError(f"Task metadata already exists: {metadata}")
        is_junction = getattr(task_root, "is_junction", lambda: False)
        if task_root.is_symlink() or is_junction():
            raise PathSafetyError(f"Linked Task folders cannot be adopted: {task_root}")
        self._initialize(project, task)
        self._index(project, task)
        self.repository.record_activity(
            project.project_id,
            "task_adopted_from_filesystem",
            {"name": task.name},
            task.task_id,
        )
        return task

    def load(self, project: ProjectSettings, config_path: Path) -> TaskSettings:
        """Load task JSON and refresh its SQLite index."""
        task = load_model(config_path, TaskSettings)
        if task.project_id != project.project_id:
            raise ValueError("Task belongs to a different project")
        self._index(project, task)
        return task

    def save(self, project: ProjectSettings, task: TaskSettings) -> Path:
        """Atomically save task settings and refresh the index."""
        if task.project_id != project.project_id:
            raise ValueError("Task belongs to a different project")
        task.modified_at = utc_now()
        path = self.resolver.resolve_task_metadata_path(project, task)
        atomic_write_model(path, task)
        self._index(project, task)
        self.repository.record_activity(
            project.project_id, "task_settings_changed", task_id=task.task_id
        )
        return path

    def discover(self, project: ProjectSettings) -> list[TaskSettings]:
        """Discover direct-child tasks from canonical JSON, then rebuild the index."""
        root = self.resolver.resolve_project_root(project)
        if not root.is_dir():
            return []
        tasks: list[TaskSettings] = []
        for candidate in root.iterdir():
            if not candidate.is_dir() or candidate.name.startswith("."):
                continue
            config_path = candidate / ".houd2" / "task.json"
            if not config_path.is_file():
                continue
            task = load_model(config_path, TaskSettings)
            if task.project_id == project.project_id:
                tasks.append(task)
                self._index(project, task)
        return sorted(tasks, key=lambda item: item.modified_at, reverse=True)

    def rename(
        self, project: ProjectSettings, task: TaskSettings, new_name: str
    ) -> TaskSettings:
        """Rename a task folder and update its canonical settings."""
        old_root = self.resolver.resolve_task_root(project, task.name)
        new_root = self.resolver.resolve_task_root(project, new_name)
        if new_root.exists():
            raise FileExistsError(f"Task already exists: {new_name}")
        old_name = task.name
        old_root.rename(new_root)
        task.name = new_name
        task.modified_at = utc_now()
        self.save(project, task)
        self.repository.record_activity(
            project.project_id,
            "task_renamed",
            {"old_name": old_name, "new_name": task.name},
            task.task_id,
        )
        return task

    def archive(self, project: ProjectSettings, task: TaskSettings) -> None:
        """Mark a task archived without deleting its files."""
        task.status = "archived"
        self.save(project, task)

    def restore(self, project: ProjectSettings, task: TaskSettings) -> None:
        """Return an archived Task to active production status."""
        if task.status != "archived":
            raise ValueError(f"Task is not archived: {task.name}")
        task.status = "active"
        self.save(project, task)

    def delete_permanently(
        self, project: ProjectSettings, task: TaskSettings
    ) -> Path:
        """Permanently delete one direct-child Task folder and its local indexes."""
        if task.project_id != project.project_id:
            raise ValueError("Task belongs to a different project")
        project_root = self.resolver.resolve_project_root(project)
        task_root = self.resolver.resolve_task_root(project, task.name)
        resolved = task_root.resolve()
        if resolved == project_root or resolved.parent != project_root:
            raise PathSafetyError(f"Task deletion escaped the Project root: {task_root}")
        is_junction = getattr(task_root, "is_junction", lambda: False)
        if task_root.is_symlink() or is_junction():
            raise PathSafetyError(f"Linked Task folders cannot be deleted: {task_root}")
        if not task_root.is_dir():
            raise FileNotFoundError(f"Task folder is missing: {task_root}")

        shutil.rmtree(task_root)
        self.repository.remove_task(task.task_id)
        self.repository.record_activity(
            project.project_id,
            "task_deleted_permanently",
            {"name": task.name, "path": str(task_root)},
            task.task_id,
        )
        return task_root

    def set_thumbnail(
        self, project: ProjectSettings, task: TaskSettings, source: Path
    ) -> Path:
        """Atomically replace a task thumbnail from a supported image file."""
        if not source.is_file() or source.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            raise ValueError("Select an existing JPG or PNG image")
        extension = source.suffix.lower().lstrip(".")
        destination = self.resolver.resolve_thumbnail_path(
            project, task, extension=extension
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_suffix(destination.suffix + ".part")
        try:
            shutil.copy2(source, temporary)
            os.replace(temporary, destination)
        except OSError:
            temporary.unlink(missing_ok=True)
            raise
        self.repository.record_activity(
            project.project_id,
            "thumbnail_updated",
            {"path": str(destination)},
            task.task_id,
        )
        return destination

    def _index(self, project: ProjectSettings, task: TaskSettings) -> None:
        path = self.resolver.resolve_task_metadata_path(project, task)
        self.repository.upsert_task(
            task.task_id,
            project.project_id,
            task.name,
            path,
            task.status,
            task.modified_at.isoformat(),
        )

    def _initialize(self, project: ProjectSettings, task: TaskSettings) -> None:
        task_root = self.resolver.resolve_task_root(project, task.name)
        self.resolver.resolve_houdini_root(project, task).mkdir(
            parents=True, exist_ok=True
        )
        (task_root / ".houd2" / "hips").mkdir(parents=True, exist_ok=True)
        (task_root / ".houd2" / "thumbnails").mkdir(parents=True, exist_ok=True)
        for folder in project.folders:
            if folder.enabled and folder.auto_create:
                self.resolver.resolve_houdini_folder(
                    project, task, folder.relative_path
                ).mkdir(parents=True, exist_ok=True)
        atomic_write_model(self.resolver.resolve_task_metadata_path(project, task), task)
