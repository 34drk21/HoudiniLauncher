from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from houd2launcher.core.config import atomic_write_model, load_model
from houd2launcher.core.exceptions import SettingsImportError
from houd2launcher.core.folder_migration import FolderStructureMigrator
from houd2launcher.core.models import (
    FolderDefinition,
    ProjectSettings,
    SettingsPackage,
    TaskSettings,
)
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.database.repositories import LauncherRepository
from houd2launcher.settings.exporter import build_package, export_package
from houd2launcher.settings.importer import (
    apply_import,
    build_import_candidate,
    identify_import,
    load_package,
    preview_import,
)


def test_project_export_filters_secrets(tmp_path: Path, project: ProjectSettings) -> None:
    project.environment = {"CACHE_ROOT": "cache", "API_TOKEN": "secret"}
    project.description = "Portable description"
    project.houdini.default_installation_id = "local-houdini"
    path = export_package(project, tmp_path / "export.json")
    package = load_package(path)
    assert package.schema_version == 2
    assert package.scope == "project"
    assert package.source_id == project.project_id
    assert package.source_name == project.name
    assert package.sections["description"] == "Portable description"
    assert package.sections["environment"] == {"CACHE_ROOT": "cache"}
    assert "default_installation_id" not in package.sections["houdini"]


def test_import_preview_backup_and_overwrite(tmp_path: Path, project: ProjectSettings) -> None:
    target = tmp_path / "project.json"
    atomic_write_model(target, project)
    incoming = project.model_copy(deep=True)
    incoming.environment = {"CACHE_ROOT": "D:/cache"}
    package = load_package(export_package(incoming, tmp_path / "incoming.json"))
    assert preview_import(project, package)
    imported, backup = apply_import(project, package, target, "overwrite")
    assert imported.environment["CACHE_ROOT"] == "D:/cache"
    assert backup is not None and backup.is_file()


def test_invalid_json_does_not_change_existing_settings(
    tmp_path: Path, project: ProjectSettings
) -> None:
    target = tmp_path / "project.json"
    atomic_write_model(target, project)
    before = target.read_bytes()
    invalid = tmp_path / "invalid.json"
    invalid.write_text("{not json", encoding="utf-8")
    with pytest.raises(SettingsImportError):
        load_package(invalid)
    assert target.read_bytes() == before


def test_exact_project_update_replaces_portable_settings_but_keeps_identity(
    project: ProjectSettings,
) -> None:
    project.description = "Old"
    project.environment = {"LOCAL_ONLY": "keep only when not replaced"}
    project.houdini.default_installation_id = "target-installation"
    incoming = project.model_copy(deep=True)
    incoming.description = "Updated"
    incoming.environment = {"CACHE_ROOT": "shared/cache"}
    incoming.houdini.default_installation_id = "source-installation"
    incoming.houdini.fallback_policy = "newer_compatible"

    package = build_package(incoming)
    identity = identify_import(project, package)
    candidate = build_import_candidate(project, package, "replace_section")

    assert identity.status == "exact"
    assert candidate.project_id == project.project_id
    assert candidate.name == project.name
    assert candidate.project_root == project.project_root
    assert candidate.description == "Updated"
    assert candidate.environment == {"CACHE_ROOT": "shared/cache"}
    assert candidate.houdini.default_installation_id == "target-installation"
    assert candidate.houdini.fallback_policy == "newer_compatible"


def test_name_match_and_mismatch_are_distinguished(project: ProjectSettings) -> None:
    renamed_identity = project.model_copy(
        deep=True, update={"project_id": str(uuid4())}
    )
    assert identify_import(project, build_package(renamed_identity)).status == "name_match"

    other = renamed_identity.model_copy(deep=True, update={"name": "OtherProject"})
    assert identify_import(project, build_package(other)).status == "mismatch"


def test_task_update_keeps_target_ids_and_local_installation(
    project: ProjectSettings,
) -> None:
    task = TaskSettings(
        project_id=project.project_id,
        name="fire",
        description="Old",
        owner="old-owner",
        recommended_installation_id="target-installation",
    )
    incoming = task.model_copy(deep=True)
    incoming.description = "Updated"
    incoming.owner = "new-owner"
    incoming.status = "on_hold"
    incoming.frames.end = 1200
    incoming.recommended_installation_id = "source-installation"

    package = build_package(incoming, project)
    candidate = build_import_candidate(task, package, "replace_section")

    assert package.source_project_id == project.project_id
    assert package.source_project_name == project.name
    assert "recommended_installation_id" not in package.sections
    assert candidate.task_id == task.task_id
    assert candidate.project_id == task.project_id
    assert candidate.name == task.name
    assert candidate.description == "Updated"
    assert candidate.owner == "new-owner"
    assert candidate.status == "on_hold"
    assert candidate.frames.end == 1200
    assert candidate.recommended_installation_id == "target-installation"


def test_task_name_match_requires_the_same_project(project: ProjectSettings) -> None:
    target = TaskSettings(project_id=project.project_id, name="fire")
    same_project = target.model_copy(deep=True, update={"task_id": str(uuid4())})
    other_project = same_project.model_copy(
        deep=True, update={"project_id": str(uuid4())}
    )

    assert identify_import(target, build_package(same_project)).status == "name_match"
    assert identify_import(target, build_package(other_project)).status == "mismatch"


def test_schema_v1_package_remains_importable(project: ProjectSettings) -> None:
    package = SettingsPackage.model_validate(
        {
            "schema_version": 1,
            "scope": "project",
            "sections": {"environment": {"CACHE_ROOT": "legacy/cache"}},
        }
    )

    assert identify_import(project, package).status == "legacy"
    candidate = build_import_candidate(project, package, "replace_section")
    assert candidate.environment == {"CACHE_ROOT": "legacy/cache"}


def test_imported_folder_structure_migrates_all_tasks(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    projects = ProjectManager(repository, resolver)
    projects.create(project)
    tasks = TaskManager(repository, resolver)
    task_models = [
        tasks.create(project, TaskSettings(project_id=project.project_id, name=name))
        for name in ("fire", "smoke")
    ]
    for task in task_models:
        (resolver.resolve_role(project, task, "geo_cache") / "keep.txt").write_text(
            task.name, encoding="utf-8"
        )
    incoming = project.model_copy(deep=True)
    incoming.folders[0].relative_path = "cache/geo"
    incoming.folders.append(
        FolderDefinition(
            key="scripts",
            display_name="Scripts",
            role="scripts",
            relative_path="scripts",
        )
    )
    candidate = build_import_candidate(
        project, build_package(incoming), "replace_section", {"folders"}
    )
    migrator = FolderStructureMigrator(resolver)
    plan = migrator.plan(project, candidate, task_models)

    assert not plan.blockers
    assert sum(item.kind == "move" for item in plan.actions) == 2
    assert sum(item.kind == "create" for item in plan.actions) == 2
    migrator.apply(project, plan)
    projects.save(candidate)
    migrator.recover_pending(candidate)

    for task in task_models:
        houdini_root = resolver.resolve_houdini_root(candidate, task)
        assert (houdini_root / "cache" / "geo" / "keep.txt").read_text(
            encoding="utf-8"
        ) == task.name
        assert (houdini_root / "scripts").is_dir()
