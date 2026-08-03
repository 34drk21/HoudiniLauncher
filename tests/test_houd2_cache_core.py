from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from houd2_cache.context import Houd2ContextError, resolve_houd2_context
from houd2_cache.manifest import create_manifest, marker_attributes, validate_manifest
from houd2_cache.paths import build_cache_paths, next_cache_version


def _environment(monkeypatch, tmp_path: Path) -> Path:
    project = tmp_path / "日本語 Project"
    task = project / "Fire Task"
    houdini = task / "houdini"
    geo = houdini / "custom geo"
    values = {
        "HOUD2_PROJECT_ID": "project-id", "HOUD2_PROJECT_ROOT": str(project),
        "HOUD2_TASK_ID": "task-id", "HOUD2_TASK_ROOT": str(task),
        "HOUD2_HOUDINI_ROOT": str(houdini), "HOUD2_GEO_ROOT": str(geo),
        "HOUD2_USER_ID": "user-id", "HOUD2_MACHINE_ID": "machine-id",
        "HOUD2_USER": "QA Artist",
    }
    for name, value in values.items():
        monkeypatch.setenv(name, value)
    return geo


def test_context_and_paths_use_launcher_geo_root(monkeypatch, tmp_path: Path) -> None:
    geo = _environment(monkeypatch, tmp_path)
    context = resolve_houd2_context()
    assert context.geo_root == geo.resolve()
    paths = build_cache_paths(context, "explosion_main", 3)
    assert paths.version_root == geo.resolve() / "explosion_main" / "v003"
    assert paths.file_pattern == "explosion_main/v003/geo/explosion_main.$F4.bgeo.sc"


def test_context_rejects_geo_root_outside_task(monkeypatch, tmp_path: Path) -> None:
    _environment(monkeypatch, tmp_path)
    monkeypatch.setenv("HOUD2_GEO_ROOT", str(tmp_path / "outside"))
    with pytest.raises(Houd2ContextError):
        resolve_houd2_context()


def test_next_version_accepts_legacy_padding(monkeypatch, tmp_path: Path) -> None:
    geo = _environment(monkeypatch, tmp_path)
    (geo / "smoke" / "v1").mkdir(parents=True)
    (geo / "smoke" / "v003").mkdir()
    (geo / "smoke" / "v004.__writing__").mkdir()
    assert next_cache_version(geo, "smoke") == 4


def test_manifest_projection_has_no_absolute_paths_or_secrets() -> None:
    context = SimpleNamespace(
        project_id="p", task_id="t", user_id="u",
        user_display_name="Artist", machine_id="m",
    )
    data = create_manifest(
        context=context, cache_name="smoke", version=1, description="test",
        file_pattern="smoke/v001/geo/smoke.$F4.bgeo.sc",
        frame_start=1, frame_end=2, frame_step=1, fps=24,
        file_count=2, size_bytes=5_000_000_000,
    )
    validate_manifest(data)
    attrs = marker_attributes(data)
    assert attrs["houd2_creator_display_name"] == "Artist"
    assert attrs["houd2_total_size"] == "5000000000"
    assert attrs["houd2_frame_mode"] == "range"
    assert "D:/" not in str(data)


def test_current_frame_manifest_records_explicit_mode() -> None:
    context = SimpleNamespace(
        project_id="p", task_id="t", user_id="u",
        user_display_name="Artist", machine_id="m",
    )
    data = create_manifest(
        context=context, cache_name="still", version=1, description="test",
        file_pattern="still/v001/geo/still.$F4.bgeo.sc",
        frame_start=1012, frame_end=1012, frame_step=1, fps=24,
        file_count=1, size_bytes=100, current_only=True,
    )
    assert data["frame"]["mode"] == "current"
    assert marker_attributes(data)["houd2_frame_mode"] == "current"
