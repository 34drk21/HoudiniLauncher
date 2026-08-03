from __future__ import annotations

from houd2launcher.core.folder_migration import FolderStructureMigrator
from houd2launcher.core.models import FolderDefinition, ProjectSettings, TaskSettings
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.database.repositories import LauncherRepository


def test_folder_structure_change_moves_existing_data_and_creates_new_roles(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    manager = TaskManager(repository, resolver)
    tasks = [
        manager.create(project, TaskSettings(project_id=project.project_id, name=name))
        for name in ("fire", "smoke")
    ]
    for task in tasks:
        (resolver.resolve_role(project, task, "geo_cache") / "keep.bgeo.sc").write_bytes(
            b"cache"
        )
    proposed = project.model_copy(deep=True)
    proposed.folders = [
        FolderDefinition(
            key="geo",
            display_name="Geometry",
            role="geo_cache",
            relative_path="cache/geo",
        ),
        *project.folders[1:],
        FolderDefinition(
            key="scripts",
            display_name="Scripts",
            role="scripts",
            relative_path="scripts",
        ),
    ]
    migrator = FolderStructureMigrator(resolver)
    plan = migrator.plan(project, proposed, tasks)
    assert not plan.blockers
    assert sum(item.kind == "move" for item in plan.actions) == 2
    assert sum(item.kind == "create" for item in plan.actions) == 2

    migrator.apply(project, plan)

    for task in tasks:
        assert not (resolver.resolve_houdini_root(project, task) / "geo").exists()
        assert (
            resolver.resolve_houdini_root(project, task)
            / "cache"
            / "geo"
            / "keep.bgeo.sc"
        ).read_bytes() == b"cache"
        assert (resolver.resolve_houdini_root(project, task) / "scripts").is_dir()


def test_folder_structure_change_blocks_nonempty_destination(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="fire")
    )
    destination = resolver.resolve_houdini_root(project, task) / "cache" / "geo"
    destination.mkdir(parents=True)
    (destination / "collision.txt").write_text("keep", encoding="utf-8")
    proposed = project.model_copy(deep=True)
    proposed.folders[0].relative_path = "cache/geo"

    plan = FolderStructureMigrator(resolver).plan(project, proposed, [task])

    assert plan.blockers
    assert "destination is not empty" in plan.blockers[0]
    assert resolver.resolve_role(project, task, "geo_cache").is_dir()


def test_removed_role_is_retained_without_delete(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="fire")
    )
    old = resolver.resolve_role(project, task, "alembic")
    proposed = project.model_copy(deep=True)
    proposed.folders = [item for item in proposed.folders if item.role != "alembic"]

    plan = FolderStructureMigrator(resolver).plan(project, proposed, [task])

    assert old in plan.retained
    assert all(item.source != old for item in plan.actions)


def test_folder_structure_can_swap_two_role_paths(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="swap")
    )
    (resolver.resolve_role(project, task, "geo_cache") / "geo.txt").write_text(
        "geo", encoding="utf-8"
    )
    (resolver.resolve_role(project, task, "alembic") / "abc.txt").write_text(
        "abc", encoding="utf-8"
    )
    proposed = project.model_copy(deep=True)
    proposed.folders[0].relative_path = "abc"
    proposed.folders[1].relative_path = "geo"
    migrator = FolderStructureMigrator(resolver)
    plan = migrator.plan(project, proposed, [task])
    assert not plan.blockers

    migrator.apply(project, plan)

    houdini = resolver.resolve_houdini_root(project, task)
    assert (houdini / "abc" / "geo.txt").read_text(encoding="utf-8") == "geo"
    assert (houdini / "geo" / "abc.txt").read_text(encoding="utf-8") == "abc"


def test_pending_migration_rolls_back_until_project_settings_are_committed(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="recover")
    )
    source = resolver.resolve_role(project, task, "geo_cache")
    (source / "keep.txt").write_text("data", encoding="utf-8")
    proposed = project.model_copy(deep=True)
    proposed.folders[0].relative_path = "cache/geo"
    migrator = FolderStructureMigrator(resolver)
    plan = migrator.plan(project, proposed, [task])
    migrator.apply(project, plan)
    assert not source.exists()

    messages = migrator.recover_pending(project)

    assert messages and messages[0].startswith("Rolled back")
    assert (source / "keep.txt").read_text(encoding="utf-8") == "data"
    assert not (resolver.resolve_houdini_root(project, task) / "cache" / "geo").exists()


def test_pending_migration_is_finalized_after_project_settings_commit(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="commit")
    )
    source = resolver.resolve_role(project, task, "geo_cache")
    (source / "keep.txt").write_text("data", encoding="utf-8")
    proposed = project.model_copy(deep=True)
    proposed.folders[0].relative_path = "cache/geo"
    migrator = FolderStructureMigrator(resolver)
    migrator.apply(project, migrator.plan(project, proposed, [task]))

    messages = migrator.recover_pending(proposed)

    destination = resolver.resolve_houdini_root(project, task) / "cache" / "geo"
    assert messages and messages[0].startswith("Finalized")
    assert (destination / "keep.txt").read_text(encoding="utf-8") == "data"
    assert not source.exists()
