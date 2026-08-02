from __future__ import annotations

from pathlib import Path

import pytest

from houd2launcher.core.models import ProjectSettings
from houd2launcher.core.config import atomic_write_model
from houd2launcher.core.exceptions import DuplicateRegistrationError
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.database.repositories import LauncherRepository
from houd2launcher.core.path_resolver import PathResolver


def test_create_register_and_unregister_project(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    manager = ProjectManager(repository, resolver)
    manager.create(project)
    assert resolver.resolve_project_metadata_path(project).is_file()
    assert manager.registered()[0].project_id == project.project_id
    manager.unregister(project.project_id)
    assert manager.registered() == []
    assert resolver.resolve_project_metadata_path(project).is_file()


def test_project_root_missing_is_not_returned(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    manager = ProjectManager(repository, resolver)
    repository.upsert_project(
        project.project_id,
        project.name,
        project.project_root,
        resolver.resolve_project_metadata_path(project),
    )
    assert manager.registered() == []


def test_project_id_survives_name_change(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    manager = ProjectManager(repository, resolver)
    manager.create(project)
    identifier = project.project_id
    project.name = "RenamedProject"
    manager.save(project)
    assert manager.registered()[0].project_id == identifier


def test_registered_repairs_stale_id_for_same_root_and_config(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    manager = ProjectManager(repository, resolver)
    manager.create(project)
    old_id = project.project_id
    repository.set_project_favorite(old_id, True)
    repository.record_activity(old_id, "before_id_repair")
    replacement = ProjectSettings(
        name=project.name,
        project_root=project.project_root,
    )
    atomic_write_model(resolver.resolve_project_metadata_path(project), replacement)

    loaded = manager.registered()
    records = repository.list_projects(include_archived=True)

    assert loaded[0].project_id == replacement.project_id
    assert records[0]["project_id"] == replacement.project_id
    assert records[0]["favorite"] == 1
    assert repository.history(replacement.project_id)[0]["event_type"] == "before_id_repair"


def test_add_existing_repairs_stale_id_but_rejects_same_id(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    manager = ProjectManager(repository, resolver)
    manager.create(project)
    replacement = ProjectSettings(name=project.name, project_root=project.project_root)
    atomic_write_model(resolver.resolve_project_metadata_path(project), replacement)

    added = manager.add_existing(project.project_root)

    assert added.project_id == replacement.project_id
    with pytest.raises(DuplicateRegistrationError, match="already registered"):
        manager.add_existing(project.project_root)
