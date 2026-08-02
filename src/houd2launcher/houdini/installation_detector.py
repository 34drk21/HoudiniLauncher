from __future__ import annotations

import re
from datetime import datetime, timezone
from pathlib import Path

from ..core.models import HoudiniInstallation


VERSION_PATTERN = re.compile(
    r"Houdini\s+(?P<major>\d+)\.(?P<minor>\d+)\.(?P<build>\d+)", re.IGNORECASE
)


class HoudiniInstallationDetector:
    """Detect Windows Houdini installations without depending on one registry key."""

    def scan(self, roots: list[Path] | None = None) -> list[HoudiniInstallation]:
        """Scan known installation roots and return unique valid builds."""
        candidates = roots or [Path("C:/Program Files/Side Effects Software")]
        found: dict[str, HoudiniInstallation] = {}
        for root in candidates:
            if not root.is_dir():
                continue
            for install_root in root.iterdir():
                if not install_root.is_dir():
                    continue
                installation = self.from_install_root(install_root, source="auto")
                if installation:
                    key = str(installation.houdini_executable.resolve()).casefold()
                    found[key] = installation
        return sorted(found.values(), key=lambda item: item.version_tuple, reverse=True)

    def from_install_root(
        self, install_root: Path, source: str = "manual"
    ) -> HoudiniInstallation | None:
        """Build an installation model from a SideFX installation directory."""
        match = VERSION_PATTERN.search(install_root.name)
        if not match:
            return None
        major, minor, build = (
            int(match.group("major")),
            int(match.group("minor")),
            int(match.group("build")),
        )
        houdini = self._first_existing(
            install_root / "bin" / "houdini.exe", install_root / "houdini.exe"
        )
        if houdini is None:
            return None
        hython = self._first_existing(
            install_root / "bin" / "hython.exe", install_root / "hython.exe"
        )
        hbatch = self._first_existing(
            install_root / "bin" / "hbatch.exe", install_root / "hbatch.exe"
        )
        version_string = f"{major}.{minor}.{build}"
        return HoudiniInstallation(
            display_name=f"Houdini {version_string}",
            major=major,
            minor=minor,
            build=build,
            version_string=version_string,
            install_root=install_root.resolve(),
            houdini_executable=houdini.resolve(),
            hython_executable=hython.resolve() if hython else None,
            hbatch_executable=hbatch.resolve() if hbatch else None,
            source=source,  # type: ignore[arg-type]
            enabled=True,
            is_valid=True,
            last_checked=datetime.now(timezone.utc),
        )

    @staticmethod
    def _first_existing(*paths: Path) -> Path | None:
        return next((path for path in paths if path.is_file()), None)

