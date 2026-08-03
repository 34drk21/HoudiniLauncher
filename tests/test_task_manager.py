from __future__ import annotations

from pathlib import Path

import pytest

from houd2launcher.core.models import FolderDefinition, ProjectSettings, TaskSettings
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.database.repositories import LauncherRepository


def test_task_creation_builds_configured_folders(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskSettings(project_id=project.project_id, name="wall_destruction_010")
    manager = TaskManager(repository, resolver)
    manager.create(project, task)
    assert resolver.resolve_task_metadata_path(project, task).is_file()
    assert resolver.resolve_houdini_root(project, task).is_dir()
    assert resolver.resolve_role(project, task, "geo_cache").is_dir()
    assert resolver.resolve_role(project, task, "alembic").is_dir()


def test_disabled_or_non_auto_folder_is_not_created(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    project.folders = [
        FolderDefinition(
            key="render",
            display_name="Render",
            role="render",
            relative_path="render",
            auto_create=False,
        )
    ]
    ProjectManager(repository, resolver).create(project)
    task = TaskSettings(project_id=project.project_id, name="magic_spell")
    TaskManager(repository, resolver).create(project, task)
    assert not resolver.resolve_role(project, task, "render").exists()


def test_task_rename_updates_folder_and_json(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskSettings(project_id=project.project_id, name="old_task")
    manager = TaskManager(repository, resolver)
    manager.create(project, task)
    manager.rename(project, task, "new_task")
    assert not (project.project_root / "old_task").exists()
    assert resolver.resolve_task_metadata_path(project, task).is_file()


def test_rejects_invalid_task_name(project: ProjectSettings) -> None:
    with pytest.raises(ValueError):
        TaskSettings(project_id=project.project_id, name="bad/task")


def test_archive_and_restore_task_updates_canonical_status(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    manager = TaskManager(repository, resolver)
    task = manager.create(
        project, TaskSettings(project_id=project.project_id, name="finished")
    )

    manager.archive(project, task)
    assert task.status == "archived"
    manager.restore(project, task)

    loaded = manager.load(project, resolver.resolve_task_metadata_path(project, task))
    assert loaded.status == "active"


def test_delete_task_permanently_removes_folder_and_indexes(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="delete_me")
    )
    hip = resolver.resolve_houdini_root(project, task) / "delete_me_v001_QA.hip"
    hip.write_bytes(b"hip")
    repository.upsert_hip(
        hip,
        task.task_id,
        1,
        "QA",
        resolver.resolve_hip_metadata_path(project, task, hip),
    )

    deleted = TaskManager(repository, resolver).delete_permanently(project, task)

    assert deleted == project.project_root / "delete_me"
    assert not deleted.exists()
    assert repository.list_tasks(project.project_id) == []


def test_delete_task_rejects_other_project(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
    tmp_path: Path,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="keep_me")
    )
    other = ProjectSettings(name="Other", project_root=tmp_path / "Other")
    ProjectManager(repository, resolver).create(other)

    with pytest.raises(ValueError, match="different project"):
        TaskManager(repository, resolver).delete_permanently(other, task)
    assert resolver.resolve_task_root(project, task.name).is_dir()
