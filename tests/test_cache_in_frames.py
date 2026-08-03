from __future__ import annotations

from pathlib import Path

from houd2_cache.cache_in import _expand_frame, _frame_for_record


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
