from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from houd2launcher.core.cache_manager import CacheManager, CacheReference
from houd2launcher.core.exceptions import PathSafetyError
from houd2launcher.core.models import TaskSettings
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager


def test_discovers_used_and_unused_directory_versions(
    project, repository, resolver
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="cache_test")
    )
    cache_root = resolver.resolve_role(project, task, "geo_cache") / "smoke"
    for version, size in ((1, 10), (2, 25)):
        directory = cache_root / f"v{version:03d}"
        directory.mkdir(parents=True)
        (directory / "smoke.1001.bgeo.sc").write_bytes(b"x" * size)

    manager = CacheManager(resolver)
    records = manager.discover(
        project,
        task,
        [
            CacheReference(
                node_path="/obj/geo1/filecache1",
                parameter="file",
                raw_path="$HIP/geo/smoke/v002/smoke.$F4.bgeo.sc",
                expanded_path=cache_root / "v002" / "smoke.1001.bgeo.sc",
            )
        ],
    )

    assert [(record.version, record.is_used, record.size) for record in records] == [
        (1, False, 10),
        (2, True, 25),
    ]
    assert all(record.managed for record in records)
    assert records[1].node_paths == ("/obj/geo1/filecache1",)


def test_permanently_deletes_one_version_without_using_trash(project, repository, resolver) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="trash_test")
    )
    cache_root = resolver.resolve_role(project, task, "geo_cache") / "debris"
    for version in (1, 2):
        directory = cache_root / f"v{version:03d}"
        directory.mkdir(parents=True)
        (directory / "debris.1001.bgeo.sc").write_bytes(b"cache")
    manager = CacheManager(resolver)
    records = manager.discover(
        project,
        task,
        [
            CacheReference(
                node_path="/obj/debris/filecache1",
                parameter="file",
                raw_path="$HIP/geo/debris/v002/debris.$F4.bgeo.sc",
                expanded_path=cache_root / "v002" / "debris.1001.bgeo.sc",
            )
        ],
    )
    unused = next(record for record in records if not record.is_used)

    deleted = manager.delete_permanently(project, task, [unused])

    assert not (cache_root / "v001").exists()
    assert (cache_root / "v002").is_dir()
    assert deleted == ((cache_root / "v001").resolve(),)
    assert not (resolver.resolve_task_root(project, task.name) / ".houd2" / "trash").exists()


def test_outside_reference_is_not_in_geo_inventory(
    tmp_path: Path, project, repository, resolver
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="outside_test")
    )
    outside = tmp_path / "shared" / "v003" / "shared.1001.vdb"
    outside.parent.mkdir(parents=True)
    outside.write_bytes(b"vdb")
    records = CacheManager(resolver).discover(
        project,
        task,
        [CacheReference("/obj/file1", "file", str(outside), outside)],
    )
    assert records == ()


def test_all_geo_cache_names_are_listed_and_only_exact_version_is_used(
    project, repository, resolver
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="inventory_test")
    )
    root = resolver.resolve_role(project, task, "geo_cache")
    for cache_name in ("fire", "unreferenced"):
        for version in (1, 2):
            folder = root / cache_name / f"v{version}"
            folder.mkdir(parents=True)
            (folder / f"{cache_name}_v{version}.0001.bgeo.sc").write_bytes(b"cache")
    records = CacheManager(resolver).discover(
        project,
        task,
        [CacheReference("/obj/fire/filecache1", "sopoutput", "", root / "fire" / "v2" / "fire_v2.1001.bgeo.sc")],
    )
    assert {record.name for record in records} == {"fire", "unreferenced"}
    assert [record.version for record in records if record.is_used] == [2]


def test_parent_selection_can_delete_all_versions_and_outside_is_rejected(
    project, repository, resolver, tmp_path: Path
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="delete_all")
    )
    root = resolver.resolve_role(project, task, "geo_cache") / "dust"
    for version in (1, 2):
        folder = root / f"v{version}"
        folder.mkdir(parents=True)
        (folder / "dust.0001.vdb").write_bytes(b"x")
    manager = CacheManager(resolver)
    records = manager.discover(project, task, [])
    outside = tmp_path / "outside.vdb"
    outside.write_bytes(b"x")
    with pytest.raises(PathSafetyError):
        manager.delete_permanently(
            project, task, [replace(records[0], path=outside, targets=(outside,))]
        )
    manager.delete_permanently(project, task, list(records))
    assert not (root / "v1").exists()
    assert not (root / "v2").exists()


def test_v1_folder_with_sphere_frame_sequence_is_counted(
    project, repository, resolver
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="fire")
    )
    version_root = resolver.resolve_role(project, task, "geo_cache") / "sphere" / "v1"
    version_root.mkdir(parents=True)
    for frame in range(1, 6):
        (version_root / f"sphere_v1.{frame:04d}.bgeo.sc").write_bytes(b"x" * frame)

    records = CacheManager(resolver).discover(
        project,
        task,
        [
            CacheReference(
                node_path="/obj/geo1/sphere/filecache1",
                parameter="file",
                raw_path="$HIP/geo/sphere/v1/sphere_v1.$F4.bgeo.sc",
                # The HIP may currently be on a frame outside the cached range.
                expanded_path=version_root / "sphere_v1.1001.bgeo.sc",
            )
        ],
    )

    assert len(records) == 1
    assert records[0].is_used
    assert records[0].managed
    assert records[0].file_count == 5
    assert records[0].size == 15


def test_filename_versions_in_one_folder_only_mark_and_delete_the_exact_version(
    project, repository, resolver
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="filename_versions")
    )
    cache_root = resolver.resolve_role(project, task, "geo_cache") / "surface"
    cache_root.mkdir(parents=True)
    for version in (1, 2):
        for frame in (1, 2):
            (cache_root / f"surface_v{version}.{frame:04d}.vdb").write_bytes(b"x")
    manager = CacheManager(resolver)
    records = manager.discover(
        project,
        task,
        [CacheReference("/obj/file1", "file", "", cache_root / "surface_v2.1001.vdb")],
    )
    assert [(item.version, item.is_used, item.file_count) for item in records] == [
        (1, False, 2),
        (2, True, 2),
    ]
    manager.delete_permanently(project, task, [records[0]])
    assert not list(cache_root.glob("surface_v1.*.vdb"))
    assert len(list(cache_root.glob("surface_v2.*.vdb"))) == 2


def test_marker_and_writing_directories_are_not_inventory_files(
    project, repository, resolver
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="houd2_cache")
    )
    cache_root = resolver.resolve_role(project, task, "geo_cache") / "smoke"
    version_root = cache_root / "v001"
    geo = version_root / "geo"
    geo.mkdir(parents=True)
    (geo / "smoke.1001.bgeo.sc").write_bytes(b"cache")
    (version_root / "cache_marker.bgeo.sc").write_bytes(b"marker")
    writing = cache_root / "v002.__writing__" / "geo"
    writing.mkdir(parents=True)
    (writing / "smoke.1001.bgeo.sc").write_bytes(b"partial")

    records = CacheManager(resolver).discover(project, task, [])

    assert len(records) == 1
    assert records[0].version == 1
    assert records[0].file_count == 1
    assert records[0].size == 5
