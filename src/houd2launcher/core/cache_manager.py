from __future__ import annotations

import re
import shutil
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path

from .exceptions import PathSafetyError
from .models import ProjectSettings, TaskSettings
from .path_resolver import PathResolver


_CACHE_SUFFIXES = (
    ".bgeo.sc",
    ".geo.sc",
    ".bgeo",
    ".geo",
    ".vdb",
    ".abc",
    ".sim",
    ".usda",
    ".usdc",
    ".usdz",
    ".usd",
)
_DIRECTORY_VERSION = re.compile(r"^(?:v|ver|version[_-]?)(\d{1,6})$", re.IGNORECASE)
_FILE_VERSION = re.compile(r"(?i)(?:^|[_\-.])v(\d{1,6})(?=[_\-.]|$)")


@dataclass(frozen=True, slots=True)
class CacheReference:
    """One cache path actively read by a node in a HIP file."""

    node_path: str
    parameter: str
    raw_path: str
    expanded_path: Path


@dataclass(frozen=True, slots=True)
class CacheRecord:
    """One cache version found below the configured geo_cache role."""

    name: str
    version: int | None
    kind: str
    path: Path
    size: int
    file_count: int
    modified_at: datetime | None
    is_used: bool
    exists: bool
    managed: bool
    node_paths: tuple[str, ...]
    targets: tuple[Path, ...]


@dataclass(frozen=True, slots=True)
class CacheGroup:
    """All on-disk versions belonging to one cache name."""

    name: str
    path: Path
    versions: tuple[CacheRecord, ...]

    @property
    def size(self) -> int:
        return sum(item.size for item in self.versions)

    @property
    def file_count(self) -> int:
        return sum(item.file_count for item in self.versions)

    @property
    def is_used(self) -> bool:
        return any(item.is_used for item in self.versions)

    @property
    def modified_at(self) -> datetime | None:
        values = [item.modified_at for item in self.versions if item.modified_at]
        return max(values, default=None)


@dataclass(frozen=True, slots=True)
class CacheScanResult:
    """Cache inventory and non-fatal warnings produced for one selected HIP."""

    hip_path: Path
    records: tuple[CacheRecord, ...]
    warnings: tuple[str, ...] = ()

    @property
    def groups(self) -> tuple[CacheGroup, ...]:
        return group_cache_records(self.records)


class CacheManager:
    """Inventory and permanently remove caches below the geo_cache role."""

    def __init__(self, resolver: PathResolver) -> None:
        self.resolver = resolver

    def geo_cache_root(self, project: ProjectSettings, task: TaskSettings) -> Path:
        """Return the only root this manager may inventory or delete."""
        return self.resolver.resolve_role(project, task, "geo_cache")

    def discover(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        references: list[CacheReference],
    ) -> tuple[CacheRecord, ...]:
        """Scan every known cache below geo_cache and mark exact HIP references used."""
        root = self.geo_cache_root(project, task)
        if not root.is_dir():
            return ()

        buckets: dict[tuple[str, int | None], list[Path]] = {}
        bucket_paths: dict[tuple[str, int | None], Path] = {}
        bucket_names: dict[tuple[str, int | None], str] = {}
        bucket_kinds: dict[tuple[str, int | None], set[str]] = {}
        for file_path in root.rglob("*"):
            if not file_path.is_file() or not _is_known_cache_file(file_path):
                continue
            relative = file_path.relative_to(root)
            if file_path.name.casefold() == "cache_marker.bgeo.sc":
                continue
            if any(part.casefold().endswith(".__writing__") for part in relative.parts):
                continue
            if not relative.parts:
                continue
            cache_name = relative.parts[0] if len(relative.parts) > 1 else _cache_name(file_path)
            version_index, version = _version_from_relative(relative)
            key = (cache_name.casefold(), version)
            buckets.setdefault(key, []).append(file_path)
            bucket_names.setdefault(key, cache_name)
            bucket_kinds.setdefault(key, set()).add(_cache_kind(file_path))
            if version_index is not None:
                bucket_paths[key] = root.joinpath(*relative.parts[: version_index + 1])
            else:
                bucket_paths.setdefault(key, file_path.parent if len(relative.parts) > 1 else file_path)

        records: list[CacheRecord] = []
        for key, files in buckets.items():
            _, version = key
            files.sort(key=lambda item: str(item).casefold())
            path = bucket_paths[key]
            name = bucket_names[key]
            targets = (
                (path,)
                if path.is_dir() and _DIRECTORY_VERSION.match(path.name)
                else tuple(files)
            )
            nodes = _matching_nodes(path, files, references, version)
            modified = max((item.stat().st_mtime for item in files), default=None)
            records.append(
                CacheRecord(
                    name=name,
                    version=version,
                    kind=", ".join(sorted(bucket_kinds[key])),
                    path=path,
                    size=sum(item.stat().st_size for item in files),
                    file_count=len(files),
                    modified_at=(
                        datetime.fromtimestamp(modified).astimezone() if modified else None
                    ),
                    is_used=bool(nodes),
                    exists=True,
                    managed=True,
                    node_paths=nodes,
                    targets=targets,
                )
            )
        return tuple(
            sorted(records, key=lambda item: (item.name.casefold(), item.version or -1))
        )

    def delete_permanently(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        records: list[CacheRecord],
    ) -> tuple[Path, ...]:
        """Permanently delete selected versions, strictly below geo_cache."""
        if not records:
            raise ValueError("No cache versions were selected")
        root = self.geo_cache_root(project, task).resolve()
        targets: list[Path] = []
        for record in records:
            for target in record.targets:
                resolved = target.resolve()
                if resolved == root or not _is_within(root, resolved):
                    raise PathSafetyError(f"Cache target is outside geo_cache: {target}")
                if target.is_symlink():
                    raise PathSafetyError(f"Symbolic cache targets cannot be deleted: {target}")
                if resolved.exists() and resolved not in targets:
                    targets.append(resolved)
        if not targets:
            raise FileNotFoundError("The selected cache files no longer exist")

        # Removing a version directory makes one deletion atomic from the user's view.
        compacted = [
            target
            for target in targets
            if not any(target != parent and _is_within(parent, target) for parent in targets)
        ]
        for target in sorted(compacted, key=lambda item: len(item.parts), reverse=True):
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        return tuple(compacted)


def group_cache_records(records: tuple[CacheRecord, ...] | list[CacheRecord]) -> tuple[CacheGroup, ...]:
    grouped: dict[str, list[CacheRecord]] = {}
    names: dict[str, str] = {}
    paths: dict[str, Path] = {}
    for record in records:
        key = record.name.casefold()
        grouped.setdefault(key, []).append(record)
        names.setdefault(key, record.name)
        if record.path.is_file():
            group_path = record.path.parent
        elif record.version is not None and _DIRECTORY_VERSION.match(record.path.name):
            group_path = record.path.parent
        else:
            group_path = record.path
        paths.setdefault(key, group_path)
    return tuple(
        CacheGroup(
            name=names[key],
            path=paths[key],
            versions=tuple(sorted(items, key=lambda item: (item.version or -1, item.kind))),
        )
        for key, items in sorted(grouped.items())
    )


def _version_from_relative(relative: Path) -> tuple[int | None, int | None]:
    for index, part in reversed(list(enumerate(relative.parts[:-1]))):
        match = _DIRECTORY_VERSION.match(part)
        if match:
            return index, int(match.group(1))
    match = _FILE_VERSION.search(relative.name)
    return (None, int(match.group(1))) if match else (None, None)


def _cache_name(path: Path) -> str:
    name = path.name
    for suffix in _CACHE_SUFFIXES:
        if name.casefold().endswith(suffix):
            name = name[: -len(suffix)]
            break
    name = re.sub(r"(?i)(?:[_\-.])v\d{1,6}(?=[_\-.]|$)", "", name)
    name = re.sub(r"[._-]?\d{1,8}$", "", name)
    return name.rstrip("_.-") or path.stem


def _matching_nodes(
    version_path: Path,
    files: list[Path],
    references: list[CacheReference],
    version: int | None,
) -> tuple[str, ...]:
    nodes: set[str] = set()
    normalized_files = {_normalized(item) for item in files}
    for reference in references:
        candidate = reference.expanded_path
        if not candidate.is_absolute():
            continue
        normalized = _normalized(candidate)
        version_directory = bool(
            version_path.is_dir() and _DIRECTORY_VERSION.match(version_path.name)
        )
        directory_match = version_directory and _is_within(version_path, candidate)
        # A frame expression often evaluates to a frame that has not been cached. Its
        # version directory still identifies the actively loaded cache correctly.
        same_version_parent = False
        if not version_directory and candidate.parent.resolve() == version_path.resolve():
            match = _FILE_VERSION.search(candidate.name)
            same_version_parent = bool(match and int(match.group(1)) == version)
        if normalized in normalized_files or directory_match or same_version_parent:
            nodes.add(reference.node_path)
    return tuple(sorted(nodes))


def _normalized(path: Path) -> str:
    return str(path.resolve()).replace("\\", "/").casefold()


def _is_known_cache_file(path: Path) -> bool:
    return any(path.name.casefold().endswith(suffix) for suffix in _CACHE_SUFFIXES)


def _cache_kind(path: Path) -> str:
    name = path.name.casefold()
    for suffix in _CACHE_SUFFIXES:
        if name.endswith(suffix):
            return suffix.lstrip(".").upper()
    return "CACHE"


def _is_within(root: Path, path: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
        return True
    except ValueError:
        return False
