from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .api_client import CatalogClient
from .context import resolve_houd2_context
from .manifest import create_manifest, load_manifest, populate_marker_geometry, write_manifest, write_marker
from .paths import build_cache_paths, next_cache_version, validate_cache_name


def save_to_disk(kwargs: dict[str, Any]) -> None:
    node = kwargs["node"]
    evaluate_as = node.parm("evaluate_as")
    current_only = bool(evaluate_as and int(evaluate_as.eval()) == 1)
    _save(node, current_only=current_only)


def save_current_frame(kwargs: dict[str, Any]) -> None:
    _save(kwargs["node"], current_only=True)


def update_preview(kwargs: dict[str, Any]) -> None:
    node = kwargs["node"]
    try:
        context = resolve_houd2_context(node)
        name = validate_cache_name(node.evalParm("cache_name"))
        mode = node.evalParm("version_mode")
        version = next_cache_version(context.geo_root, name) if int(mode) == 0 else int(node.evalParm("manual_version"))
        paths = build_cache_paths(context, name, version)
        _set(node, "resolved_geo_root", str(context.geo_root))
        _set(node, "resolved_cache_path", str(paths.version_root))
        _set(node, "status", "Ready to cache")
    except Exception as exc:
        _set(node, "status", str(exc))


def open_cache_folder(kwargs: dict[str, Any]) -> None:
    node = kwargs["node"]
    update_preview(kwargs)
    path = Path(node.evalParm("resolved_cache_path"))
    target = path if path.exists() else path.parent
    if not target.exists():
        raise RuntimeError(f"Cache folder does not exist: {target}")
    _open_folder(target)


def cook_marker(python_sop: Any) -> None:
    node = python_sop.parent()
    geometry = python_sop.geometry()
    manifest_value = str(node.evalParm("manifest_path") or "")
    if not manifest_value:
        geometry.clear()
        python_sop.addWarning("Save a cache to create its HouD2 Marker")
        return
    try:
        populate_marker_geometry(geometry, load_manifest(Path(manifest_value)))
    except Exception as exc:
        geometry.clear()
        python_sop.addWarning(f"Cannot load HouD2 Cache Marker: {exc}")


def _save(node: Any, current_only: bool) -> None:
    import hou

    context = resolve_houd2_context(node)
    name = validate_cache_name(str(node.evalParm("cache_name")))
    mode = int(node.evalParm("version_mode"))
    version = next_cache_version(context.geo_root, name) if mode == 0 else int(node.evalParm("manual_version"))
    paths = build_cache_paths(context, name, version)
    if paths.version_root.exists():
        raise RuntimeError(f"Cache Version already exists: {paths.version_root}")
    if paths.staging_root.exists():
        raise RuntimeError(f"Incomplete cache staging folder already exists: {paths.staging_root}")
    frame_start = int(round(hou.frame())) if current_only else int(node.evalParm("frame_start"))
    frame_end = frame_start if current_only else int(node.evalParm("frame_end"))
    frame_step = 1 if current_only else int(node.evalParm("frame_increment"))
    if frame_end < frame_start or frame_step < 1:
        raise ValueError("Frame range or increment is invalid")
    _set(node, "status", f"Writing v{version:03d}...")
    try:
        paths.staging_geo_directory.mkdir(parents=True)
        file_cache = node.node("filecache")
        if file_cache is None:
            raise RuntimeError("Internal File Cache node is missing")
        _configure_file_cache(
            node, paths.staging_file_pattern,
            frame_start, frame_end, frame_step, current_only,
        )
        file_cache.parm("execute").pressButton()
        errors = tuple(file_cache.errors())
        if errors:
            raise RuntimeError("; ".join(errors))
        files = sorted(
            item for item in paths.staging_geo_directory.iterdir()
            if item.is_file() and item.name.casefold().endswith(".bgeo.sc")
        )
        expected = 1 + ((frame_end - frame_start) // frame_step)
        if len(files) != expected:
            raise RuntimeError(f"Expected {expected} cache files, found {len(files)}")
        size = sum(item.stat().st_size for item in files)
        if size <= 0:
            raise RuntimeError("Cache files were written with zero total size")
        manifest = create_manifest(
            context=context, cache_name=name, version=version,
            description=str(node.evalParm("description") or ""),
            file_pattern=paths.file_pattern,
            frame_start=frame_start, frame_end=frame_end, frame_step=frame_step,
            fps=float(hou.fps()), file_count=len(files), size_bytes=size,
            current_only=current_only,
        )
        staging_manifest = paths.staging_root / "cache_manifest.json"
        staging_marker = paths.staging_root / "cache_marker.bgeo.sc"
        write_manifest(staging_manifest, manifest)
        write_marker(staging_marker, manifest)
        os.replace(paths.staging_root, paths.version_root)
        _set(node, "resolved_geo_root", str(context.geo_root))
        _set(node, "resolved_cache_path", str(paths.version_root))
        _set(node, "manifest_path", str(paths.manifest_path))
        _set(node, "cache_id", str(manifest["cache_id"]))
        _set(node, "resolved_version", version)
        _set(node, "status", f"Complete: {name} v{version:03d} ({len(files)} files)")
        node.cook(force=True)
        _refresh_catalog(context)
    except Exception as exc:
        if paths.staging_root.exists():
            shutil.rmtree(paths.staging_root, ignore_errors=True)
        _set(node, "status", f"ERROR: {exc}")
        raise


def _configure_file_cache(
    node: Any, pattern: str, start: int, end: int, step: int, current_only: bool
) -> None:
    _set(node, "internal_file_pattern", pattern.replace("\\", "/"))
    _set(node, "internal_start", start)
    _set(node, "internal_end", end)
    _set(node, "internal_step", step)
    _set(node, "internal_current_only", int(current_only))


def _refresh_catalog(context: Any) -> None:
    if not context.api_url or not context.api_token:
        return
    try:
        CatalogClient(context.api_url, context.api_token).refresh()
    except Exception:
        pass


def _set(node: Any, name: str, value: object) -> None:
    parm = node.parm(name)
    if parm is not None:
        parm.set(value)


def _open_folder(path: Path) -> None:
    if sys.platform.startswith("win"):
        os.startfile(str(path))  # type: ignore[attr-defined]
    elif sys.platform == "darwin":
        subprocess.Popen(["open", str(path)])
    else:
        subprocess.Popen(["xdg-open", str(path)])
