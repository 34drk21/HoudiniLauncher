from __future__ import annotations

from pathlib import Path

from houd2launcher.core.hip_manager import HipManager
from houd2launcher.core.models import ProjectSettings, TaskSettings
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.database.repositories import LauncherRepository


def _created_task(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> TaskSettings:
    ProjectManager(repository, resolver).create(project)
    task = TaskSettings(project_id=project.project_id, name="shot010_fx")
    TaskManager(repository, resolver).create(project, task)
    return task


def test_detects_supported_extensions_non_recursively(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    task = _created_task(project, repository, resolver)
    root = resolver.resolve_houdini_root(project, task)
    for version, extension in enumerate(("hip", "hiplc", "hipnc"), start=1):
        (root / f"{task.name}_v{version:03d}_shota.{extension}").write_bytes(b"hip")
    nested = root / "geo"
    nested.mkdir(exist_ok=True)
    (nested / f"{task.name}_v999_shota.hip").write_bytes(b"nested")
    records = HipManager(repository, resolver).list_hips(project, task)
    assert [record.version for record in records] == [3, 2, 1]


def test_does_not_misdetect_invalid_versions(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    task = _created_task(project, repository, resolver)
    root = resolver.resolve_houdini_root(project, task)
    for name in (
        f"{task.name}_version001_shota.hip",
        f"other_v001_shota.hip",
        f"{task.name}_v1_shota.hip",
        f"{task.name}_v000_shota.hip",
    ):
        (root / name).write_bytes(b"invalid")
    assert HipManager(repository, resolver).list_hips(project, task) == []


def test_metadata_roundtrip_and_version_up(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    task = _created_task(project, repository, resolver)
    manager = HipManager(repository, resolver)
    version, path = manager.next_path(project, task, "shota")
    path.write_bytes(b"valid hip data")
    metadata = manager.register_created(
        project, task, path, version, "shota", "houdini-21", "first"
    )
    assert metadata.comment == "first"
    records = manager.list_hips(project, task)
    assert records[0].metadata.last_saved_with == "houdini-21"
    next_record = manager.version_up(project, task, records[0], "mika", "next")
    assert next_record.version == 2
    assert next_record.path.read_bytes() == b"valid hip data"

