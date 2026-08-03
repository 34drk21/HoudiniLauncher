from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict

from ..core.models import HoudiniInstallation
from .process_options import hidden_console_options


class HdaBuildError(RuntimeError):
    """Raised when a managed Commercial HDA cannot be generated."""


class HdaBuildManifest(BaseModel):
    """Validated metadata for one generated HDA/Python integration bundle."""

    model_config = ConfigDict(extra="forbid")
    format: Literal["houd2.hda_build"] = "houd2.hda_build"
    schema_version: Literal[1] = 1
    houdini_version: str
    builder_fingerprint: str
    hda_sha256: str
    built_at: datetime


@dataclass(frozen=True, slots=True)
class HdaIntegration:
    root: Path
    otls_root: Path
    python_root: Path
    library_path: Path
    builder_fingerprint: str


@dataclass(frozen=True, slots=True)
class HdaStatus:
    state: Literal["ready", "stale", "missing", "failed", "unavailable"]
    label: str
    message: str = ""
    integration: HdaIntegration | None = None


class HdaManager:
    """Build and resolve per-Houdini managed Cache HDA integrations."""

    def __init__(
        self,
        launcher_root: Path,
        data_home: Path,
        run: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
    ) -> None:
        self.launcher_root = launcher_root.resolve()
        self.data_root = (data_home / "hda").resolve()
        self.source_root = self.launcher_root / "houdini"
        self.builder = self.source_root / "scripts" / "build_cache_hdas.py"
        self.python_source = self.source_root / "python" / "houd2_cache"
        self._run = run

    def status(self, installation: HoudiniInstallation) -> HdaStatus:
        if not installation.hython_executable or not installation.hython_executable.is_file():
            return HdaStatus(
                "unavailable", "hython missing", "A valid hython.exe is required."
            )
        if not self._sources_available():
            return HdaStatus(
                "unavailable", "Builder unavailable", "HDA Builder sources are missing."
            )
        fingerprint = self.builder_fingerprint()
        integration = self.integration(installation)
        failure = self._read_json(self._failure_path(installation))
        failure_matches = failure.get("builder_fingerprint") == fingerprint
        failure_message = str(failure.get("message", "")) if failure_matches else ""
        if integration:
            if integration.builder_fingerprint == fingerprint:
                return HdaStatus("ready", "Ready", integration=integration)
            return HdaStatus(
                "stale",
                "Update available",
                failure_message,
                integration,
            )
        if failure_matches:
            return HdaStatus("failed", "Build failed", failure_message)
        return HdaStatus("missing", "Not built")

    def should_auto_build(self, installation: HoudiniInstallation) -> bool:
        status = self.status(installation)
        return status.state in {"missing", "stale"} and not status.message

    def integration(self, installation: HoudiniInstallation) -> HdaIntegration | None:
        active = self._read_json(self._active_path(installation))
        fingerprint = str(active.get("builder_fingerprint", ""))
        if not fingerprint or not _is_sha256(fingerprint):
            return None
        root = self._version_root(installation) / fingerprint
        try:
            root.resolve().relative_to(self.data_root)
        except ValueError:
            return None
        manifest_path = root / "hda_build.json"
        try:
            manifest = HdaBuildManifest.model_validate_json(
                manifest_path.read_text(encoding="utf-8")
            )
        except Exception:
            return None
        library = root / "otls" / "houd2_cache.hda"
        python_root = root / "python"
        if (
            manifest.builder_fingerprint != fingerprint
            or manifest.houdini_version != self._version_key(installation)
            or not library.is_file()
            or not (python_root / "houd2_cache" / "__init__.py").is_file()
            or _sha256(library) != manifest.hda_sha256
        ):
            return None
        return HdaIntegration(root, root / "otls", python_root, library, fingerprint)

    def build(self, installation: HoudiniInstallation) -> HdaIntegration:
        if not installation.hython_executable or not installation.hython_executable.is_file():
            raise HdaBuildError(f"hython.exe is missing: {installation.hython_executable}")
        if not self._sources_available():
            raise HdaBuildError("HDA Builder sources are missing from this Launcher release.")
        fingerprint = self.builder_fingerprint()
        version_root = self._version_root(installation)
        final_root = version_root / fingerprint
        existing = self._integration_at(installation, final_root, fingerprint)
        if existing:
            self._activate(installation, fingerprint)
            return existing
        if final_root.exists():
            invalid = version_root / f".{fingerprint}.invalid-{uuid4().hex}"
            os.replace(final_root, invalid)
            self._remove_staging(invalid)

        version_root.mkdir(parents=True, exist_ok=True)
        staging = version_root / f".{fingerprint}.writing-{uuid4().hex}"
        staging.mkdir()
        try:
            python_target = staging / "python" / "houd2_cache"
            shutil.copytree(self.python_source, python_target)
            library = staging / "otls" / "houd2_cache.hda"
            library.parent.mkdir(parents=True)
            environment = self._build_environment(staging / "python")
            completed = self._run(
                [
                    str(installation.hython_executable),
                    str(self.builder),
                    str(library),
                ],
                cwd=self.source_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=300,
                **hidden_console_options(),
            )
            if completed.returncode != 0:
                detail = completed.stderr.strip() or completed.stdout.strip()
                raise HdaBuildError(detail or "HDA Builder failed")
            if not library.is_file() or library.stat().st_size <= 0:
                raise HdaBuildError("HDA Builder completed without a valid .hda file")
            manifest = HdaBuildManifest(
                houdini_version=self._version_key(installation),
                builder_fingerprint=fingerprint,
                hda_sha256=_sha256(library),
                built_at=datetime.now(timezone.utc),
            )
            (staging / "hda_build.json").write_text(
                manifest.model_dump_json(indent=2), encoding="utf-8"
            )
            os.replace(staging, final_root)
            self._activate(installation, fingerprint)
            self._failure_path(installation).unlink(missing_ok=True)
            integration = self._integration_at(installation, final_root, fingerprint)
            if not integration:
                raise HdaBuildError("Generated HDA bundle failed post-build validation")
            return integration
        except subprocess.TimeoutExpired as exc:
            error = HdaBuildError("HDA Builder timed out after 300 seconds")
            self._record_failure(installation, fingerprint, str(error))
            raise error from exc
        except Exception as exc:
            error = exc if isinstance(exc, HdaBuildError) else HdaBuildError(str(exc))
            self._record_failure(installation, fingerprint, str(error))
            raise error
        finally:
            if staging.exists():
                self._remove_staging(staging)

    def builder_fingerprint(self) -> str:
        digest = hashlib.sha256()
        files = [self.builder, *sorted(self.python_source.glob("*.py"))]
        for path in files:
            digest.update(path.name.encode("utf-8"))
            digest.update(path.read_bytes())
        return digest.hexdigest()

    def _integration_at(
        self, installation: HoudiniInstallation, root: Path, fingerprint: str
    ) -> HdaIntegration | None:
        active = self._active_path(installation)
        previous = self._read_json(active)
        try:
            self._write_json(active, {"builder_fingerprint": fingerprint})
            return self.integration(installation)
        finally:
            if previous:
                self._write_json(active, previous)
            else:
                active.unlink(missing_ok=True)

    def _activate(self, installation: HoudiniInstallation, fingerprint: str) -> None:
        self._write_json(
            self._active_path(installation), {"builder_fingerprint": fingerprint}
        )

    def _record_failure(
        self, installation: HoudiniInstallation, fingerprint: str, message: str
    ) -> None:
        self._write_json(
            self._failure_path(installation),
            {
                "builder_fingerprint": fingerprint,
                "attempted_at": datetime.now(timezone.utc).isoformat(),
                "message": message,
            },
        )

    def _build_environment(self, python_root: Path) -> dict[str, str]:
        environment = dict(os.environ)
        for name in ("PYTHONHOME", "PYTHONUSERBASE", "PYTHONSTARTUP"):
            environment.pop(name, None)
        environment["PYTHONNOUSERSITE"] = "1"
        environment["PYTHONPATH"] = str(python_root)
        return environment

    def _sources_available(self) -> bool:
        return self.builder.is_file() and (self.python_source / "__init__.py").is_file()

    def _version_root(self, installation: HoudiniInstallation) -> Path:
        return self.data_root / self._version_key(installation)

    @staticmethod
    def _version_key(installation: HoudiniInstallation) -> str:
        return f"{installation.major}.{installation.minor}.{installation.build}"

    def _active_path(self, installation: HoudiniInstallation) -> Path:
        return self._version_root(installation) / "active.json"

    def _failure_path(self, installation: HoudiniInstallation) -> Path:
        return self._version_root(installation) / "failure.json"

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
            return value if isinstance(value, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    @staticmethod
    def _write_json(path: Path, value: dict[str, object]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_suffix(path.suffix + ".part")
        temporary.write_text(json.dumps(value, indent=2), encoding="utf-8")
        os.replace(temporary, path)

    def _remove_staging(self, path: Path) -> None:
        resolved = path.resolve()
        if resolved.parent != path.parent.resolve() or resolved.parent.parent != self.data_root:
            raise HdaBuildError(f"Refusing to remove unexpected HDA staging path: {path}")
        shutil.rmtree(resolved)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)
