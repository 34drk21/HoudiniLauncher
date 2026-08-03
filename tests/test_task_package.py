from __future__ import annotations

import json
from pathlib import Path

import pytest

from houd2launcher.core.hip_manager import HipManager
from houd2launcher.core.models import ProjectSettings, TaskSettings
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.core.task_package import TaskPackageService
from houd2launcher.core.exceptions import PathSafetyError


def _source_task(project, repository, resolver):
    ProjectManager(repository, resolver).create(project)
    tasks = TaskManager(repository, resolver)
    task = tasks.create(
        project,
        TaskSettings(
            project_id=project.project_id,
            name="fire",
            recommended_installation_id="source-machine-install",
        ),
    )
    hips = HipManager(repository, resolver)
    version, hip_path = hips.next_path(project, task, "QA")
    hip_path.write_bytes(b"hip file")
    hips.register_created(
        project, task, hip_path, version, "QA", "source-machine-install"
    )
    return tasks, task, hip_path


def test_export_excludes_cache_roles_and_writes_verified_manifest(
    project, repository, resolver, tmp_path: Path
) -> None:
    tasks, task, hip_path = _source_task(project, repository, resolver)
    houdini = resolver.resolve_houdini_root(project, task)
    (houdini / "scripts").mkdir()
    (houdini / "scripts" / "tool.py").write_text("print('ok')", encoding="utf-8")
    geo = resolver.resolve_role(project, task, "geo_cache") / "smoke" / "v1"
    geo.mkdir(parents=True)
    (geo / "smoke.0001.bgeo.sc").write_bytes(b"cache")
    abc = resolver.resolve_role(project, task, "alembic")
    (abc / "asset.abc").write_bytes(b"abc cache")
    trash = resolver.resolve_task_root(project, task.name) / ".houd2" / "trash" / "caches"
    trash.mkdir(parents=True)
    (trash / "old.bgeo").write_bytes(b"old")
    project.environment = {"SHOW": "fire", "API_TOKEN": "secret", "LOCAL": "D:/private"}

    package = TaskPackageService(resolver, tasks).export(
        project, task, tmp_path / "delivery", ["21.0.440"]
    )
    manifest = json.loads((package / "manifest.json").read_text(encoding="utf-8"))
    listed = {item["relative_path"] for item in manifest["files"]}
    assert f"task/houdini/{hip_path.name}" in listed
    assert "task/houdini/scripts/tool.py" in listed
    assert not any("/geo/" in path or "/trash/caches/" in path for path in listed)
    assert "task/houdini/abc/asset.abc" in listed
    assert {"geo_cache", ".houd2/trash/caches"} <= set(manifest["excluded_roles"])
    assert "alembic" not in manifest["excluded_roles"]
    assert manifest["source_houdini_versions"] == ["21.0.440"]
    context = json.loads((package / "project_context.json").read_text(encoding="utf-8"))
    assert "project_root" not in context
    assert context["environment"] == {"SHOW": "fire"}
    preview = TaskPackageService(resolver, tasks).preview_import(package, project)
    assert preview.total_size == sum(item["size"] for item in manifest["files"])


def test_import_without_collision_preserves_task_id_and_clears_machine_ids(
    project, repository, resolver, tmp_path: Path
) -> None:
    tasks, task, hip_path = _source_task(project, repository, resolver)
    service = TaskPackageService(resolver, tasks)
    package = service.export(project, task, tmp_path / "delivery")
    target = ProjectSettings(name="Target", project_root=tmp_path / "Target")
    ProjectManager(repository, resolver).create(target)

    preview = service.preview_import(package, target)
    imported = service.import_package(package, target, preview)

    assert not preview.renamed
    assert imported.task_id == task.task_id
    assert imported.recommended_installation_id is None
    imported_hip = resolver.resolve_houdini_root(target, imported) / hip_path.name
    metadata = HipManager(repository, resolver).list_hips(target, imported)[0].metadata
    assert imported_hip.is_file()
    assert metadata.task_id == task.task_id
    assert metadata.last_saved_with is None
    assert metadata.recommended_installation_id is None


def test_collision_import_renames_task_managed_hip_and_metadata(
    project, repository, resolver, tmp_path: Path
) -> None:
    tasks, task, old_hip = _source_task(project, repository, resolver)
    service = TaskPackageService(resolver, tasks)
    package = service.export(project, task, tmp_path / "delivery")

    preview = service.preview_import(package, project)
    imported = service.import_package(package, project, preview)
    imported_hips = HipManager(repository, resolver).list_hips(project, imported)

    assert preview.renamed
    assert imported.name == "fire_copy"
    assert imported.task_id != task.task_id
    assert len(imported_hips) == 1
    assert imported_hips[0].path.name.startswith("fire_copy_v001_QA")
    assert imported_hips[0].path.name != old_hip.name
    assert imported_hips[0].metadata.task_id == imported.task_id


def test_corrupt_and_traversal_packages_are_rejected(
    project, repository, resolver, tmp_path: Path
) -> None:
    tasks, task, _ = _source_task(project, repository, resolver)
    service = TaskPackageService(resolver, tasks)
    corrupt = service.export(project, task, tmp_path / "corrupt")
    (corrupt / "task" / ".houd2" / "task.json").write_bytes(b"changed")
    with pytest.raises(ValueError, match="Checksum mismatch"):
        service.preview_import(corrupt, project)

    traversal = service.export(project, task, tmp_path / "traversal")
    manifest_path = traversal / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["files"][0]["relative_path"] = "../escape.hip"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    with pytest.raises(PathSafetyError):
        service.preview_import(traversal, project)


def test_export_rejects_destination_inside_source_task(
    project, repository, resolver
) -> None:
    tasks, task, _ = _source_task(project, repository, resolver)
    with pytest.raises(PathSafetyError):
        TaskPackageService(resolver, tasks).export(
            project, task, resolver.resolve_task_root(project, task.name) / "delivery"
        )
