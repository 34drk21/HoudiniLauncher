from __future__ import annotations

import re
import string
from dataclasses import dataclass
from pathlib import Path

from .models import ProjectSettings, TaskSettings


SUPPORTED_HIP_EXTENSIONS = {".hip", ".hiplc", ".hipnc"}


@dataclass(frozen=True, slots=True)
class ParsedHipName:
    """Version and user parsed from a managed HIP filename."""

    version: int
    user: str
    extension: str


def parse_managed_hip_name(
    path: Path, project: ProjectSettings, task: TaskSettings
) -> ParsedHipName | None:
    """Parse only HIP names matching the active task and configured padding."""
    if path.suffix.lower() not in SUPPORTED_HIP_EXTENSIONS:
        return None
    pattern_parts = ["^"]
    seen_version = False
    seen_user = False
    for literal, field_name, _format_spec, _conversion in string.Formatter().parse(
        project.naming.hip_template
    ):
        pattern_parts.append(re.escape(literal))
        if field_name is None:
            continue
        if field_name == "project":
            pattern_parts.append(re.escape(project.name))
        elif field_name == "task":
            pattern_parts.append(re.escape(task.name))
        elif field_name == "version":
            if seen_version:
                return None
            pattern_parts.append(
                rf"(?P<version>\d{{{project.naming.version_padding},}})"
            )
            seen_version = True
        elif field_name == "user":
            if seen_user:
                return None
            pattern_parts.append(r"(?P<user>[^/\\]+?)")
            seen_user = True
        elif field_name == "date":
            pattern_parts.append(r"\d{8}")
        elif field_name == "houdini_version":
            pattern_parts.append(r"[A-Za-z0-9_.-]+")
        elif field_name == "extension":
            pattern_parts.append(r"(?:hip|hiplc|hipnc)")
        else:
            return None
    if not seen_version:
        return None
    pattern_parts.append("$")
    pattern = re.compile("".join(pattern_parts), re.IGNORECASE)
    match = pattern.fullmatch(path.name)
    if not match:
        return None
    version = int(match.group("version"))
    if version < 1:
        return None
    user = match.groupdict().get("user") or "unknown"
    return ParsedHipName(version, user, path.suffix.lower().lstrip("."))


def next_version(versions: list[int]) -> int:
    """Return one greater than the highest positive HIP version."""
    valid = [version for version in versions if version > 0]
    return max(valid, default=0) + 1
