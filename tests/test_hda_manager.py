from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from houd2launcher.core.models import HoudiniInstallation
from houd2launcher.houdini.hda_manager import HdaBuildError, HdaManager


def _sources(root: Path) -> None:
    builder = root / "houdini" / "scripts" / "build_cache_hdas.py"
    package = root / "houdini" / "python" / "houd2_cache"
    builder.parent.mkdir(parents=True)
    package.mkdir(parents=True)
    builder.write_text("# builder v1\n", encoding="utf-8")
    (package / "__init__.py").write_text("# package\n", encoding="utf-8")
    (package / "cache_in.py").write_text("VALUE = 1\n", encoding="utf-8")


def _installation(root: Path) -> HoudiniInstallation:
    install = root / "Houdini 21.0.671"
    install.mkdir()
    houdini = install / "houdini.exe"
    hython = install / "hython.exe"
    houdini.write_bytes(b"")
    hython.write_bytes(b"")
    return HoudiniInstallation(
        display_name="Houdini 21.0.671",
        major=21,
        minor=0,
        build=671,
        version_string="21.0.671",
        install_root=install,
        houdini_executable=houdini,
        hython_executable=hython,
    )


def test_builds_versioned_hda_and_activates_paired_python(tmp_path: Path) -> None:
    launcher_root = tmp_path / "launcher"
    _sources(launcher_root)
    installation = _installation(tmp_path)
    captured: dict[str, object] = {}

    def fake_run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        captured.update(options)
        Path(command[-1]).write_bytes(b"commercial hda")
        return subprocess.CompletedProcess(command, 0, "Definitions: cache_in, cache_out", "")

    manager = HdaManager(launcher_root, tmp_path / "data", run=fake_run)
    integration = manager.build(installation)

    assert integration.library_path.is_file()
    assert "21.0.671" in integration.library_path.parts
    assert (integration.python_root / "houd2_cache" / "cache_in.py").is_file()
    assert manager.status(installation).state == "ready"
    assert manager.integration(installation) == integration
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert environment["PYTHONPATH"].endswith("python")
    assert "PYTHONHOME" not in environment


def test_failed_rebuild_keeps_previous_active_hda(tmp_path: Path) -> None:
    launcher_root = tmp_path / "launcher"
    _sources(launcher_root)
    installation = _installation(tmp_path)

    def success(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        Path(command[-1]).write_bytes(b"first hda")
        return subprocess.CompletedProcess(command, 0, "ok", "")

    manager = HdaManager(launcher_root, tmp_path / "data", run=success)
    first = manager.build(installation)
    (launcher_root / "houdini" / "scripts" / "build_cache_hdas.py").write_text(
        "# builder v2\n", encoding="utf-8"
    )

    def fail(command: list[str], **_: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(command, 1, "", "No Commercial license")

    manager._run = fail
    with pytest.raises(HdaBuildError, match="Commercial"):
        manager.build(installation)

    status = manager.status(installation)
    assert status.state == "stale"
    assert status.integration == first
    assert not manager.should_auto_build(installation)
    assert first.library_path.read_bytes() == b"first hda"
    assert not list((tmp_path / "data" / "hda").rglob("*.writing-*"))


def test_missing_hython_is_reported_without_touching_process_environment(
    tmp_path: Path,
) -> None:
    launcher_root = tmp_path / "launcher"
    _sources(launcher_root)
    installation = _installation(tmp_path)
    installation.hython_executable = tmp_path / "missing-hython.exe"
    before = dict(os.environ)

    with pytest.raises(HdaBuildError, match="hython"):
        HdaManager(launcher_root, tmp_path / "data").build(installation)

    assert dict(os.environ) == before
