from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from houd2launcher.core.environment import EnvironmentResolver
from houd2launcher.core.exceptions import HoudiniLaunchError
from houd2launcher.core.hip_manager import HipManager
from houd2launcher.core.models import HoudiniInstallation, LauncherSettings, TaskSettings
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.database.repositories import LauncherRepository
from houd2launcher.houdini.launcher import HoudiniLauncher


def _installation(tmp_path: Path) -> HoudiniInstallation:
    root = tmp_path / "Houdini 21.0.671"
    root.mkdir()
    houdini = root / "houdini.exe"
    hython = root / "hython.exe"
    houdini.write_bytes(b"")
    hython.write_bytes(b"")
    return HoudiniInstallation(
        display_name="Houdini 21.0.671",
        major=21,
        minor=0,
        build=671,
        version_string="21.0.671",
        install_root=root,
        houdini_executable=houdini,
        hython_executable=hython,
    )


@pytest.mark.parametrize(
    ("license_type", "extension"),
    [
        ("Commercial", "hip"),
        ("Indie", "hiplc"),
        ("Apprentice", "hipnc"),
        ("Unknown", "hip"),
    ],
)
def test_extension_follows_license(license_type: str, extension: str) -> None:
    assert HoudiniLauncher.extension_for_license(license_type) == extension


def test_create_blank_hip_probes_indie_and_registers_only_after_save(
    tmp_path: Path,
    project,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="create_test")
    )
    installation = _installation(tmp_path)

    run_options: list[dict[str, object]] = []

    def fake_run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        run_options.append(options)
        if len(command) == 3:
            return subprocess.CompletedProcess(command, 0, "HOUD2_LICENSE=Indie\n", "")
        Path(command[-1]).write_bytes(b"hiplc")
        return subprocess.CompletedProcess(command, 0, "", "")

    manager = HipManager(repository, resolver)
    launcher = HoudiniLauncher(
        EnvironmentResolver(resolver),
        manager,
        repository,
        tmp_path,
        run=fake_run,
    )
    result = launcher.create_blank_hip(
        project, task, installation, LauncherSettings(), "SY"
    )

    assert result.suffix == ".hiplc"
    assert installation.license_type == "Indie"
    assert manager.list_hips(project, task)[0].path == result
    if os.name == "nt":
        assert all(
            options["creationflags"] == subprocess.CREATE_NO_WINDOW
            for options in run_options
        )
    else:
        assert all("creationflags" not in options for options in run_options)


def test_license_probe_timeout_is_reported(
    tmp_path: Path,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    installation = _installation(tmp_path)

    def timeout(*_: object, **__: object) -> subprocess.CompletedProcess[str]:
        raise subprocess.TimeoutExpired("hython", 30)

    launcher = HoudiniLauncher(
        EnvironmentResolver(resolver),
        HipManager(repository, resolver),
        repository,
        tmp_path,
        run=timeout,
    )
    with pytest.raises(HoudiniLaunchError, match="timed out"):
        launcher.probe_license(installation)
