from __future__ import annotations

from pathlib import Path

from houd2launcher.core.models import LauncherSettings
from houd2launcher.houdini.installation_detector import HoudiniInstallationDetector
from houd2launcher.houdini.installation_manager import HoudiniInstallationManager


def _fake_install(root: Path, version: str, valid: bool = True) -> Path:
    install = root / f"Houdini {version}"
    (install / "bin").mkdir(parents=True)
    if valid:
        for executable in ("houdini.exe", "hython.exe", "hbatch.exe"):
            (install / "bin" / executable).write_bytes(b"")
    return install


def test_detects_multiple_versions_and_sorts_newest_first(tmp_path: Path) -> None:
    _fake_install(tmp_path, "20.5.613")
    _fake_install(tmp_path, "21.0.487")
    _fake_install(tmp_path, "19.5.999", valid=False)
    found = HoudiniInstallationDetector().scan([tmp_path])
    assert [item.version_string for item in found] == ["21.0.487", "20.5.613"]
    assert all(item.houdini_executable.name == "houdini.exe" for item in found)


def test_manual_registration_and_duplicate_prevention(tmp_path: Path) -> None:
    install_root = _fake_install(tmp_path, "21.0.487")
    installation = HoudiniInstallationDetector().from_install_root(
        install_root, source="manual"
    )
    assert installation is not None
    settings = LauncherSettings()
    HoudiniInstallationManager.register(settings, installation)
    try:
        HoudiniInstallationManager.register(settings, installation.model_copy(deep=True))
    except Exception:
        pass
    else:
        raise AssertionError("Duplicate executable should be rejected")
    assert len(settings.installations) == 1

