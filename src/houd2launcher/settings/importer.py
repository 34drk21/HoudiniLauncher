from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from ..core.config import atomic_write_model, backup_file, load_model
from ..core.exceptions import SettingsImportError
from ..core.models import ProjectSettings, SettingsPackage, TaskSettings
from .diff import Difference, diff_values


SettingsModel = TypeVar("SettingsModel", ProjectSettings, TaskSettings)
ImportMode = Literal["merge", "overwrite", "replace_section"]


def load_package(path: Path) -> SettingsPackage:
    """Load and fully validate a settings package before any mutation."""
    try:
        return SettingsPackage.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise SettingsImportError(str(exc)) from exc


def preview_import(
    current: ProjectSettings | TaskSettings, package: SettingsPackage
) -> list[Difference]:
    """Return differences for an import preview without changing settings."""
    _validate_scope(current, package)
    current_sections = {
        name: current.model_dump(mode="json").get(name) for name in package.sections
    }
    return diff_values(current_sections, package.sections)


def apply_import(
    current: SettingsModel,
    package: SettingsPackage,
    target_path: Path,
    mode: ImportMode = "overwrite",
    selected_sections: set[str] | None = None,
) -> tuple[SettingsModel, Path | None]:
    """Validate a merged candidate, back up the target, then atomically save it."""
    _validate_scope(current, package)
    sections = selected_sections or set(package.sections)
    unknown = sections - set(package.sections)
    if unknown:
        raise SettingsImportError(f"Unknown import sections: {sorted(unknown)}")
    candidate_data = deepcopy(current.model_dump(mode="python"))
    for section in sections:
        incoming = deepcopy(package.sections[section])
        existing = candidate_data.get(section)
        if mode == "merge" and isinstance(existing, dict) and isinstance(incoming, dict):
            merged = dict(existing)
            for key, value in incoming.items():
                merged.setdefault(key, value)
            candidate_data[section] = merged
        elif mode in {"overwrite", "replace_section"}:
            if mode == "overwrite" and isinstance(existing, dict) and isinstance(incoming, dict):
                merged = dict(existing)
                merged.update(incoming)
                candidate_data[section] = merged
            else:
                candidate_data[section] = incoming
        else:
            candidate_data[section] = incoming
    try:
        candidate = type(current).model_validate(candidate_data)
    except ValidationError as exc:
        raise SettingsImportError(str(exc)) from exc
    backup = backup_file(target_path)
    atomic_write_model(target_path, candidate)
    return candidate, backup


def _validate_scope(
    current: ProjectSettings | TaskSettings, package: SettingsPackage
) -> None:
    expected = "project" if isinstance(current, ProjectSettings) else "task"
    if package.scope != expected:
        raise SettingsImportError(
            f"Cannot import {package.scope} settings into a {expected} target"
        )

