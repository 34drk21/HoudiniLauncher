from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from .models import ProjectSettings, TaskSettings
from .path_resolver import PathResolver


@dataclass(frozen=True, slots=True)
class FolderMigrationAction:
    task_name: str
    role: str
    source: Path | None
    destination: Path
    kind: str


@dataclass(frozen=True, slots=True)
class FolderMigrationPlan:
    actions: tuple[FolderMigrationAction, ...]
    blockers: tuple[str, ...]
    retained: tuple[Path, ...]

    @property
    def requires_confirmation(self) -> bool:
        return bool(self.actions)


class FolderStructureMigrator:
    """Plan and apply safe filesystem changes for Project folder definitions."""

    def __init__(self, resolver: PathResolver) -> None:
        self.resolver = resolver

    def plan(
        self,
        current: ProjectSettings,
        proposed: ProjectSettings,
        tasks: list[TaskSettings],
    ) -> FolderMigrationPlan:
        old_by_role = {item.role: item for item in current.folders if item.enabled}
        new_by_role = {item.role: item for item in proposed.folders if item.enabled}
        actions: list[FolderMigrationAction] = []
        blockers: list[str] = []
        retained: list[Path] = []

        for task in tasks:
            moves: list[FolderMigrationAction] = []
            for role, old in old_by_role.items():
                new = new_by_role.get(role)
                source = self.resolver.resolve_houdini_folder(
                    current, task, old.relative_path
                )
                if new is None:
                    if source.exists():
                        retained.append(source)
                    continue
                destination = self.resolver.resolve_houdini_folder(
                    proposed, task, new.relative_path
                )
                if source == destination:
                    continue
                if source.exists():
                    moves.append(
                        FolderMigrationAction(
                            task.name, role, source, destination, "move"
                        )
                    )
                elif new.auto_create:
                    actions.append(
                        FolderMigrationAction(
                            task.name, role, None, destination, "create"
                        )
                    )

            moved_roles = {item.role for item in moves}
            for role, new in new_by_role.items():
                if role in old_by_role or role in moved_roles or not new.auto_create:
                    continue
                destination = self.resolver.resolve_houdini_folder(
                    proposed, task, new.relative_path
                )
                if not destination.exists():
                    actions.append(
                        FolderMigrationAction(
                            task.name, role, None, destination, "create"
                        )
                    )

            blockers.extend(self._validate_moves(task, moves))
            actions.extend(moves)

        return FolderMigrationPlan(
            tuple(actions), tuple(dict.fromkeys(blockers)), tuple(retained)
        )

    def apply(self, project: ProjectSettings, plan: FolderMigrationPlan) -> None:
        if plan.blockers:
            raise ValueError("Folder migration has blocking conflicts")
        migration_id = str(uuid4())
        journal = (
            self.resolver.resolve_project_root(project)
            / ".houd2"
            / "folder_migrations"
            / f"{migration_id}.json"
        )
        journal.parent.mkdir(parents=True, exist_ok=True)
        journal_data = {
            "migration_id": migration_id,
            "status": "running",
            "actions": [
                {
                    "task": item.task_name,
                    "role": item.role,
                    "source": str(item.source) if item.source else None,
                    "destination": str(item.destination),
                    "kind": item.kind,
                }
                for item in plan.actions
            ],
        }
        self._write_journal(journal, journal_data)
        staged: list[tuple[FolderMigrationAction, Path]] = []
        placed: list[tuple[FolderMigrationAction, Path]] = []
        created: list[Path] = []
        try:
            for index, action in enumerate(item for item in plan.actions if item.source):
                assert action.source is not None
                staging = (
                    self.resolver.resolve_task_root(project, action.task_name)
                    / ".houd2"
                    / "folder_migrations"
                    / migration_id
                    / f"{index:04d}_{action.role}"
                )
                staging.parent.mkdir(parents=True, exist_ok=True)
                action.source.rename(staging)
                staged.append((action, staging))
            journal_data["status"] = "staged"
            self._write_journal(journal, journal_data)
            for action, staging in staged:
                if action.destination.exists():
                    action.destination.rmdir()
                action.destination.parent.mkdir(parents=True, exist_ok=True)
                staging.rename(action.destination)
                placed.append((action, staging))
            for action in (item for item in plan.actions if item.kind == "create"):
                if not action.destination.exists():
                    action.destination.mkdir(parents=True, exist_ok=True)
                    created.append(action.destination)
            journal_data["status"] = "placed"
            self._write_journal(journal, journal_data)
        except OSError:
            for path in reversed(created):
                try:
                    path.rmdir()
                except OSError:
                    pass
            for action, staging in reversed(placed):
                if action.destination.exists() and not staging.exists():
                    staging.parent.mkdir(parents=True, exist_ok=True)
                    action.destination.rename(staging)
            for action, staging in reversed(staged):
                if staging.exists() and action.source is not None:
                    action.source.parent.mkdir(parents=True, exist_ok=True)
                    staging.rename(action.source)
            raise
        else:
            for _, staging in staged:
                root = staging.parent
                if root.exists():
                    shutil.rmtree(root, ignore_errors=True)

    def recover_pending(self, project: ProjectSettings) -> tuple[str, ...]:
        """Restore old paths after an interrupted migration, or finalize a committed one."""
        journal_root = (
            self.resolver.resolve_project_root(project)
            / ".houd2"
            / "folder_migrations"
        )
        if not journal_root.is_dir():
            return ()
        recovered: list[str] = []
        for journal in sorted(journal_root.glob("*.json")):
            data = json.loads(journal.read_text(encoding="utf-8"))
            migration_id = str(data.get("migration_id", journal.stem))
            raw_actions = data.get("actions", [])
            if not isinstance(raw_actions, list):
                continue
            actions = [item for item in raw_actions if isinstance(item, dict)]
            if self._migration_is_committed(project, migration_id, actions):
                journal.unlink(missing_ok=True)
                recovered.append(f"Finalized folder migration {migration_id}")
                continue

            payloads: list[tuple[Path, Path]] = []
            recovery_root = journal_root / f"{migration_id}.__recovery__"
            status = str(data.get("status", "running"))
            for index, item in enumerate(
                action for action in actions if action.get("source")
            ):
                task_name = str(item["task"])
                role = str(item["role"])
                task_root = self.resolver.resolve_task_root(project, task_name)
                houdini_root = task_root / "houdini"
                source = Path(str(item["source"])).resolve()
                destination = Path(str(item["destination"])).resolve()
                if houdini_root.resolve() not in source.parents:
                    raise ValueError(f"Unsafe migration source in {journal}")
                if houdini_root.resolve() not in destination.parents:
                    raise ValueError(f"Unsafe migration destination in {journal}")
                staging = (
                    task_root
                    / ".houd2"
                    / "folder_migrations"
                    / migration_id
                    / f"{index:04d}_{role}"
                )
                payload = destination if status == "placed" else staging
                if not payload.exists():
                    continue
                recovery = recovery_root / f"{index:04d}_{role}"
                recovery.parent.mkdir(parents=True, exist_ok=True)
                payload.rename(recovery)
                payloads.append((recovery, source))
            for payload, source in reversed(payloads):
                source.parent.mkdir(parents=True, exist_ok=True)
                payload.rename(source)
            shutil.rmtree(recovery_root, ignore_errors=True)
            for item in actions:
                if item.get("kind") != "create":
                    continue
                destination = Path(str(item["destination"]))
                try:
                    destination.rmdir()
                except OSError:
                    pass
            journal.unlink(missing_ok=True)
            recovered.append(f"Rolled back folder migration {migration_id}")
        return tuple(recovered)

    @staticmethod
    def _write_journal(path: Path, data: dict[str, object]) -> None:
        temporary = path.with_suffix(".json.part")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        temporary.replace(path)

    def _migration_is_committed(
        self,
        project: ProjectSettings,
        migration_id: str,
        actions: list[dict[str, object]],
    ) -> bool:
        by_role = {item.role: item for item in project.folders if item.enabled}
        move_index = 0
        for item in actions:
            role = str(item["role"])
            task = str(item["task"])
            definition = by_role.get(role)
            if definition is None:
                return False
            expected = self.resolver.resolve_houdini_folder(
                project, task, definition.relative_path
            )
            destination = Path(str(item["destination"])).resolve()
            staging_exists = False
            if item.get("source"):
                staging = (
                    self.resolver.resolve_task_root(project, task)
                    / ".houd2"
                    / "folder_migrations"
                    / migration_id
                    / f"{move_index:04d}_{role}"
                )
                staging_exists = staging.exists()
                move_index += 1
            if expected != destination or staging_exists or not destination.exists():
                return False
        return True

    @staticmethod
    def _validate_moves(
        task: TaskSettings, moves: list[FolderMigrationAction]
    ) -> list[str]:
        blockers: list[str] = []
        sources = {item.source for item in moves}
        for action in moves:
            source = action.source
            assert source is not None
            is_junction = getattr(source, "is_junction", lambda: False)
            if source.is_symlink() or is_junction():
                blockers.append(f"{task.name}/{action.role}: linked source is not supported")
            destination = action.destination
            destination_is_junction = getattr(
                destination, "is_junction", lambda: False
            )
            if (
                destination.is_file()
                or destination.is_symlink()
                or destination_is_junction()
            ):
                blockers.append(f"{task.name}/{action.role}: destination is not a folder")
            elif destination.exists() and destination not in sources:
                try:
                    if any(destination.iterdir()):
                        blockers.append(
                            f"{task.name}/{action.role}: destination is not empty"
                        )
                except OSError:
                    blockers.append(f"{task.name}/{action.role}: destination is unreadable")
            for other in moves:
                if other is action or other.source is None:
                    continue
                if source in other.source.parents or other.source in source.parents:
                    blockers.append(
                        f"{task.name}: nested migration sources require manual cleanup"
                    )
        return blockers
