from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class Houd2ContextError(RuntimeError):
    """Raised when a safe HouD2 Task context cannot be established."""


@dataclass(frozen=True)
class Houd2Context:
    project_id: str
    project_root: Path
    task_id: str
    task_root: Path
    houdini_root: Path
    geo_root: Path
    user_id: str
    machine_id: str
    api_url: str | None
    api_token: str | None = None
    user_display_name: str = ""


def resolve_houd2_context(node: Any | None = None) -> Houd2Context:
    """Resolve Launcher context without reading the Launcher SQLite database."""
    context = _from_environment() or _from_hip_file() or _from_manual_parameters(node)
    if context is None:
        raise Houd2ContextError(
            "HouD2Launcher task context was not found. Launch Houdini from "
            "HouD2Launcher or set Manual Task Root and Manual Geo Root."
        )
    return _validated(context)


def _from_environment() -> Houd2Context | None:
    required = {
        "project_id": os.getenv("HOUD2_PROJECT_ID", ""),
        "project_root": os.getenv("HOUD2_PROJECT_ROOT", ""),
        "task_id": os.getenv("HOUD2_TASK_ID", ""),
        "task_root": os.getenv("HOUD2_TASK_ROOT", ""),
        "houdini_root": os.getenv("HOUD2_HOUDINI_ROOT", ""),
        "geo_root": os.getenv("HOUD2_GEO_ROOT", ""),
    }
    if not all(required.values()):
        return None
    return Houd2Context(
        project_id=required["project_id"],
        project_root=Path(required["project_root"]),
        task_id=required["task_id"],
        task_root=Path(required["task_root"]),
        houdini_root=Path(required["houdini_root"]),
        geo_root=Path(required["geo_root"]),
        user_id=os.getenv("HOUD2_USER_ID", ""),
        machine_id=os.getenv("HOUD2_MACHINE_ID", ""),
        api_url=os.getenv("HOUD2_API_URL") or None,
        api_token=os.getenv("HOUD2_API_TOKEN") or None,
        user_display_name=os.getenv("HOUD2_USER", ""),
    )


def _from_hip_file() -> Houd2Context | None:
    try:
        import hou

        hip_path = Path(hou.hipFile.path()).expanduser()
    except Exception:
        return None
    if not hip_path.is_absolute() or hip_path.name.casefold() == "untitled.hip":
        return None
    houdini_root = hip_path.parent
    task_root = houdini_root.parent
    if houdini_root.name.casefold() != "houdini":
        return None
    task_path = task_root / ".houd2" / "task.json"
    project_root = task_root.parent
    project_path = project_root / ".houd2" / "project.json"
    if not task_path.is_file() or not project_path.is_file():
        return None
    try:
        task_data = json.loads(task_path.read_text(encoding="utf-8"))
        project_data = json.loads(project_path.read_text(encoding="utf-8"))
        if task_data.get("format") != "houd2.task_settings":
            return None
        if project_data.get("format") != "houd2.project_settings":
            return None
        if task_data.get("project_id") != project_data.get("project_id"):
            return None
        role = next(
            item for item in project_data.get("folders", [])
            if item.get("enabled", True) and item.get("role") == "geo_cache"
        )
        relative = _safe_relative(str(role["relative_path"]))
    except (KeyError, StopIteration, TypeError, ValueError, json.JSONDecodeError):
        return None
    return Houd2Context(
        project_id=str(project_data["project_id"]),
        project_root=project_root,
        task_id=str(task_data["task_id"]),
        task_root=task_root,
        houdini_root=houdini_root,
        geo_root=houdini_root.joinpath(*relative.parts),
        user_id=os.getenv("HOUD2_USER_ID", ""),
        machine_id=os.getenv("HOUD2_MACHINE_ID", ""),
        api_url=os.getenv("HOUD2_API_URL") or None,
        api_token=os.getenv("HOUD2_API_TOKEN") or None,
        user_display_name=os.getenv("HOUD2_USER", ""),
    )


def _from_manual_parameters(node: Any | None) -> Houd2Context | None:
    if node is None:
        return None
    task_root_value = _parm_string(node, "manual_task_root")
    geo_root_value = _parm_string(node, "manual_geo_root")
    if not task_root_value or not geo_root_value:
        return None
    task_root = Path(task_root_value).expanduser()
    return Houd2Context(
        project_id=_parm_string(node, "manual_project_id") or "manual-project",
        project_root=task_root.parent,
        task_id=_parm_string(node, "manual_task_id") or "manual-task",
        task_root=task_root,
        houdini_root=task_root / "houdini",
        geo_root=Path(geo_root_value).expanduser(),
        user_id=os.getenv("HOUD2_USER_ID", "manual-user"),
        machine_id=os.getenv("HOUD2_MACHINE_ID", "manual-machine"),
        api_url=os.getenv("HOUD2_API_URL") or None,
        api_token=os.getenv("HOUD2_API_TOKEN") or None,
        user_display_name=os.getenv("HOUD2_USER", "Developer"),
    )


def _validated(context: Houd2Context) -> Houd2Context:
    for label, path in {
        "Project Root": context.project_root,
        "Task Root": context.task_root,
        "Houdini Root": context.houdini_root,
        "Geo Root": context.geo_root,
    }.items():
        if not path.expanduser().is_absolute():
            raise Houd2ContextError(f"{label} must be absolute: {path}")
    project_root = context.project_root.expanduser().resolve()
    task_root = context.task_root.expanduser().resolve()
    houdini_root = context.houdini_root.expanduser().resolve()
    geo_root = context.geo_root.expanduser().resolve()
    _ensure_within(project_root, task_root, "Task Root")
    _ensure_within(task_root, houdini_root, "Houdini Root")
    _ensure_within(houdini_root, geo_root, "Geo Root")
    if geo_root == houdini_root:
        raise Houd2ContextError("Geo Root must be below the Houdini Root")
    return Houd2Context(
        project_id=context.project_id, project_root=project_root,
        task_id=context.task_id, task_root=task_root,
        houdini_root=houdini_root, geo_root=geo_root,
        user_id=context.user_id, machine_id=context.machine_id,
        api_url=context.api_url, api_token=context.api_token,
        user_display_name=context.user_display_name,
    )


def _ensure_within(root: Path, candidate: Path, label: str) -> None:
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise Houd2ContextError(f"{label} escapes its managed root: {candidate}") from exc


def _safe_relative(value: str) -> Path:
    normalized = value.strip().replace("\\", "/")
    path = Path(*normalized.split("/"))
    if not normalized or path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ValueError("Unsafe relative path")
    return path


def _parm_string(node: Any, name: str) -> str:
    try:
        parm = node.parm(name)
        return str(parm.evalAsString()).strip() if parm is not None else ""
    except Exception:
        return ""
