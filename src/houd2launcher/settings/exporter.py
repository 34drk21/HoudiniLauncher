from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

from ..core.models import ProjectSettings, SettingsPackage, TaskSettings


SECRET_MARKERS = ("PASSWORD", "TOKEN", "SECRET", "CREDENTIAL", "API_KEY")
PROJECT_SECTIONS = (
    "description",
    "folders",
    "environment",
    "search_paths",
    "naming",
    "houdini",
    "default_frames",
    "sdm_default_folder_roles",
)
TASK_SECTIONS = ("description", "status", "owner", "frames", "environment")


def _safe_environment(values: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in values.items()
        if not any(marker in name.upper() for marker in SECRET_MARKERS)
    }


def build_package(
    model: ProjectSettings | TaskSettings,
    source_project: ProjectSettings | None = None,
) -> SettingsPackage:
    """Build a portable, credential-filtered settings package."""
    scope = "project" if isinstance(model, ProjectSettings) else "task"
    allowed = PROJECT_SECTIONS if scope == "project" else TASK_SECTIONS
    dumped = model.model_dump(mode="json")
    sections = {name: dumped[name] for name in allowed}
    if "environment" in sections:
        sections["environment"] = _safe_environment(model.environment)
    if scope == "project":
        houdini = dict(sections["houdini"])
        houdini.pop("default_installation_id", None)
        sections["houdini"] = houdini
        return SettingsPackage(
            scope=scope,
            source_id=model.project_id,
            source_name=model.name,
            sections=sections,
        )
    return SettingsPackage(
        scope=scope,
        source_id=model.task_id,
        source_name=model.name,
        source_project_id=model.project_id,
        source_project_name=(
            source_project.name
            if source_project and source_project.project_id == model.project_id
            else None
        ),
        sections=sections,
    )


def export_package(
    model: ProjectSettings | TaskSettings,
    destination: Path,
    source_project: ProjectSettings | None = None,
) -> Path:
    """Atomically export selected settings sections to JSON."""
    package = build_package(model, source_project)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_text(package.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    return destination
