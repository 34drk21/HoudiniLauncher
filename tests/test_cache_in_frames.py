from __future__ import annotations

from pathlib import Path

from houd2_cache import cache_in
from houd2_cache.cache_in import (
    _cache_color_state,
    _ensure_cache_selection,
    _expand_frame,
    _frame_for_record,
)


class _Parm:
    def __init__(self, value=""):
        self.value = value

    def evalAsString(self):
        return str(self.value)

    def deleteAllKeyframes(self):
        return None

    def set(self, value):
        self.value = value


class _Node:
    def __init__(self):
        self.parms = {
            "cache_name": _Parm(""),
            "specific_version": _Parm(""),
        }
        self.data = {}

    def parm(self, name):
        return self.parms.get(name)

    def userData(self, name):
        return self.data.get(name)

    def setUserData(self, name, value):
        self.data[name] = value

    def destroyUserData(self, name):
        self.data.pop(name, None)


def test_current_frame_cache_uses_its_saved_frame() -> None:
    record = {
        "frame_mode": "current",
        "frame_start": 1001,
        "frame_end": 1001,
        "file_count": 1,
    }
    assert _frame_for_record(record, 1050) == 1001
    assert _expand_frame(Path("smoke.$F4.bgeo.sc"), record).name == (
        "smoke.1001.bgeo.sc"
    )


def test_range_cache_continues_to_follow_timeline_frame() -> None:
    record = {
        "frame_mode": "range",
        "frame_start": 1001,
        "frame_end": 1100,
        "file_count": 100,
    }
    assert _frame_for_record(record, 1050) == 1050


def test_old_single_frame_manifest_is_treated_as_current_frame_cache() -> None:
    record = {"frame_start": 42, "frame_end": 42, "file_count": 1}
    assert _frame_for_record(record, 1001) == 42


def test_empty_dynamic_menu_token_commits_first_cache(monkeypatch) -> None:
    node = _Node()
    monkeypatch.setattr(
        cache_in,
        "_records",
        lambda _node: [
            {"cache_name": "smoke", "version": 1},
            {"cache_name": "smoke", "version": 2},
        ],
    )

    _ensure_cache_selection(node)

    assert node.parm("cache_name").value == "smoke"
    assert node.parm("specific_version").value == "2"


def test_cache_in_color_reflects_latest_version_and_missing_file() -> None:
    records = [
        {"version": 1},
        {"version": 2},
    ]
    assert _cache_color_state(records[1], records, True) == "green"
    assert _cache_color_state(records[0], records, True) == "yellow"
    assert _cache_color_state(records[1], records, False) == "red"
