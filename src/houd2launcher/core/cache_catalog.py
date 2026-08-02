from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from .models import ProjectSettings, TaskSettings
from .path_resolver import PathResolver
from .project_manager import ProjectManager
from .task_manager import TaskManager


_CACHE_SUFFIXES = (
    ".bgeo.sc", ".geo.sc", ".bgeo", ".geo", ".vdb", ".abc",
    ".sim", ".usda", ".usdc", ".usdz", ".usd",
)
_VERSION = re.compile(r"^v(?P<version>\d{1,6})$", re.IGNORECASE)
_FRAME_FILE = re.compile(
    r"^(?P<prefix>.*?)(?P<frame>-?\d+)(?P<suffix>\.(?:bgeo\.sc|geo\.sc|bgeo|geo|vdb|abc|sim|usda|usdc|usdz|usd))$",
    re.IGNORECASE,
)


class CacheCatalogService:
    """Expose registered Projects, Tasks, and loadable cache Versions."""

    def __init__(
        self,
        projects: ProjectManager,
        tasks: TaskManager,
        resolver: PathResolver,
    ) -> None:
        self.projects = projects
        self.tasks = tasks
        self.resolver = resolver
        self._cache: dict[tuple[str, str], tuple[float, list[dict[str, object]]]] = {}
        self._lock = threading.RLock()

    def list_projects(self) -> list[dict[str, object]]:
        return [
            {
                "project_id": item.project_id,
                "name": item.name,
                "project_root": str(item.project_root),
            }
            for item in self.projects.registered()
        ]

    def list_tasks(self, project_id: str) -> list[dict[str, object]]:
        project = self._project(project_id)
        return [
            {
                "task_id": item.task_id,
                "project_id": item.project_id,
                "name": item.name,
                "status": item.status,
            }
            for item in self.tasks.discover(project)
        ]

    def list_caches(self, project_id: str, task_id: str) -> list[dict[str, object]]:
        key = (project_id, task_id)
        with self._lock:
            cached = self._cache.get(key)
            if cached and time.monotonic() - cached[0] < 2.0:
                return [dict(item) for item in cached[1]]
        project = self._project(project_id)
        task = self._task(project, task_id)
        records = self._scan(project, task)
        with self._lock:
            self._cache[key] = (time.monotonic(), records)
        return [dict(item) for item in records]

    def versions(
        self, project_id: str, task_id: str, cache_name: str
    ) -> list[dict[str, object]]:
        return [
            item for item in self.list_caches(project_id, task_id)
            if str(item["cache_name"]).casefold() == cache_name.casefold()
        ]

    def find_cache(self, cache_id: str) -> dict[str, object]:
        for project in self.list_projects():
            for task in self.list_tasks(str(project["project_id"])):
                for cache in self.list_caches(
                    str(project["project_id"]), str(task["task_id"])
                ):
                    if cache["cache_id"] == cache_id:
                        return cache
        raise KeyError(f"Unknown cache ID: {cache_id}")

    def refresh(self) -> None:
        with self._lock:
            self._cache.clear()

    def _project(self, project_id: str) -> ProjectSettings:
        match = next(
            (item for item in self.projects.registered() if item.project_id == project_id),
            None,
        )
        if match is None:
            raise KeyError(f"Unknown Project ID: {project_id}")
        return match

    def _task(self, project: ProjectSettings, task_id: str) -> TaskSettings:
        match = next(
            (item for item in self.tasks.discover(project) if item.task_id == task_id),
            None,
        )
        if match is None:
            raise KeyError(f"Unknown Task ID: {task_id}")
        return match

    def _scan(
        self, project: ProjectSettings, task: TaskSettings
    ) -> list[dict[str, object]]:
        geo_root = self.resolver.resolve_role(project, task, "geo_cache")
        if not geo_root.is_dir():
            return []
        results: list[dict[str, object]] = []
        for cache_root in sorted(geo_root.iterdir(), key=lambda item: item.name.casefold()):
            if not cache_root.is_dir() or cache_root.name.startswith("."):
                continue
            for version_root in sorted(cache_root.iterdir(), key=lambda item: item.name.casefold()):
                match = _VERSION.fullmatch(version_root.name)
                if not match or not version_root.is_dir() or version_root.name.endswith(".__writing__"):
                    continue
                version = int(match.group("version"))
                manifest_path = version_root / "cache_manifest.json"
                try:
                    record = self._from_manifest(
                        project, task, geo_root, cache_root.name, version,
                        version_root, manifest_path,
                    ) if manifest_path.is_file() else self._legacy(
                        project, task, geo_root, cache_root.name, version, version_root
                    )
                except (OSError, ValueError, json.JSONDecodeError):
                    record = self._invalid(
                        project, task, geo_root, cache_root.name, version, version_root
                    )
                results.append(record)
        return sorted(
            results,
            key=lambda item: (str(item["cache_name"]).casefold(), int(item["version"])),
        )

    def _from_manifest(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        geo_root: Path,
        cache_name: str,
        version: int,
        version_root: Path,
        manifest_path: Path,
    ) -> dict[str, object]:
        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        if data.get("schema") != "houd2.cache" or int(data.get("schema_version", 0)) != 1:
            raise ValueError("Unsupported cache Manifest")
        if data.get("project_id") != project.project_id or data.get("task_id") != task.task_id:
            raise ValueError("Cache Manifest context mismatch")
        if data.get("name") != cache_name or int(data.get("version", -1)) != version:
            raise ValueError("Cache Manifest path mismatch")
        if data.get("path_base") != "geo_root":
            raise ValueError("Unsupported cache path base")
        pattern = _safe_relative(str(data.get("file_pattern", "")))
        resolved = (geo_root / Path(*PurePosixPath(pattern).parts)).resolve()
        _ensure_within(geo_root, resolved)
        frame = data.get("frame") if isinstance(data.get("frame"), dict) else {}
        creator = data.get("creator") if isinstance(data.get("creator"), dict) else {}
        storage = data.get("storage") if isinstance(data.get("storage"), dict) else {}
        status = str(data.get("status", "invalid"))
        return {
            "cache_id": str(data.get("cache_id", "")),
            "project_id": project.project_id,
            "project_name": project.name,
            "task_id": task.task_id,
            "task_name": task.name,
            "cache_name": cache_name,
            "version": version,
            "cache_type": str(data.get("cache_type", "geo_sequence")),
            "geo_root": str(geo_root),
            "file_pattern": pattern,
            "manifest_path": str(manifest_path),
            "description": str(data.get("description", "")),
            "created_at": str(data.get("created_at", "")),
            "creator_user_id": str(creator.get("user_id", "")),
            "creator_display_name": str(creator.get("display_name", "Unknown")),
            "creator_machine_id": str(creator.get("machine_id", "")),
            "frame_start": int(frame.get("start", 0)),
            "frame_end": int(frame.get("end", 0)),
            "frame_step": int(frame.get("step", 1)),
            "fps": float(frame.get("fps", 0.0)),
            "file_count": int(storage.get("file_count", 0)),
            "size_bytes": int(storage.get("size_bytes", 0)),
            "status": status,
            "loadable": status == "complete",
            "legacy": False,
            "version_root": str(version_root),
        }

    def _legacy(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        geo_root: Path,
        cache_name: str,
        version: int,
        version_root: Path,
    ) -> dict[str, object]:
        files = [
            item for item in version_root.rglob("*")
            if item.is_file() and _is_cache_file(item) and item.name != "cache_marker.bgeo.sc"
        ]
        files.sort(key=lambda item: str(item).casefold())
        if not files:
            return self._invalid(project, task, geo_root, cache_name, version, version_root)
        pattern, ambiguous = _infer_pattern(geo_root, files)
        relative_key = f"{project.project_id}/{task.task_id}/{cache_name}/{version}/{pattern}"
        return {
            "cache_id": str(uuid5(NAMESPACE_URL, "houd2-legacy:" + relative_key)),
            "project_id": project.project_id,
            "project_name": project.name,
            "task_id": task.task_id,
            "task_name": task.name,
            "cache_name": cache_name,
            "version": version,
            "cache_type": "legacy_geo_sequence",
            "geo_root": str(geo_root),
            "file_pattern": pattern,
            "manifest_path": "",
            "description": "Legacy cache without HouD2 Manifest",
            "created_at": "",
            "creator_user_id": "",
            "creator_display_name": "Unknown",
            "creator_machine_id": "",
            "frame_start": 0,
            "frame_end": 0,
            "frame_step": 1,
            "fps": 0.0,
            "file_count": len(files),
            "size_bytes": sum(item.stat().st_size for item in files),
            "status": "ambiguous" if ambiguous else "complete",
            "loadable": not ambiguous,
            "legacy": True,
            "version_root": str(version_root),
        }

    @staticmethod
    def _invalid(
        project: ProjectSettings,
        task: TaskSettings,
        geo_root: Path,
        cache_name: str,
        version: int,
        version_root: Path,
    ) -> dict[str, object]:
        key = f"{project.project_id}/{task.task_id}/{cache_name}/{version}/invalid"
        return {
            "cache_id": str(uuid5(NAMESPACE_URL, key)),
            "project_id": project.project_id, "project_name": project.name,
            "task_id": task.task_id, "task_name": task.name,
            "cache_name": cache_name, "version": version,
            "cache_type": "unknown", "geo_root": str(geo_root),
            "file_pattern": "", "manifest_path": "", "description": "",
            "created_at": "", "creator_user_id": "",
            "creator_display_name": "Unknown", "creator_machine_id": "",
            "frame_start": 0, "frame_end": 0, "frame_step": 1, "fps": 0.0,
            "file_count": 0, "size_bytes": 0, "status": "invalid",
            "loadable": False, "legacy": True, "version_root": str(version_root),
        }


def _safe_relative(value: str) -> str:
    normalized = value.strip().replace("\\", "/")
    path = PurePosixPath(normalized)
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Cache file pattern must be a safe relative path")
    return path.as_posix()


def _ensure_within(root: Path, candidate: Path) -> None:
    try:
        candidate.resolve().relative_to(root.resolve())
    except ValueError as exc:
        raise ValueError("Cache path escapes its Geo Root") from exc


def _is_cache_file(path: Path) -> bool:
    return any(path.name.casefold().endswith(suffix) for suffix in _CACHE_SUFFIXES)


def _infer_pattern(geo_root: Path, files: list[Path]) -> tuple[str, bool]:
    matches = [_FRAME_FILE.match(item.name) for item in files]
    if all(matches):
        signatures = {
            (match.group("prefix"), match.group("suffix").casefold(), len(match.group("frame").lstrip("-")))
            for match in matches if match is not None
        }
        parents = {item.parent.resolve() for item in files}
        if len(signatures) == 1 and len(parents) == 1:
            prefix, suffix, padding = next(iter(signatures))
            relative_parent = next(iter(parents)).relative_to(geo_root.resolve())
            pattern = relative_parent / f"{prefix}$F{padding}{suffix}"
            return PurePosixPath(*pattern.parts).as_posix(), False
    if len(files) == 1:
        return PurePosixPath(*files[0].relative_to(geo_root).parts).as_posix(), False
    return "", True
