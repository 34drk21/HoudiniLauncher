from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from houd2_cache import cache_in as cache_in_module
from houd2_cache import cache_out


class FakeParm:
    def __init__(self, value: object = "") -> None:
        self.value = value
        self.keyframes_deleted = False

    def deleteAllKeyframes(self) -> None:
        self.keyframes_deleted = True

    def set(self, value: object) -> None:
        self.value = value


class FakeCacheIn:
    def __init__(self) -> None:
        self.parms = {
            name: FakeParm()
            for name in (
                "project_id",
                "task_id",
                "cache_name",
                "version_mode",
                "specific_version",
                "resolved_cache_id",
            )
        }
        self.name = ""
        self.position = 0.0
        self.selected = False
        self.destroyed = False

    def parm(self, name: str) -> FakeParm | None:
        return self.parms.get(name)

    def setName(self, name: str, *, unique_name: bool = False) -> None:
        assert unique_name
        self.name = name

    def setPosition(self, position: float) -> None:
        self.position = position

    def setSelected(self, selected: bool, *, clear_all_selected: bool = False) -> None:
        assert clear_all_selected
        self.selected = selected

    def path(self) -> str:
        return f"/obj/geo1/{self.name}"

    def destroy(self) -> None:
        self.destroyed = True


class FakeParent:
    def __init__(self) -> None:
        self.created: FakeCacheIn | None = None

    def createNode(self, type_name: str) -> FakeCacheIn:
        assert type_name == "houd2::cache_in::1.0"
        self.created = FakeCacheIn()
        return self.created


class FakeCacheOut:
    def __init__(self, manifest_path: Path, parent: FakeParent) -> None:
        self.manifest_path = manifest_path
        self._parent = parent

    def evalParm(self, name: str) -> str:
        assert name == "manifest_path"
        return str(self.manifest_path)

    def parent(self) -> FakeParent:
        return self._parent

    def name(self) -> str:
        return "smoke_out"

    def position(self) -> float:
        return 10.0


def _manifest() -> dict[str, object]:
    return {
        "project_id": "project-id",
        "task_id": "task-id",
        "name": "smoke",
        "version": 7,
        "cache_id": "cache-id",
        "status": "complete",
    }


def test_create_cache_in_targets_last_completed_version(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    manifest_path = tmp_path / "cache_manifest.json"
    manifest_path.write_text("{}", encoding="utf-8")
    parent = FakeParent()
    source = FakeCacheOut(manifest_path, parent)
    messages: list[str] = []
    monkeypatch.setitem(
        sys.modules,
        "hou",
        SimpleNamespace(
            Vector2=lambda x, _y: x,
            ui=SimpleNamespace(setStatusMessage=messages.append),
        ),
    )
    monkeypatch.setattr(cache_out, "load_manifest", lambda _path: _manifest())
    refreshed: list[FakeCacheIn] = []
    monkeypatch.setattr(cache_in_module, "update_info", refreshed.append)

    created = cache_out.create_cache_in({"node": source})

    assert created is parent.created
    assert created.name == "smoke_out_cache_in"
    assert created.position == 13.5
    assert created.selected
    assert refreshed == [created]
    assert messages == ["Created /obj/geo1/smoke_out_cache_in for smoke v007"]
    assert {name: parm.value for name, parm in created.parms.items()} == {
        "project_id": "project-id",
        "task_id": "task-id",
        "cache_name": "smoke",
        "version_mode": 1,
        "specific_version": "7",
        "resolved_cache_id": "cache-id",
    }
    assert all(parm.keyframes_deleted for parm in created.parms.values())


def test_create_cache_in_requires_a_saved_manifest(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(
        sys.modules,
        "hou",
        SimpleNamespace(Vector2=lambda x, _y: x),
    )
    source = FakeCacheOut(tmp_path / "missing.json", FakeParent())

    with pytest.raises(RuntimeError, match="Manifest was not found"):
        cache_out.create_cache_in({"node": source})
