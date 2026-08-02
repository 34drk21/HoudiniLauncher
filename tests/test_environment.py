from __future__ import annotations

from pathlib import Path

import pytest

from houd2launcher.core.environment import EnvironmentResolver
from houd2launcher.core.exceptions import EnvironmentResolutionError
from houd2launcher.core.models import (
    HoudiniInstallation,
    ProjectSettings,
    SearchPathSettings,
    TaskSettings,
)
from houd2launcher.core.path_resolver import PathResolver


def _installation(tmp_path: Path) -> HoudiniInstallation:
    executable = tmp_path / "houdini.exe"
    executable.write_bytes(b"")
    return HoudiniInstallation(
        display_name="Houdini 21.0.487",
        major=21,
        minor=0,
        build=487,
        version_string="21.0.487",
        install_root=tmp_path,
        houdini_executable=executable,
    )


def test_environment_priority_templates_roles_and_search_paths(
    tmp_path: Path, project: ProjectSettings
) -> None:
    task = TaskSettings(
        project_id=project.project_id,
        name="dust",
        environment={"VALUE": "task", "CACHE": "{role:geo_cache}"},
    )
    project.environment = {"VALUE": "project", "ROOT_COPY": "{project_root}"}
    project.search_paths = SearchPathSettings(hda=["{project_root}/pipeline/hda"])
    environment = EnvironmentResolver(PathResolver()).build(
        project,
        task,
        _installation(tmp_path),
        launcher_environment={"VALUE": "launcher"},
        open_overrides={"VALUE": "open"},
        base_environment={"VALUE": "os"},
        user="shota",
        user_id="user-id",
        machine_id="machine-id",
        api_url="http://127.0.0.1:1234",
        api_token="secret-token",
        launcher_root=str(tmp_path),
    )
    assert environment["VALUE"] == "open"
    assert environment["ROOT_COPY"] == str(project.project_root)
    assert environment["CACHE"].endswith("dust\\houdini\\geo")
    assert environment["HOUD2_TASK_NAME"] == "dust"
    assert environment["TASK_NAME"] == "dust"
    assert environment["SHOT_FRAME_START"] == str(task.frames.start)
    assert environment["SHOT_FRAME_END"] == str(task.frames.end)
    assert environment["HOUD2_GEO_ROOT"].endswith("dust\\houdini\\geo")
    assert environment["HOUD2_USER_ID"] == "user-id"
    assert environment["HOUD2_MACHINE_ID"] == "machine-id"
    assert environment["HOUD2_API_URL"] == "http://127.0.0.1:1234"
    assert environment["HOUD2_API_TOKEN"] == "secret-token"
    assert str(tmp_path / "houdini" / "python") in environment["PYTHONPATH"]
    assert "&" in environment["HOUDINI_OTLSCAN_PATH"]


def test_detects_environment_cycle(tmp_path: Path, project: ProjectSettings) -> None:
    project.environment = {"A": "{B}", "B": "{A}"}
    task = TaskSettings(project_id=project.project_id, name="cycle")
    with pytest.raises(EnvironmentResolutionError):
        EnvironmentResolver(PathResolver()).build(
            project, task, _installation(tmp_path), base_environment={}
        )


def test_rejects_reserved_override(tmp_path: Path, project: ProjectSettings) -> None:
    task = TaskSettings(project_id=project.project_id, name="reserved")
    with pytest.raises(EnvironmentResolutionError):
        EnvironmentResolver(PathResolver()).build(
            project,
            task,
            _installation(tmp_path),
            open_overrides={"HOUD2_TASK_NAME": "bad"},
            base_environment={},
        )


def test_expression_environment_lists_only_launcher_managed_values(
    tmp_path: Path, project: ProjectSettings
) -> None:
    task = TaskSettings(
        project_id=project.project_id,
        name="fire",
        frames={"start": 1001, "end": 1050, "fps": 25, "sim_start": 990},
    )
    environment = EnvironmentResolver(PathResolver()).expression_environment(
        project,
        task,
        _installation(tmp_path),
        launcher_environment={"SHOW": "fire"},
        user="QA",
    )
    assert environment["TASK_NAME"] == "fire"
    assert environment["SHOT_FRAME_START"] == "1001"
    assert environment["SHOT_FRAME_END"] == "1050"
    assert environment["SHOW"] == "fire"
    assert "PATH" not in environment
