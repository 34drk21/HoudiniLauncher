from __future__ import annotations

import os
import re
import subprocess
import sys
from pathlib import Path, PurePosixPath
from typing import Any

from .api_client import CatalogClient, CatalogUnavailable
from .context import resolve_houd2_context
from .manifest import load_manifest


def project_menu(kwargs: dict[str, Any]) -> list[str]:
    node = kwargs["node"]
    try:
        items = _client(node).projects()
        return _menu(items, "project_id", "name")
    except Exception:
        current = os.getenv("HOUD2_PROJECT_ID", "")
        return [current, "Current Project"] if current else []


def task_menu(kwargs: dict[str, Any]) -> list[str]:
    node = kwargs["node"]
    project_id = _value(node, "project_id") or os.getenv("HOUD2_PROJECT_ID", "")
    try:
        return _menu(_client(node).tasks(project_id), "task_id", "name")
    except Exception:
        current = os.getenv("HOUD2_TASK_ID", "")
        return [current, "Current Task"] if current else []


def cache_menu(kwargs: dict[str, Any]) -> list[str]:
    node = kwargs["node"]
    try:
        records = _records(node)
        names = sorted({str(item["cache_name"]) for item in records}, key=str.casefold)
        result: list[str] = []
        for name in names:
            result.extend((name, name))
        return result
    except Exception:
        return []


def version_menu(kwargs: dict[str, Any]) -> list[str]:
    node = kwargs["node"]
    try:
        records = _versions(node)
        result: list[str] = []
        for item in sorted(records, key=lambda value: int(value["version"]), reverse=True):
            token = str(item["version"])
            label = f"v{int(item['version']):03d} - {str(item['status']).upper()}"
            result.extend((token, label))
        return result
    except Exception:
        return []


def selection_changed(kwargs: dict[str, Any]) -> None:
    update_info(kwargs["node"])


def refresh_catalog(kwargs: dict[str, Any]) -> None:
    node = kwargs["node"]
    try:
        _client(node).refresh()
        _set(node, "local_status", "Catalog refreshed")
        update_info(node)
    except Exception as exc:
        _set(node, "local_status", str(exc))


def reload_cache(kwargs: dict[str, Any]) -> None:
    node = kwargs["node"]
    file_node = node.node("load_cache")
    if file_node is not None and file_node.parm("reload") is not None:
        file_node.parm("reload").pressButton()
    node.cook(force=True)
    update_info(node)


def sync_to_local(kwargs: dict[str, Any]) -> None:
    node = kwargs["node"]
    try:
        record = resolve_record(node)
        _client(node).sync(str(record["cache_id"]))
    except Exception as exc:
        _set(node, "local_status", f"Sync unavailable: {exc}")


def open_cache_folder(kwargs: dict[str, Any]) -> None:
    record = resolve_record(kwargs["node"])
    path = _resolved_pattern(record).parent
    if not path.exists():
        raise RuntimeError(f"Cache folder does not exist: {path}")
    _open_folder(path)


def resolved_file(node: Any) -> str:
    try:
        record = resolve_record(node)
        path = _resolved_pattern(record)
        _set(node, "resolved_geo_root", str(record["geo_root"]))
        _set(node, "resolved_file_pattern", str(path).replace("\\", "/"))
        return str(_expand_frame(path)).replace("\\", "/")
    except Exception as exc:
        _set(node, "local_status", f"INVALID: {exc}")
        return ""


def update_info(node: Any) -> None:
    try:
        record = resolve_record(node)
        pattern = _resolved_pattern(record)
        current = _expand_frame(pattern)
        status = "READY" if current.is_file() else "MISSING"
        _set(node, "resolved_cache_id", str(record["cache_id"]))
        _set(node, "resolved_geo_root", str(record["geo_root"]))
        _set(node, "resolved_file_pattern", str(pattern).replace("\\", "/"))
        _set(node, "local_status", status)
        _set(node, "info_creator", str(record.get("creator_display_name") or "Unknown"))
        _set(node, "info_user_id", str(record.get("creator_user_id") or "Unknown"))
        _set(node, "info_machine_id", str(record.get("creator_machine_id") or "Unknown"))
        _set(node, "info_created_at", str(record.get("created_at") or "Unknown"))
        _set(node, "info_description", str(record.get("description") or ""))
        _set(node, "info_type", str(record.get("cache_type") or "Unknown"))
        _set(
            node, "info_frames",
            f"{record.get('frame_start', 0)}-{record.get('frame_end', 0)} step {record.get('frame_step', 1)} @ {record.get('fps', 0)} fps",
        )
        _set(node, "info_storage", f"{record.get('file_count', 0)} files / {_format_size(int(record.get('size_bytes', 0)))}")
        _set(node, "info_source", f"{record.get('project_name', '')} / {record.get('task_name', '')}")
    except Exception as exc:
        _set(node, "local_status", f"INVALID: {exc}")


def resolve_record(node: Any) -> dict[str, Any]:
    records = _versions(node)
    loadable = [item for item in records if bool(item.get("loadable"))]
    if not loadable:
        raise RuntimeError("No loadable Cache Version is available")
    if int(node.evalParm("version_mode")) == 0:
        return max(loadable, key=lambda item: int(item["version"]))
    selected = int(_value(node, "specific_version") or 0)
    match = next((item for item in records if int(item["version"]) == selected), None)
    if match is None:
        raise RuntimeError(f"Cache Version v{selected:03d} was not found")
    if not bool(match.get("loadable")):
        raise RuntimeError(f"Cache Version v{selected:03d} is {match.get('status', 'invalid')}")
    return match


def _records(node: Any) -> list[dict[str, Any]]:
    project_id = _value(node, "project_id") or os.getenv("HOUD2_PROJECT_ID", "")
    task_id = _value(node, "task_id") or os.getenv("HOUD2_TASK_ID", "")
    if not project_id or not task_id:
        raise RuntimeError("Select a Project and Task")
    try:
        return _client(node).caches(project_id, task_id)
    except CatalogUnavailable:
        context = resolve_houd2_context(node)
        if project_id != context.project_id or task_id != context.task_id:
            raise CatalogUnavailable(
                "The Launcher Catalog is required to browse another Project or Task"
            )
        return _local_records(context)


def _versions(node: Any) -> list[dict[str, Any]]:
    cache_name = _value(node, "cache_name")
    if not cache_name:
        raise RuntimeError("Select a Cache")
    return [item for item in _records(node) if str(item["cache_name"]).casefold() == cache_name.casefold()]


def _client(node: Any) -> CatalogClient:
    context = resolve_houd2_context(node)
    if not context.api_url or not context.api_token:
        raise CatalogUnavailable("Launch Houdini from HouD2Launcher to browse the Cache Catalog")
    return CatalogClient(context.api_url, context.api_token)


def _local_records(context: Any) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    version_pattern = re.compile(r"^v(\d{1,6})$", re.IGNORECASE)
    if not context.geo_root.is_dir():
        return records
    for cache_root in sorted(context.geo_root.iterdir(), key=lambda item: item.name.casefold()):
        if not cache_root.is_dir():
            continue
        for version_root in sorted(cache_root.iterdir(), key=lambda item: item.name.casefold()):
            match = version_pattern.fullmatch(version_root.name)
            if not match or not version_root.is_dir():
                continue
            version = int(match.group(1))
            manifest_path = version_root / "cache_manifest.json"
            if manifest_path.is_file():
                try:
                    data = load_manifest(manifest_path)
                    frame = data["frame"]
                    creator = data["creator"]
                    storage = data["storage"]
                    records.append({
                        "cache_id": data["cache_id"], "project_id": context.project_id,
                        "project_name": context.project_id, "task_id": context.task_id,
                        "task_name": os.getenv("HOUD2_TASK_NAME", context.task_id),
                        "cache_name": data["name"], "version": data["version"],
                        "cache_type": data["cache_type"], "geo_root": str(context.geo_root),
                        "file_pattern": data["file_pattern"], "description": data.get("description", ""),
                        "created_at": data.get("created_at", ""),
                        "creator_user_id": creator.get("user_id", ""),
                        "creator_display_name": creator.get("display_name", "Unknown"),
                        "creator_machine_id": creator.get("machine_id", ""),
                        "frame_start": frame["start"], "frame_end": frame["end"],
                        "frame_step": frame["step"], "fps": frame["fps"],
                        "file_count": storage["file_count"], "size_bytes": storage["size_bytes"],
                        "status": data["status"], "loadable": data["status"] == "complete",
                        "legacy": False,
                    })
                    continue
                except Exception:
                    pass
            files = sorted(
                item for item in version_root.rglob("*.bgeo.sc")
                if item.is_file() and item.name.casefold() != "cache_marker.bgeo.sc"
            )
            pattern = _legacy_pattern(context.geo_root, files)
            records.append({
                "cache_id": f"legacy:{context.project_id}:{context.task_id}:{cache_root.name}:{version}",
                "project_id": context.project_id, "project_name": context.project_id,
                "task_id": context.task_id, "task_name": os.getenv("HOUD2_TASK_NAME", context.task_id),
                "cache_name": cache_root.name, "version": version,
                "cache_type": "legacy_geo_sequence", "geo_root": str(context.geo_root),
                "file_pattern": pattern, "description": "Legacy cache without HouD2 Manifest",
                "created_at": "", "creator_user_id": "", "creator_display_name": "Unknown",
                "creator_machine_id": "", "frame_start": 0, "frame_end": 0,
                "frame_step": 1, "fps": 0.0, "file_count": len(files),
                "size_bytes": sum(item.stat().st_size for item in files),
                "status": "complete" if pattern else "ambiguous", "loadable": bool(pattern),
                "legacy": True,
            })
    return records


def _legacy_pattern(geo_root: Path, files: list[Path]) -> str:
    if not files:
        return ""
    matcher = re.compile(r"^(.*?)(-?\d+)(\.(?:bgeo\.sc|geo\.sc|bgeo|geo))$", re.IGNORECASE)
    matches = [matcher.match(item.name) for item in files]
    parents = {item.parent.resolve() for item in files}
    signatures = {
        (match.group(1), match.group(3), len(match.group(2).lstrip("-")))
        for match in matches if match is not None
    }
    if all(matches) and len(parents) == 1 and len(signatures) == 1:
        prefix, suffix, padding = next(iter(signatures))
        parent = next(iter(parents)).relative_to(geo_root.resolve())
        return PurePosixPath(*parent.parts, f"{prefix}$F{padding}{suffix}").as_posix()
    if len(files) == 1:
        return PurePosixPath(*files[0].relative_to(geo_root).parts).as_posix()
    return ""


def _resolved_pattern(record: dict[str, Any]) -> Path:
    geo_root = Path(str(record["geo_root"])).expanduser().resolve()
    relative = str(record["file_pattern"]).replace("\\", "/")
    pure = PurePosixPath(relative)
    if not relative or pure.is_absolute() or any(part in {"", ".", ".."} for part in pure.parts):
        raise ValueError("Catalog returned an unsafe Cache pattern")
    result = geo_root.joinpath(*pure.parts)
    try:
        result.parent.resolve().relative_to(geo_root)
    except ValueError as exc:
        raise ValueError("Cache pattern escapes its Source Geo Root") from exc
    return result


def _expand_frame(pattern: Path) -> Path:
    try:
        import hou

        frame = int(round(hou.frame()))
    except Exception:
        frame = 1
    value = str(pattern)
    return Path(re.sub(r"\$F(?P<padding>\d+)", lambda match: f"{frame:0{int(match.group('padding'))}d}", value))


def _menu(items: list[dict[str, Any]], token_key: str, label_key: str) -> list[str]:
    result: list[str] = []
    for item in items:
        result.extend((str(item[token_key]), str(item[label_key])))
    return result


def _value(node: Any, name: str) -> str:
    parm = node.parm(name)
    return str(parm.evalAsString()).strip() if parm is not None else ""


def _set(node: Any, name: str, value: object) -> None:
    parm = node.parm(name)
    if parm is not None:
        try:
            parm.deleteAllKeyframes()
            parm.set(value)
        except Exception:
            pass


def _format_size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _open_folder(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
