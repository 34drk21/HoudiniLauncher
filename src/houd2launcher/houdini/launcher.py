from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable
from uuid import uuid4

from ..core.environment import EnvironmentResolver
from ..core.exceptions import HoudiniLaunchError
from ..core.hip_manager import HipManager, HipRecord
from ..core.models import (
    HoudiniInstallation,
    LauncherSettings,
    ProjectSettings,
    TaskSettings,
)
from ..database.repositories import LauncherRepository
from .process_options import hidden_console_options
from .editions import resolve_houdini_edition


@dataclass(frozen=True, slots=True)
class HoudiniValidationResult:
    """Result of an isolated hython license and HIP-save test."""

    license_type: str
    extension: str
    version: str


class HoudiniLauncher:
    """Create and open HIP files with an explicitly selected Houdini executable."""

    def __init__(
        self,
        environment_resolver: EnvironmentResolver,
        hip_manager: HipManager,
        repository: LauncherRepository,
        launcher_root: Path,
        popen: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
        api_url: str = "",
        api_token: str = "",
    ) -> None:
        self.environment_resolver = environment_resolver
        self.hip_manager = hip_manager
        self.repository = repository
        self.launcher_root = launcher_root.resolve()
        self.api_url = api_url
        self.api_token = api_token
        self._popen = popen
        self._run = run

    @staticmethod
    def extension_for_license(license_type: str, fallback: str = "hip") -> str:
        """Return the HIP extension required by a Houdini license category."""
        normalized = license_type.strip().casefold()
        if "indie" in normalized:
            return "hiplc"
        if "apprentice" in normalized or "noncommercial" in normalized:
            return "hipnc"
        if "commercial" in normalized or "education" in normalized:
            return "hip"
        return fallback.lower().lstrip(".")

    def probe_license(self, installation: HoudiniInstallation) -> str:
        """Query hython for its active license category and update the model."""
        self._validate_hython(installation)
        script = (
            "import hou; "
            "print('HOUD2_LICENSE=' + str(hou.licenseCategory()).split('.')[-1])"
        )
        completed = self._run_hython(installation, script, timeout=30)
        marker = next(
            (
                line.partition("=")[2].strip()
                for line in completed.stdout.splitlines()
                if line.startswith("HOUD2_LICENSE=")
            ),
            "",
        )
        if not marker:
            raise HoudiniLaunchError("hython did not report its Houdini license type")
        installation.license_type = marker
        installation.last_checked = datetime.now(timezone.utc)
        return marker

    def validate_hip_creation(
        self, installation: HoudiniInstallation
    ) -> HoudiniValidationResult:
        """Create and remove a temporary HIP to validate this hython installation."""
        self._validate_installation(installation)
        license_type = self.probe_license(installation)
        extension = self.extension_for_license(license_type)
        with tempfile.TemporaryDirectory(prefix="houd2launcher-validate-") as root:
            destination = Path(root) / f"validation.{extension}"
            script = (
                "import hou,sys; "
                "hou.hipFile.clear(suppress_save_prompt=True); "
                "hou.hipFile.save(file_name=sys.argv[1]); "
                "print('HOUD2_VERSION=' + hou.applicationVersionString())"
            )
            completed = self._run_hython(
                installation, script, str(destination), timeout=90
            )
            if not destination.is_file():
                raise HoudiniLaunchError("hython finished but did not create the test HIP")
            version = next(
                (
                    line.partition("=")[2].strip()
                    for line in completed.stdout.splitlines()
                    if line.startswith("HOUD2_VERSION=")
                ),
                installation.version_string,
            )
        installation.is_valid = True
        return HoudiniValidationResult(license_type, extension, version)

    def create_blank_hip(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        installation: HoudiniInstallation,
        launcher_settings: LauncherSettings,
        user: str,
        comment: str = "",
        extension: str | None = None,
    ) -> Path:
        """Use the selected hython to create a valid blank HIP and register metadata."""
        self._validate_installation(installation)
        self._validate_hython(installation)
        license_type = installation.license_type
        if not license_type or license_type.casefold() == "unknown":
            license_type = self.probe_license(installation)
        fallback = extension or project.naming.default_extension
        resolved_extension = self.extension_for_license(license_type, fallback)
        version, destination = self.hip_manager.next_path(
            project, task, user, resolved_extension, installation.version_string
        )
        destination.parent.mkdir(parents=True, exist_ok=True)
        environment = self._environment(
            project,
            task,
            installation,
            launcher_settings,
            destination,
            user,
            {},
        )
        script = (
            "import hou,sys; "
            "hou.hipFile.clear(suppress_save_prompt=True); "
            "hou.hipFile.save(file_name=sys.argv[1])"
        )
        try:
            completed = self._run_hython(
                installation,
                script,
                str(destination),
                env=environment,
                cwd=self.environment_resolver.path_resolver.resolve_houdini_root(project, task),
                timeout=90,
            )
        except Exception:
            destination.unlink(missing_ok=True)
            raise
        if not destination.is_file():
            destination.unlink(missing_ok=True)
            raise HoudiniLaunchError("hython finished but did not create the HIP file")
        self.hip_manager.register_created(
            project,
            task,
            destination,
            version,
            user,
            installation.installation_id,
            comment,
        )
        return destination

    def _run_hython(
        self,
        installation: HoudiniInstallation,
        script: str,
        *arguments: str,
        timeout: int,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
    ) -> subprocess.CompletedProcess[str]:
        command = [str(installation.hython_executable), "-c", script, *arguments]
        try:
            completed = self._run(
                command,
                env=env,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=timeout,
                **hidden_console_options(),
            )
        except subprocess.TimeoutExpired as exc:
            raise HoudiniLaunchError(
                f"hython timed out after {timeout} seconds"
            ) from exc
        except OSError as exc:
            raise HoudiniLaunchError(f"Cannot start hython: {exc}") from exc
        if completed.returncode != 0:
            detail = completed.stderr.strip() or completed.stdout.strip()
            raise HoudiniLaunchError(
                detail or f"hython exited with code {completed.returncode}"
            )
        return completed

    def open_hip(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        hip: HipRecord,
        installation: HoudiniInstallation,
        launcher_settings: LauncherSettings,
        user: str,
        read_only: bool = False,
        overrides: dict[str, str] | None = None,
        edition: str | None = None,
    ) -> subprocess.Popen[bytes]:
        """Open a HIP through the chosen executable and record the operation."""
        self._validate_installation(installation)
        selected_edition = resolve_houdini_edition(installation, edition)
        if not hip.path.is_file():
            raise HoudiniLaunchError(f"HIP file is missing: {hip.path}")
        open_path = self._read_only_copy(hip.path) if read_only else hip.path
        environment = self._environment(
            project,
            task,
            installation,
            launcher_settings,
            open_path,
            user,
            overrides or {},
        )
        try:
            startup_script = Path(__file__).with_name("apply_launch_settings.py")
            process = self._popen(
                [
                    str(selected_edition.executable),
                    str(open_path),
                    "waitforui",
                    str(startup_script),
                ],
                env=environment,
                cwd=self.environment_resolver.path_resolver.resolve_houdini_root(project, task),
            )
        except OSError as exc:
            raise HoudiniLaunchError(str(exc)) from exc
        hip.metadata.last_opened_with = installation.installation_id
        if not read_only:
            hip.metadata.last_saved_with = installation.installation_id
        self.hip_manager.save_metadata(project, task, hip.path, hip.metadata)
        self.repository.record_open(
            project.project_id,
            task.task_id,
            hip.path,
            installation.installation_id,
            "read_only" if read_only else "normal",
        )
        self.repository.record_activity(
            project.project_id,
            "hip_open",
            {
                "path": str(hip.path),
                "installation": installation.version_string,
                "edition": selected_edition.key,
                "read_only": read_only,
            },
            task.task_id,
        )
        return process

    def _environment(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        installation: HoudiniInstallation,
        launcher_settings: LauncherSettings,
        hip_path: Path,
        user: str,
        overrides: dict[str, str],
    ) -> dict[str, str]:
        return self.environment_resolver.build(
            project,
            task,
            installation,
            launcher_environment=launcher_settings.launcher_environment,
            open_overrides=overrides,
            launcher_root=str(self.launcher_root),
            hip_path=str(hip_path),
            user=user,
            user_id=launcher_settings.user_id,
            machine_id=launcher_settings.machine_id,
            api_url=self.api_url,
            api_token=self.api_token,
        )

    @staticmethod
    def _validate_installation(installation: HoudiniInstallation) -> None:
        if not installation.enabled or not installation.is_valid:
            raise HoudiniLaunchError("The selected Houdini installation is disabled or invalid")
        if not installation.houdini_executable.is_file():
            raise HoudiniLaunchError(
                f"houdini.exe is missing: {installation.houdini_executable}"
            )

    @staticmethod
    def _validate_hython(installation: HoudiniInstallation) -> None:
        if not installation.hython_executable or not installation.hython_executable.is_file():
            raise HoudiniLaunchError(
                f"hython.exe is missing: {installation.hython_executable or 'not registered'}"
            )

    @staticmethod
    def _read_only_copy(source: Path) -> Path:
        root = Path(tempfile.gettempdir()) / "HouD2Launcher" / "read_only" / str(uuid4())
        root.mkdir(parents=True)
        destination = root / source.name
        shutil.copy2(source, destination)
        os.chmod(destination, stat.S_IREAD)
        return destination
