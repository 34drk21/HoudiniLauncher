from __future__ import annotations

import re
from pathlib import Path, PurePosixPath, PureWindowsPath

from .exceptions import PathSafetyError


WINDOWS_INVALID_CHARS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
WINDOWS_RESERVED_NAMES = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{index}" for index in range(1, 10)),
    *(f"LPT{index}" for index in range(1, 10)),
}
NAME_PATTERN = re.compile(r"^[^<>:\"/\\|?*\x00-\x1f]+$")
ENVIRONMENT_NAME_PATTERN = re.compile(r"^[A-Z_][A-Z0-9_]*$")


def validate_filename_component(value: str, label: str = "Name") -> str:
    """Validate a single user-facing Windows-compatible path component."""
    cleaned = value.strip()
    if not cleaned or cleaned in {".", ".."} or not NAME_PATTERN.fullmatch(cleaned):
        raise ValueError(f"{label} contains invalid filename characters")
    if cleaned.endswith((" ", ".")):
        raise ValueError(f"{label} cannot end with a space or dot")
    if cleaned.split(".", 1)[0].upper() in WINDOWS_RESERVED_NAMES:
        raise ValueError(f"{label} uses a reserved Windows filename")
    return cleaned


def validate_relative_path(value: str, label: str = "Relative path") -> str:
    """Validate and normalize a safe project-relative POSIX-style path."""
    cleaned = value.strip().replace("\\", "/")
    if not cleaned:
        raise ValueError(f"{label} cannot be empty")
    if PureWindowsPath(cleaned).is_absolute() or PurePosixPath(cleaned).is_absolute():
        raise ValueError(f"{label} must be relative")
    parts = PurePosixPath(cleaned).parts
    if any(part in {"", ".", ".."} for part in parts):
        raise ValueError(f"{label} cannot contain '.', '..', or empty segments")
    for part in parts:
        validate_filename_component(part, label)
    return PurePosixPath(*parts).as_posix()


def ensure_within(root: Path, candidate: Path) -> Path:
    """Resolve a candidate path and ensure it remains below root."""
    resolved_root = root.expanduser().resolve()
    resolved_candidate = candidate.expanduser().resolve()
    if resolved_candidate != resolved_root and resolved_root not in resolved_candidate.parents:
        raise PathSafetyError(f"Path escapes project root: {candidate}")
    return resolved_candidate


def validate_environment_name(value: str) -> str:
    """Validate a user-defined environment variable name."""
    if not ENVIRONMENT_NAME_PATTERN.fullmatch(value):
        raise ValueError("Environment variable names must match ^[A-Z_][A-Z0-9_]*$")
    if value.startswith("HOUD2_"):
        raise ValueError("HOUD2_ is reserved for launcher internal variables")
    return value

