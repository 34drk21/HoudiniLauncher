from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path

from houd2launcher.core.cache_manager import CacheManager
from houd2launcher.core.environment import EnvironmentResolver
from houd2launcher.core.hip_manager import HipManager
from houd2launcher.core.models import HoudiniInstallation, LauncherSettings, TaskSettings
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.houdini.cache_scanner import HoudiniCacheScanner


def test_scanner_parses_hython_references(project, repository, resolver, tmp_path: Path) -> None:
    ProjectManager(repository, resolver).create(project)
    task = TaskManager(repository, resolver).create(
        project, TaskSettings(project_id=project.project_id, name="scanner_test")
    )
    manager = HipManager(repository, resolver)
    version, hip_path = manager.next_path(project, task, "QA")
    hip_path.write_bytes(b"hip")
    manager.register_created(project, task, hip_path, version, "QA", "install")
    hip = manager.list_hips(project, task)[0]
    cache = resolver.resolve_role(project, task, "geo_cache") / "water" / "v004"
    cache.mkdir(parents=True)
    cache_file = cache / "water.1001.bgeo.sc"
    cache_file.write_bytes(b"cache")
    install_root = tmp_path / "Houdini"
    install_root.mkdir()
    houdini = install_root / "houdini.exe"
    hython = install_root / "hython.exe"
    houdini.write_bytes(b"")
    hython.write_bytes(b"")
    installation = HoudiniInstallation(
        display_name="Houdini Test",
        major=21,
        minor=0,
        build=1,
        version_string="21.0.1",
        install_root=install_root,
        houdini_executable=houdini,
        hython_executable=hython,
    )
    payload = json.dumps(
        [
            {
                "node_path": "/obj/water/filecache1",
                "parameter": "file",
                "raw_path": "$HIP/geo/water/v004/water.$F4.bgeo.sc",
                "expanded_path": str(cache_file),
            }
        ]
    )

    run_options: dict[str, object] = {}

    def fake_run(command: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        run_options.update(options)
        return subprocess.CompletedProcess(
            command, 0, f"HOUD2_CACHE_REFERENCES={payload}\n", ""
        )

    scanner = HoudiniCacheScanner(
        EnvironmentResolver(resolver),
        CacheManager(resolver),
        tmp_path,
        run=fake_run,
    )
    result = scanner.scan(
        project, task, hip, installation, LauncherSettings(), "QA"
    )
    assert len(result.records) == 1
    assert result.records[0].version == 4
    assert result.records[0].is_used
    assert result.records[0].size == 5
    if os.name == "nt":
        assert run_options["creationflags"] == subprocess.CREATE_NO_WINDOW
    else:
        assert "creationflags" not in run_options
