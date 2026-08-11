from __future__ import annotations

from dataclasses import dataclass

from .hip_manager import HipManager
from .models import ProjectSettings, TaskSettings
from .path_resolver import PathResolver
from .task_manager import TaskManager
from .validation import validate_filename_component


@dataclass(frozen=True, slots=True)
class ReconcileReport:
    tasks: tuple[TaskSettings, ...]
    task_candidates: tuple[str, ...]
    hip_count: int
    errors: tuple[str, ...]


class FilesystemReconciler:
    """Rebuild canonical Task/HIP indexes from safe filesystem discoveries."""

    def __init__(
        self,
        tasks: TaskManager,
        hips: HipManager,
        resolver: PathResolver,
    ) -> None:
        self.tasks = tasks
        self.hips = hips
        self.resolver = resolver

    def reconcile(self, project: ProjectSettings) -> ReconcileReport:
        root = self.resolver.resolve_project_root(project)
        if not root.is_dir():
            return ReconcileReport((), (), 0, (f"Project root is missing: {root}",))
        tasks: list[TaskSettings] = []
        candidates: list[str] = []
        errors: list[str] = []
        hip_count = 0
        for candidate in sorted(root.iterdir(), key=lambda item: item.name.casefold()):
            if not candidate.is_dir() or candidate.name.startswith("."):
                continue
            config = candidate / ".houd2" / "task.json"
            if not config.is_file():
                try:
                    validate_filename_component(candidate.name, "Task name")
                    if (candidate / "houdini").is_dir() or any(candidate.glob("*.hip*")):
                        task = self.adopt_task(project, candidate.name, "System")
                        tasks.append(task)
                        hip_count += len(self.hips.list_hips(project, task))
                    else:
                        candidates.append(candidate.name)
                except (OSError, ValueError) as exc:
                    errors.append(f"{candidate.name}: {exc}")
                continue
            try:
                task = self.tasks.load(project, config, repair_project_id=True)
                tasks.append(task)
                hip_count += len(self.hips.list_hips(project, task))
            except (OSError, ValueError) as exc:
                errors.append(f"{candidate.name}: {exc}")
        tasks.sort(key=lambda item: item.modified_at, reverse=True)
        return ReconcileReport(
            tuple(tasks), tuple(candidates), hip_count, tuple(errors)
        )

    def adopt_task(
        self, project: ProjectSettings, folder_name: str, user: str
    ) -> TaskSettings:
        task = TaskSettings(
            project_id=project.project_id,
            name=folder_name,
            owner=user,
            frames=project.default_frames.model_copy(deep=True),
        )
        return self.tasks.adopt_existing(project, task)
