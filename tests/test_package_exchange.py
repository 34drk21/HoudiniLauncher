from __future__ import annotations

import json
from pathlib import Path

import pytest

from houd2launcher.core.hip_manager import HipManager
from houd2launcher.core.models import ProjectSettings, TaskSettings
from houd2launcher.core.package_exchange import PackageExchangeService
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.core.task_package import TaskPackageService


def _service(repository, resolver):
    projects = ProjectManager(repository, resolver)
    tasks = TaskManager(repository, resolver)
    task_packages = TaskPackageService(resolver, tasks)
    return projects, tasks, PackageExchangeService(
        resolver, projects, tasks, task_packages
    )


def _source(project, repository, resolver):
    projects, tasks, service = _service(repository, resolver)
    projects.create(project)
    task = tasks.create(
        project,
        TaskSettings(
            project_id=project.project_id,
            name="fire",
            environment={"SHOW": "demo", "API_TOKEN": "secret", "LOCAL": "D:/private"},
        ),
    )
    version, hip = HipManager(repository, resolver).next_path(project, task, "QA")
    hip.write_bytes(b"hip")
    HipManager(repository, resolver).register_created(
        project, task, hip, version, "QA", "source-installation"
    )
    geo = resolver.resolve_role(project, task, "geo_cache") / "smoke" / "v001"
    geo.mkdir(parents=True)
    (geo / "smoke.1001.bgeo.sc").write_bytes(b"cache")
    abc = resolver.resolve_role(project, task, "alembic")
    (abc / "asset.abc").write_bytes(b"abc")
    scripts = resolver.resolve_houdini_root(project, task) / "scripts"
    scripts.mkdir()
    (scripts / "tool.py").write_text("print('ok')", encoding="utf-8")
    return projects, tasks, service, task, hip


def test_task_exchange_publish_discover_import_as_copy(
    project, repository, resolver, tmp_path: Path
) -> None:
    projects, tasks, service, task, hip = _source(
        project, repository, resolver
    )
    exchange = tmp_path / "共有 Package"
    published = service.publish_task(
        exchange, project, task, publisher_user_id="user-id", publisher_name="QA"
    )
    discovered = service.discover(exchange)
    assert discovered[0].manifest.package_id == published.manifest.package_id
    listed = {item.relative_path for item in published.manifest.files}
    assert any(path.endswith(hip.name) for path in listed)
    assert not any("/geo/" in path or "/abc/" in path for path in listed)
    task_json = json.loads(
        (published.payload_root / "task" / ".houd2" / "task.json").read_text(
            encoding="utf-8"
        )
    )
    assert task_json["environment"] == {"SHOW": "demo"}

    target = ProjectSettings(name="Target", project_root=tmp_path / "Target")
    projects.create(target)
    preview = service.preview_import(discovered[0], target_project=target)
    assert preview.renamed
    assert preview.target_name == "fire_copy"
    result = service.import_package(preview, target_project=target)
    assert result.task is not None
    assert result.task.task_id != task.task_id
    assert result.path.is_dir()
    assert published.package_root.is_dir()


def test_project_exchange_excludes_caches_and_preserves_existing_project(
    project, repository, resolver, tmp_path: Path
) -> None:
    projects, tasks, service, task, hip = _source(
        project, repository, resolver
    )
    project.environment = {"SHOW": "demo", "PASSWORD": "secret", "LOCAL": "C:/private"}
    projects.save(project)
    exchange = tmp_path / "Exchange"
    published = service.publish_project(exchange, project, publisher_name="Supervisor")

    payload_text = (published.payload_root / ".houd2" / "project.json").read_text(
        encoding="utf-8"
    )
    assert str(project.project_root) not in payload_text
    assert "secret" not in payload_text
    assert not any(
        (published.payload_root / "fire" / "houdini" / "geo").rglob("*")
    )
    assert not (published.payload_root / "fire" / "houdini" / "abc").exists()
    assert (published.payload_root / "fire" / "houdini" / "scripts" / "tool.py").is_file()

    preview = service.preview_import(published, project_parent=tmp_path)
    assert preview.renamed
    assert preview.target_name == "DemoProject_copy"
    result = service.import_package(preview)
    assert project.project_root.is_dir()
    assert result.path.is_dir()
    imported_tasks = tasks.discover(result.project)
    assert len(imported_tasks) == 1
    assert imported_tasks[0].task_id != task.task_id
    assert (result.path / "fire" / "houdini" / hip.name).is_file()
    assert not (result.path / "fire" / "houdini" / "geo" / "smoke").exists()


def test_exchange_rejects_checksum_changes(
    project, repository, resolver, tmp_path: Path
) -> None:
    _, _, service, task, _ = _source(project, repository, resolver)
    published = service.publish_task(tmp_path / "exchange", project, task)
    task_json = published.payload_root / "task" / ".houd2" / "task.json"
    task_json.write_text("{}", encoding="utf-8")

    with pytest.raises(ValueError, match="Checksum mismatch"):
        service.preview_import(published, target_project=project)


def test_exchange_rejects_import_destination_inside_package(
    project, repository, resolver, tmp_path: Path
) -> None:
    _, _, service, _, _ = _source(project, repository, resolver)
    published = service.publish_project(tmp_path / "exchange", project)

    with pytest.raises(Exception, match="cannot be inside"):
        service.preview_import(published, project_parent=published.payload_root)
