from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path, PurePosixPath

from .context import Houd2Context


_VERSION = re.compile(r"^v(?P<version>\d{1,6})$", re.IGNORECASE)
_INVALID_NAME = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{x}" for x in range(1, 10)), *(f"LPT{x}" for x in range(1, 10))}


@dataclass(frozen=True)
class CachePaths:
    cache_root: Path
    version_root: Path
    staging_root: Path
    geo_directory: Path
    staging_geo_directory: Path
    manifest_path: Path
    marker_path: Path
    file_pattern: str
    staging_file_pattern: str


def validate_cache_name(value: str) -> str:
    name = value.strip()
    if not name or name in {".", ".."} or _INVALID_NAME.search(name):
        raise ValueError("Cache Name contains invalid filename characters")
    if name.endswith((" ", ".")) or name.split(".", 1)[0].upper() in _RESERVED:
        raise ValueError("Cache Name is not Windows-compatible")
    return name


def next_cache_version(geo_root: Path, cache_name: str) -> int:
    root = geo_root / validate_cache_name(cache_name)
    versions: list[int] = []
    if root.is_dir():
        for child in root.iterdir():
            match = _VERSION.fullmatch(child.name)
            if child.is_dir() and match:
                versions.append(int(match.group("version")))
    return max(versions, default=0) + 1


def build_cache_paths(context: Houd2Context, cache_name: str, version: int) -> CachePaths:
    name = validate_cache_name(cache_name)
    if version < 1 or version > 999999:
        raise ValueError("Cache Version must be between 1 and 999999")
    cache_root = _within(context.geo_root, context.geo_root / name)
    version_name = f"v{version:03d}"
    version_root = _within(cache_root, cache_root / version_name)
    staging_root = _within(cache_root, cache_root / f"{version_name}.__writing__")
    geo_directory = _within(version_root, version_root / "geo")
    staging_geo = _within(staging_root, staging_root / "geo")
    relative = PurePosixPath(name, version_name, "geo", f"{name}.$F4.bgeo.sc").as_posix()
    return CachePaths(
        cache_root=cache_root, version_root=version_root, staging_root=staging_root,
        geo_directory=geo_directory, staging_geo_directory=staging_geo,
        manifest_path=version_root / "cache_manifest.json",
        marker_path=version_root / "cache_marker.bgeo.sc",
        file_pattern=relative,
        staging_file_pattern=str(staging_geo / f"{name}.$F4.bgeo.sc"),
    )


def _within(root: Path, candidate: Path) -> Path:
    resolved_root = root.resolve()
    resolved = candidate.resolve()
    try:
        resolved.relative_to(resolved_root)
    except ValueError as exc:
        raise ValueError(f"Cache path escapes its managed root: {candidate}") from exc
    return resolved
