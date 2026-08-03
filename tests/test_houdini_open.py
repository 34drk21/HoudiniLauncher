from __future__ import annotations

from pathlib import Path

from houd2launcher.core.environment import EnvironmentResolver
from houd2launcher.core.hip_manager import HipManager
from houd2launcher.core.models import (
    HoudiniInstallation,
    LauncherSettings,
    ProjectSettings,
    TaskSettings,
)
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.database.repositories import LauncherRepository
from houd2launcher.houdini.installation_manager import HoudiniInstallationManager
from houd2launcher.houdini.launcher import HoudiniLauncher
from houd2launcher.houdini.editions import (
    available_houdini_editions,
    resolve_houdini_edition,
)
from houd2launcher.houdini.open_policy import should_show_open_dialog


def _installation(tmp_path: Path, version: tuple[int, int, int]) -> HoudiniInstallation:
    major, minor, build = version
    root = tmp_path / f"Houdini {major}.{minor}.{build}"
    root.mkdir()
    executable = root / "houdini.exe"
    executable.write_bytes(b"")
    return HoudiniInstallation(
        display_name=f"Houdini {major}.{minor}.{build}",
        major=major,
        minor=minor,
        build=build,
        version_string=f"{major}.{minor}.{build}",
        install_root=root,
        houdini_executable=executable,
    )


def _add_product_executables(installation: HoudiniInstallation) -> None:
    installation.houdini_executable.with_name("houdinifx.exe").write_bytes(b"")
    installation.houdini_executable.with_name("houdinicore.exe").write_bytes(b"")


def test_fx_is_preferred_and_core_can_be_selected(tmp_path: Path) -> None:
    installation = _installation(tmp_path, (21, 0, 487))
    _add_product_executables(installation)
    editions = available_houdini_editions(installation)
    assert [item.key for item in editions] == ["fx", "core"]
    assert resolve_houdini_edition(installation).key == "fx"
    assert resolve_houdini_edition(installation, "core").executable.name == "houdinicore.exe"


def test_edition_falls_back_to_registered_executable(tmp_path: Path) -> None:
    installation = _installation(tmp_path, (21, 0, 487))
    selected = resolve_houdini_edition(installation)
    assert selected.key == "auto"
    assert selected.executable == installation.houdini_executable


def test_preference_order_and_missing_fallback(tmp_path: Path) -> None:
    settings = LauncherSettings()
    old = _installation(tmp_path, (20, 5, 613))
    new = _installation(tmp_path, (21, 0, 487))
    settings.installations = [old, new]
    assert HoudiniInstallationManager.select_preferred(
        settings, ["missing", old.installation_id]
    ) == old
    assert HoudiniInstallationManager.select_preferred(settings, ["missing"]) == new


def test_open_uses_selected_executable_and_environment(
    tmp_path: Path,
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskSettings(project_id=project.project_id, name="open_test")
    TaskManager(repository, resolver).create(project, task)
    hip_manager = HipManager(repository, resolver)
    version, path = hip_manager.next_path(project, task, "shota")
    path.write_bytes(b"hip")
    hip_manager.register_created(project, task, path, version, "shota", None)
    hip = hip_manager.list_hips(project, task)[0]
    installation = _installation(tmp_path, (21, 0, 487))
    _add_product_executables(installation)
    captured: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        captured.update(kwargs)
        return object()

    launcher = HoudiniLauncher(
        EnvironmentResolver(resolver),
        hip_manager,
        repository,
        tmp_path,
        popen=fake_popen,  # type: ignore[arg-type]
    )
    launcher.open_hip(
        project, task, hip, installation, LauncherSettings(), "shota"
    )
    command = captured["command"]
    assert command[:3] == [
        str(installation.houdini_executable.with_name("houdinifx.exe")),
        str(path),
        "waitforui",
    ]
    assert str(command[3]).endswith("apply_launch_settings.py")
    environment = captured["env"]
    assert isinstance(environment, dict)
    assert environment["HOUD2_TASK_NAME"] == task.name
    assert environment["HOUD2_HOUDINI_BUILD"] == "487"
    assert environment["TASK_NAME"] == task.name
    assert environment["SHOT_FRAME_START"] == str(task.frames.start)
    assert environment["SHOT_FRAME_END"] == str(task.frames.end)


def test_open_can_explicitly_use_core(
    tmp_path: Path,
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskSettings(project_id=project.project_id, name="core_open")
    TaskManager(repository, resolver).create(project, task)
    hip_manager = HipManager(repository, resolver)
    version, path = hip_manager.next_path(project, task, "shota")
    path.write_bytes(b"hip")
    hip_manager.register_created(project, task, path, version, "shota", None)
    hip = hip_manager.list_hips(project, task)[0]
    installation = _installation(tmp_path, (21, 0, 487))
    _add_product_executables(installation)
    captured: dict[str, object] = {}

    def fake_popen(command: list[str], **kwargs: object) -> object:
        captured["command"] = command
        return object()

    launcher = HoudiniLauncher(
        EnvironmentResolver(resolver),
        hip_manager,
        repository,
        tmp_path,
        popen=fake_popen,  # type: ignore[arg-type]
    )
    launcher.open_hip(
        project,
        task,
        hip,
        installation,
        LauncherSettings(),
        "shota",
        edition="core",
    )
    assert captured["command"][0].endswith("houdinicore.exe")  # type: ignore[index,union-attr]


def test_open_dialog_policy(
    tmp_path: Path,
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskSettings(project_id=project.project_id, name="policy")
    TaskManager(repository, resolver).create(project, task)
    manager = HipManager(repository, resolver)
    version, path = manager.next_path(project, task, "shota")
    path.write_bytes(b"hip")
    manager.register_created(project, task, path, version, "shota", None)
    hip = manager.list_hips(project, task)[0]
    installation = _installation(tmp_path, (21, 0, 487))
    settings = LauncherSettings(show_open_dialog=False, installations=[installation])
    project.houdini.fallback_policy = "same_major_minor"
    assert not should_show_open_dialog(
        settings, project, hip, [installation], installation
    )
    project.houdini.fallback_policy = "always_ask"
    assert should_show_open_dialog(
        settings, project, hip, [installation], installation
    )
