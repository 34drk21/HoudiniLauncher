from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from houd2_cache.manifest import create_manifest, write_manifest
from houd2launcher.core.cache_catalog import CacheCatalogService
from houd2launcher.core.models import TaskSettings
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager


def test_catalog_lists_manifest_and_legacy_caches(project, repository, resolver) -> None:
    projects = ProjectManager(repository, resolver)
    tasks = TaskManager(repository, resolver)
    projects.create(project)
    task = tasks.create(project, TaskSettings(project_id=project.project_id, name="fire"))
    geo_root = resolver.resolve_role(project, task, "geo_cache")

    version_root = geo_root / "smoke" / "v003"
    cache_file = version_root / "geo" / "smoke.1001.bgeo.sc"
    cache_file.parent.mkdir(parents=True)
    cache_file.write_bytes(b"cache")
    context = SimpleNamespace(
        project_id=project.project_id, task_id=task.task_id,
        user_id="user-id", user_display_name="QA Artist", machine_id="machine-id",
    )
    manifest = create_manifest(
        context=context, cache_name="smoke", version=3, description="Main smoke",
        file_pattern="smoke/v003/geo/smoke.$F4.bgeo.sc",
        frame_start=1001, frame_end=1001, frame_step=1, fps=24,
        file_count=1, size_bytes=5,
    )
    write_manifest(version_root / "cache_manifest.json", manifest)

    legacy_root = geo_root / "debris" / "v1"
    legacy_root.mkdir(parents=True)
    (legacy_root / "debris_v1.1001.bgeo.sc").write_bytes(b"old")
    service = CacheCatalogService(projects, tasks, resolver)
    records = service.list_caches(project.project_id, task.task_id)

    assert [(item["cache_name"], item["version"]) for item in records] == [
        ("debris", 1), ("smoke", 3)
    ]
    smoke = records[1]
    assert smoke["creator_display_name"] == "QA Artist"
    assert smoke["file_pattern"] == "smoke/v003/geo/smoke.$F4.bgeo.sc"
    assert smoke["loadable"] is True
    assert records[0]["legacy"] is True
    assert records[0]["creator_display_name"] == "Unknown"


def test_catalog_ignores_writing_versions(project, repository, resolver) -> None:
    projects = ProjectManager(repository, resolver)
    tasks = TaskManager(repository, resolver)
    projects.create(project)
    task = tasks.create(project, TaskSettings(project_id=project.project_id, name="sim"))
    writing = resolver.resolve_role(project, task, "geo_cache") / "water" / "v002.__writing__"
    writing.mkdir(parents=True)
    (writing / "water.1001.bgeo.sc").write_bytes(b"partial")
    assert CacheCatalogService(projects, tasks, resolver).list_caches(project.project_id, task.task_id) == []
