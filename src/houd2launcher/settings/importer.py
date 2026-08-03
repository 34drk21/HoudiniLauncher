from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from ..core.config import atomic_write_model, backup_file, load_model
from ..core.exceptions import SettingsImportError
from ..core.models import ProjectSettings, SettingsPackage, TaskSettings
from .diff import Difference, diff_values


SettingsModel = TypeVar("SettingsModel", ProjectSettings, TaskSettings)
ImportMode = Literal["merge", "overwrite", "replace_section"]
IdentityStatus = Literal["exact", "name_match", "mismatch", "legacy"]

PROJECT_SECTIONS = {
    "description",
    "folders",
    "environment",
    "search_paths",
    "naming",
    "houdini",
    "default_frames",
    "sdm_default_folder_roles",
}
TASK_SECTIONS = {
    "description",
    "status",
    "owner",
    "frames",
    "environment",
    # Accepted for schema v1 compatibility, but never applied to this PC.
    "recommended_installation_id",
}


@dataclass(frozen=True, slots=True)
class ImportIdentity:
    """Describe how a settings package relates to its selected target."""

    status: IdentityStatus
    source_id: str | None
    source_name: str | None
    target_id: str
    target_name: str
    source_project_id: str | None = None
    source_project_name: str | None = None
    target_project_id: str | None = None

    @property
    def is_update(self) -> bool:
        return self.status in {"exact", "name_match"}


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
    incoming_sections = _effective_sections(current, package)
    current_sections = {
        name: current.model_dump(mode="json").get(name) for name in incoming_sections
    }
    return diff_values(current_sections, incoming_sections)


def identify_import(
    current: ProjectSettings | TaskSettings,
    package: SettingsPackage,
) -> ImportIdentity:
    """Classify exact updates, cautious name matches, and template imports."""
    _validate_scope(current, package)
    target_id = (
        current.project_id if isinstance(current, ProjectSettings) else current.task_id
    )
    if package.schema_version == 1 or not package.source_id or not package.source_name:
        status: IdentityStatus = "legacy"
    elif package.source_id == target_id:
        if (
            isinstance(current, TaskSettings)
            and package.source_project_id
            and package.source_project_id != current.project_id
        ):
            status = "mismatch"
        else:
            status = "exact"
    elif package.source_name.casefold() == current.name.casefold():
        if (
            isinstance(current, TaskSettings)
            and package.source_project_id
            and package.source_project_id != current.project_id
        ):
            status = "mismatch"
        else:
            status = "name_match"
    else:
        status = "mismatch"
    return ImportIdentity(
        status=status,
        source_id=package.source_id,
        source_name=package.source_name,
        target_id=target_id,
        target_name=current.name,
        source_project_id=package.source_project_id,
        source_project_name=package.source_project_name,
        target_project_id=(
            current.project_id if isinstance(current, TaskSettings) else None
        ),
    )


def build_import_candidate(
    current: SettingsModel,
    package: SettingsPackage,
    mode: ImportMode = "overwrite",
    selected_sections: set[str] | None = None,
) -> SettingsModel:
    """Build and validate an import candidate without writing any files."""
    _validate_scope(current, package)
    effective = _effective_sections(current, package)
    sections = set(effective) if selected_sections is None else set(selected_sections)
    unknown = sections - set(package.sections)
    if unknown:
        raise SettingsImportError(f"Unknown import sections: {sorted(unknown)}")
    sections &= set(effective)
    candidate_data = deepcopy(current.model_dump(mode="python"))
    for section in sections:
        incoming = deepcopy(effective[section])
        existing = candidate_data.get(section)
        if mode == "merge" and isinstance(existing, dict) and isinstance(incoming, dict):
            merged = dict(existing)
            for key, value in incoming.items():
                merged.setdefault(key, value)
            candidate_data[section] = merged
        elif (
            mode == "overwrite"
            and isinstance(existing, dict)
            and isinstance(incoming, dict)
        ):
            merged = dict(existing)
            merged.update(incoming)
            candidate_data[section] = merged
        else:
            candidate_data[section] = incoming
    try:
        return type(current).model_validate(candidate_data)
    except ValidationError as exc:
        raise SettingsImportError(str(exc)) from exc


def apply_import(
    current: SettingsModel,
    package: SettingsPackage,
    target_path: Path,
    mode: ImportMode = "overwrite",
    selected_sections: set[str] | None = None,
) -> tuple[SettingsModel, Path | None]:
    """Validate a merged candidate, back up the target, then atomically save it."""
    candidate = build_import_candidate(
        current, package, mode=mode, selected_sections=selected_sections
    )
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
    allowed = PROJECT_SECTIONS if expected == "project" else TASK_SECTIONS
    unknown = set(package.sections) - allowed
    if unknown:
        raise SettingsImportError(
            f"Package contains unsupported {expected} sections: {sorted(unknown)}"
        )


def _effective_sections(
    current: ProjectSettings | TaskSettings,
    package: SettingsPackage,
) -> dict[str, object]:
    """Remove machine-local values from incoming portable settings."""
    sections = deepcopy(package.sections)
    if isinstance(current, ProjectSettings):
        incoming_houdini = sections.get("houdini")
        if isinstance(incoming_houdini, dict):
            incoming_houdini.pop("default_installation_id", None)
            incoming_houdini["default_installation_id"] = (
                current.houdini.default_installation_id
            )
    else:
        sections.pop("recommended_installation_id", None)
    return sections
