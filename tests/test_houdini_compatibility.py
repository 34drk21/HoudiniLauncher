from __future__ import annotations

from pathlib import Path

from houd2launcher.core.models import HoudiniInstallation
from houd2launcher.houdini.compatibility import assess_compatibility


def _installation(tmp_path: Path, version: tuple[int, int, int]) -> HoudiniInstallation:
    major, minor, build = version
    executable = tmp_path / f"houdini-{major}-{minor}-{build}.exe"
    executable.write_bytes(b"")
    return HoudiniInstallation(
        display_name=f"Houdini {major}.{minor}.{build}",
        major=major,
        minor=minor,
        build=build,
        version_string=f"{major}.{minor}.{build}",
        install_root=tmp_path,
        houdini_executable=executable,
    )


def test_compatibility_levels(tmp_path: Path) -> None:
    saved = _installation(tmp_path, (21, 0, 487))
    assert assess_compatibility(saved, _installation(tmp_path, (21, 0, 600))).severity == "information"
    assert assess_compatibility(saved, _installation(tmp_path, (21, 5, 100))).severity == "warning"
    assert assess_compatibility(saved, _installation(tmp_path, (20, 5, 613))).severity == "high_risk"
    assert assess_compatibility(None, saved).severity == "unknown"

