from __future__ import annotations

import json
from pathlib import Path

import pytest

from houd2launcher.core.cache_exchange import CacheExchangeService
from houd2launcher.core.cache_manager import CacheManager
from houd2launcher.core.models import ProjectSettings, TaskSettings
from houd2launcher.core.path_resolver import PathResolver


def _cache(tmp_path: Path):
    resolver = PathResolver()
    project = ProjectSettings(name="Demo", project_root=tmp_path / "Demo")
    task = TaskSettings(project_id=project.project_id, name="fire")
    version = resolver.resolve_role(project, task, "geo_cache") / "smoke" / "v001"
    geo = version / "geo"
    geo.mkdir(parents=True)
    (geo / "smoke.1001.bgeo.sc").write_bytes(b"cache")
    manifest = {
        "schema": "houd2.cache", "schema_version": 1, "cache_id": "cache-123",
        "project_id": project.project_id, "task_id": task.task_id,
        "name": "smoke", "version": 1, "cache_type": "geo_sequence",
        "path_base": "geo_root", "file_pattern": "smoke/v001/geo/smoke.$F4.bgeo.sc",
        "frame": {"start": 1001, "end": 1001, "step": 1, "fps": 60, "mode": "current"},
        "creator": {"user_id": "user", "machine_id": "machine", "display_name": "Artist"},
        "storage": {"file_count": 1, "size_bytes": 5}, "status": "complete",
    }
    (version / "cache_manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    record = CacheManager(resolver).discover(project, task, [])[0]
    return resolver, project, task, version, record


def test_publish_discover_and_import_round_trip(tmp_path: Path) -> None:
    resolver, project, task, version, record = _cache(tmp_path)
    service = CacheExchangeService(resolver)
    published = service.publish(tmp_path / "exchange", project, task, [record])[0]
    assert published.manifest.cache_id == "cache-123"
    assert service.discover(tmp_path / "exchange") == (published,)
    import shutil
    shutil.rmtree(version)
    progress: list[tuple[int, str]] = []
    result = service.import_cache(
        published,
        project,
        task,
        delete_source=True,
        progress=lambda percent, phase: progress.append((percent, phase)),
    )
    assert (result.path / "geo" / "smoke.1001.bgeo.sc").read_bytes() == b"cache"
    assert result.source_deleted
    assert not published.manifest_path.parent.exists()
    assert progress[0] == (0, "Validating Published Cache")
    assert progress[-1] == (100, "Cache Import Complete")
    assert [percent for percent, _phase in progress] == sorted(
        percent for percent, _phase in progress
    )
    assert {phase for _percent, phase in progress} >= {
        "Validating Published Cache",
        "Copying to Local",
        "Verifying Local Cache",
    }


def test_import_rejects_context_mismatch_and_corruption(tmp_path: Path) -> None:
    resolver, project, task, _version, record = _cache(tmp_path)
    service = CacheExchangeService(resolver)
    published = service.publish(tmp_path / "exchange", project, task, [record])[0]
    other = TaskSettings(project_id=project.project_id, name="other")
    with pytest.raises(ValueError, match="different Project or Task"):
        service.import_cache(published, project, other)
    (published.payload_root / "geo" / "smoke.1001.bgeo.sc").write_bytes(b"bad")
    assert service.discover(tmp_path / "exchange") == ()
