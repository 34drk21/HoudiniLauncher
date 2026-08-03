from __future__ import annotations

import hashlib
import json
import os
import shutil
from datetime import datetime, timezone
from pathlib import Path
from uuid import uuid4

from .cache_manager import CacheRecord
from .exceptions import PathSafetyError
from .models import ProjectSettings, TaskSettings
from .path_resolver import PathResolver


class SdmPackageService:
    """Create a normal-folder SDM2.0 delivery while retaining Houdini hierarchy."""

    def __init__(self, resolver: PathResolver) -> None:
        self.resolver = resolver

    def export(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        destination_parent: Path,
        folder_roles: list[str],
        cache_versions: list[CacheRecord],
    ) -> Path:
        source_houdini = self.resolver.resolve_houdini_root(project, task).resolve()
        destination_parent = destination_parent.expanduser().resolve()
        try:
            destination_parent.relative_to(self.resolver.resolve_task_root(project, task.name))
            raise PathSafetyError("SDM2.0 destination cannot be inside the source Task")
        except ValueError:
            pass
        final = destination_parent / f"{task.name}_SDM2.0"
        if final.exists():
            raise FileExistsError(f"SDM2.0 Package already exists: {final}")
        staging = destination_parent / f".{final.name}.part-{uuid4().hex}"
        destination_houdini = staging / "houdini"
        selected_roots: list[Path] = []
        for role in folder_roles:
            if role != "geo_cache":
                try:
                    selected_roots.append(self.resolver.resolve_role(project, task, role).resolve())
                except KeyError:
                    continue
        selected_versions = {record.path.resolve() for record in cache_versions}
        files: list[dict[str, object]] = []
        try:
            destination_houdini.mkdir(parents=True)
            for source in source_houdini.rglob("*"):
                if source.is_symlink():
                    raise PathSafetyError(f"SDM2.0 cannot contain links: {source}")
                include = source.is_file() and source.suffix.casefold() in {".hip", ".hiplc", ".hipnc"}
                include = include or any(_within(root, source.resolve()) for root in selected_roots)
                include = include or any(_within(root, source.resolve()) for root in selected_versions)
                if not include:
                    continue
                relative = source.relative_to(source_houdini)
                destination = destination_houdini / relative
                if source.is_dir():
                    destination.mkdir(parents=True, exist_ok=True)
                    continue
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
                files.append(_entry(destination, (Path("houdini") / relative).as_posix()))
            manifest = {
                "format": "houd2.sdm2_package", "schema_version": 1,
                "package_id": str(uuid4()), "created_at": datetime.now(timezone.utc).isoformat(),
                "project_id": project.project_id, "project_name": project.name,
                "task_id": task.task_id, "task_name": task.name,
                "folder_roles": sorted(set(folder_roles)),
                "cache_versions": [f"{item.name}/v{item.version:03d}" for item in cache_versions if item.version is not None],
                "files": sorted(files, key=lambda item: str(item["path"]).casefold()),
            }
            (staging / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
            destination_parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging, final)
        except Exception:
            shutil.rmtree(staging, ignore_errors=True)
            raise
        return final


def _within(root: Path, path: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _entry(path: Path, relative: str) -> dict[str, object]:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return {"path": relative, "size": path.stat().st_size, "sha256": digest.hexdigest()}
