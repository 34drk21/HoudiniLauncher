from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4


SCHEMA = "houd2.cache"
SCHEMA_VERSION = 1


def create_manifest(
    *, context: Any, cache_name: str, version: int, description: str,
    file_pattern: str, frame_start: int, frame_end: int, frame_step: int,
    fps: float, file_count: int, size_bytes: int,
) -> dict[str, Any]:
    return {
        "schema": SCHEMA, "schema_version": SCHEMA_VERSION,
        "cache_id": str(uuid4()), "project_id": context.project_id,
        "task_id": context.task_id, "name": cache_name,
        "description": description, "version": version,
        "cache_type": "geo_sequence", "path_base": "geo_root",
        "file_pattern": file_pattern.replace("\\", "/"),
        "frame": {
            "start": int(frame_start), "end": int(frame_end),
            "step": int(frame_step), "fps": float(fps),
        },
        "creator": {
            "user_id": context.user_id,
            "display_name": context.user_display_name or "Unknown",
            "machine_id": context.machine_id,
        },
        "storage": {"file_count": int(file_count), "size_bytes": int(size_bytes)},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "complete",
    }


def write_manifest(path: Path, manifest: dict[str, Any]) -> Path:
    validate_manifest(manifest)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        temporary.write_text(json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return path


def load_manifest(path: Path) -> dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    validate_manifest(data)
    return data


def validate_manifest(data: dict[str, Any]) -> None:
    if data.get("schema") != SCHEMA or int(data.get("schema_version", 0)) != SCHEMA_VERSION:
        raise ValueError("Unsupported HouD2 Cache Manifest")
    if data.get("path_base") != "geo_root":
        raise ValueError("Cache Manifest must use geo_root-relative paths")
    pattern = str(data.get("file_pattern", ""))
    if not pattern or Path(pattern).is_absolute() or ".." in pattern.replace("\\", "/").split("/"):
        raise ValueError("Cache Manifest contains an unsafe file pattern")
    serialized = json.dumps(data, ensure_ascii=False).casefold()
    for forbidden in ("password", "access_token", "session_token", "credential"):
        if forbidden in serialized:
            raise ValueError(f"Cache Manifest contains forbidden data: {forbidden}")


def marker_attributes(data: dict[str, Any]) -> dict[str, object]:
    validate_manifest(data)
    frame = data["frame"]
    creator = data["creator"]
    storage = data["storage"]
    return {
        "houd2_schema": data["schema"],
        "houd2_schema_version": int(data["schema_version"]),
        "houd2_cache_id": str(data["cache_id"]),
        "houd2_project_id": str(data["project_id"]),
        "houd2_task_id": str(data["task_id"]),
        "houd2_cache_name": str(data["name"]),
        "houd2_cache_version": int(data["version"]),
        "houd2_cache_type": str(data["cache_type"]),
        "houd2_creator_user_id": str(creator.get("user_id", "")),
        "houd2_creator_display_name": str(creator.get("display_name", "Unknown")),
        "houd2_creator_machine_id": str(creator.get("machine_id", "")),
        "houd2_created_at": str(data.get("created_at", "")),
        "houd2_path_base": "geo_root",
        "houd2_file_pattern": str(data["file_pattern"]),
        "houd2_frame_start": int(frame["start"]),
        "houd2_frame_end": int(frame["end"]),
        "houd2_frame_step": int(frame["step"]),
        "houd2_fps": float(frame["fps"]),
        "houd2_file_count": int(storage["file_count"]),
        "houd2_total_size": str(storage["size_bytes"]),
        "houd2_status": str(data["status"]),
    }


def populate_marker_geometry(geometry: Any, data: dict[str, Any]) -> None:
    import hou

    geometry.clear()
    geometry.createPoint()
    for name, value in marker_attributes(data).items():
        geometry.addAttrib(hou.attribType.Global, name, value)
        geometry.setGlobalAttribValue(name, value)


def write_marker(path: Path, data: dict[str, Any]) -> Path:
    import hou

    geometry = hou.Geometry()
    geometry.createPoint()
    for name, value in marker_attributes(data).items():
        geometry.addAttrib(hou.attribType.Global, name, value)
        geometry.setGlobalAttribValue(name, value)
    path.parent.mkdir(parents=True, exist_ok=True)
    geometry.saveToFile(str(path))
    return path
