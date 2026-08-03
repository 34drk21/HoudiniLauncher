from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path

from ..core.cache_manager import CacheManager, CacheReference, CacheScanResult
from ..core.environment import EnvironmentResolver
from ..core.exceptions import HoudiniLaunchError
from ..core.hip_manager import HipRecord
from ..core.models import (
    HoudiniInstallation,
    LauncherSettings,
    ProjectSettings,
    TaskSettings,
)
from .process_options import hidden_console_options
from .hda_manager import HdaManager


class HoudiniCacheScanner:
    """Inspect a selected HIP with hython and resolve its cache-version inventory."""

    def __init__(
        self,
        environment_resolver: EnvironmentResolver,
        cache_manager: CacheManager,
        launcher_root: Path,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        api_url: str = "",
        api_token: str = "",
        hda_manager: HdaManager | None = None,
    ) -> None:
        self.environment_resolver = environment_resolver
        self.cache_manager = cache_manager
        self.launcher_root = launcher_root.resolve()
        self._run = run
        self.api_url = api_url
        self.api_token = api_token
        self.hda_manager = hda_manager

    def scan(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        hip: HipRecord,
        installation: HoudiniInstallation,
        launcher_settings: LauncherSettings,
        user: str,
    ) -> CacheScanResult:
        """Return used and sibling cache versions for one selected HIP."""
        if not hip.path.is_file():
            raise FileNotFoundError(f"HIP file is missing: {hip.path}")
        if not installation.hython_executable or not installation.hython_executable.is_file():
            raise HoudiniLaunchError(
                f"hython.exe is missing: {installation.hython_executable or 'not registered'}"
            )
        script = Path(__file__).with_name("cache_probe.py")
        integration = (
            self.hda_manager.integration(installation) if self.hda_manager else None
        )
        environment = self.environment_resolver.build(
            project,
            task,
            installation,
            launcher_environment=launcher_settings.launcher_environment,
            launcher_root=str(self.launcher_root),
            hip_path=str(hip.path),
            user=user,
            user_id=launcher_settings.user_id,
            machine_id=launcher_settings.machine_id,
            api_url=self.api_url,
            api_token=self.api_token,
            managed_hda_root=str(integration.root) if integration else "",
            managed_hda_version=(
                integration.builder_fingerprint if integration else ""
            ),
        )
        try:
            completed = self._run(
                [str(installation.hython_executable), str(script), str(hip.path)],
                env=environment,
                cwd=self.environment_resolver.path_resolver.resolve_houdini_root(
                    project, task
                ),
                capture_output=True,
                text=True,
                timeout=180,
                **hidden_console_options(),
            )
        except subprocess.TimeoutExpired as exc:
            raise HoudiniLaunchError("Cache scan timed out after 180 seconds") from exc
        except OSError as exc:
            raise HoudiniLaunchError(f"Cannot start hython cache scan: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise HoudiniLaunchError(detail or "hython cache scan failed")
        marker = "HOUD2_CACHE_REFERENCES="
        payload = next(
            (
                line[len(marker) :]
                for line in completed.stdout.splitlines()
                if line.startswith(marker)
            ),
            None,
        )
        if payload is None:
            raise HoudiniLaunchError("hython did not return cache reference data")
        try:
            data = json.loads(payload)
            references = [
                CacheReference(
                    node_path=str(item["node_path"]),
                    parameter=str(item["parameter"]),
                    raw_path=str(item["raw_path"]),
                    expanded_path=Path(str(item["expanded_path"])),
                )
                for item in data
            ]
        except (json.JSONDecodeError, KeyError, TypeError) as exc:
            raise HoudiniLaunchError(f"Invalid cache scan result: {exc}") from exc
        records = self.cache_manager.discover(project, task, references)
        warnings = tuple(
            f"Outside managed cache roles: {record.path}"
            for record in records
            if not record.managed
        )
        return CacheScanResult(hip.path, records, warnings)
