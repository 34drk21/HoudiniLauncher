from __future__ import annotations

import os

import hou


def _enabled(name: str) -> bool:
    return os.getenv(name, "0").strip().casefold() in {"1", "true", "yes", "on"}


if _enabled("HOUD2_APPLY_PROJECT_FPS"):
    hou.setFps(float(os.environ["SHOT_FPS"]), modify_frame_count=False)

if _enabled("HOUD2_APPLY_TASK_FRAME_RANGE"):
    start = float(os.environ["SHOT_FRAME_START"])
    end = float(os.environ["SHOT_FRAME_END"])
    hou.playbar.setFrameRange(start, end)
    hou.playbar.setPlaybackRange(start, end)
    hou.setFrame(start)
