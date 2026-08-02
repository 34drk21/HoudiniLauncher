from __future__ import annotations

from pathlib import Path

import pytest

from houd2launcher.core.models import FolderDefinition, ProjectSettings, TaskSettings
from houd2launcher.core.path_resolver import PathResolver


def test_resolves_project_task_and_houdini_roots(
    resolver: PathResolver, project: ProjectSettings
) -> None:
    task = TaskSettings(project_id=project.project_id, name="shot010_fx")
    assert resolver.resolve_project_root(project) == project.project_root
    assert resolver.resolve_task_root(project, task.name) == project.project_root / task.name
    assert resolver.resolve_houdini_root(project, task) == project.project_root / task.name / "houdini"


def test_resolves_folder_by_role(resolver: PathResolver, project: ProjectSettings) -> None:
    task = TaskSettings(project_id=project.project_id, name="dust_sim")
    assert resolver.resolve_role(project, task, "geo_cache") == (
        project.project_root / task.name / "houdini" / "geo"
    )


@pytest.mark.parametrize("name", ["..", "bad/name", "C:\\absolute", "CON", "trailing."])
def test_rejects_unsafe_task_names(
    resolver: PathResolver, project: ProjectSettings, name: str
) -> None:
    with pytest.raises(ValueError):
        resolver.resolve_task_root(project, name)


@pytest.mark.parametrize("path", ["../geo", "C:/geo", "/tmp/geo", "cache/../../outside"])
def test_rejects_unsafe_relative_folder_paths(path: str, project: ProjectSettings) -> None:
    with pytest.raises(ValueError):
        FolderDefinition(
            key="geo", display_name="Geo", role="geo_cache", relative_path=path
        )


def test_supports_nested_posix_relative_path(
    resolver: PathResolver, project: ProjectSettings
) -> None:
    project.folders = [
        FolderDefinition(
            key="geo", display_name="Geo", role="geo_cache", relative_path="cache/geo"
        )
    ]
    task = TaskSettings(project_id=project.project_id, name="smoke")
    assert resolver.resolve_role(project, task, "geo_cache") == (
        project.project_root / "smoke" / "houdini" / "cache" / "geo"
    )

