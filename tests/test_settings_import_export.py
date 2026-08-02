from __future__ import annotations

from pathlib import Path

import pytest

from houd2launcher.core.config import atomic_write_model, load_model
from houd2launcher.core.exceptions import SettingsImportError
from houd2launcher.core.models import ProjectSettings
from houd2launcher.settings.exporter import export_package
from houd2launcher.settings.importer import apply_import, load_package, preview_import


def test_project_export_filters_secrets(tmp_path: Path, project: ProjectSettings) -> None:
    project.environment = {"CACHE_ROOT": "cache", "API_TOKEN": "secret"}
    path = export_package(project, tmp_path / "export.json")
    package = load_package(path)
    assert package.scope == "project"
    assert package.sections["environment"] == {"CACHE_ROOT": "cache"}


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

