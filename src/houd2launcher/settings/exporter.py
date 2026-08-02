from __future__ import annotations

import os
from pathlib import Path

from pydantic import BaseModel

from ..core.models import ProjectSettings, SettingsPackage, TaskSettings


SECRET_MARKERS = ("PASSWORD", "TOKEN", "SECRET", "CREDENTIAL", "API_KEY")
PROJECT_SECTIONS = ("folders", "environment", "search_paths", "naming", "houdini", "default_frames")
TASK_SECTIONS = ("frames", "environment", "recommended_installation_id")


def _safe_environment(values: dict[str, str]) -> dict[str, str]:
    return {
        name: value
        for name, value in values.items()
        if not any(marker in name.upper() for marker in SECRET_MARKERS)
    }


def build_package(model: ProjectSettings | TaskSettings) -> SettingsPackage:
    """Build a portable, credential-filtered settings package."""
    scope = "project" if isinstance(model, ProjectSettings) else "task"
    allowed = PROJECT_SECTIONS if scope == "project" else TASK_SECTIONS
    dumped = model.model_dump(mode="json")
    sections = {name: dumped[name] for name in allowed}
    if "environment" in sections:
        sections["environment"] = _safe_environment(model.environment)
    return SettingsPackage(scope=scope, sections=sections)


def export_package(model: ProjectSettings | TaskSettings, destination: Path) -> Path:
    """Atomically export selected settings sections to JSON."""
    package = build_package(model)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".part")
    temporary.write_text(package.model_dump_json(indent=2), encoding="utf-8")
    os.replace(temporary, destination)
    return destination

