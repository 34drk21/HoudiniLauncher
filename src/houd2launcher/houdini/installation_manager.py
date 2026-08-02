from __future__ import annotations

from pathlib import Path

from ..core.exceptions import DuplicateRegistrationError
from ..core.models import HoudiniInstallation, LauncherSettings


class HoudiniInstallationManager:
    """Merge detected and manual Houdini installations into launcher settings."""

    @staticmethod
    def register(
        settings: LauncherSettings, installation: HoudiniInstallation
    ) -> HoudiniInstallation:
        """Register one unique Houdini executable."""
        executable = str(installation.houdini_executable.resolve()).casefold()
        if any(
            str(item.houdini_executable.resolve()).casefold() == executable
            for item in settings.installations
        ):
            raise DuplicateRegistrationError(
                f"Houdini executable is already registered: {installation.houdini_executable}"
            )
        settings.installations.append(installation)
        settings.installations.sort(key=lambda item: item.version_tuple, reverse=True)
        return installation

    @staticmethod
    def merge_detected(
        settings: LauncherSettings, detected: list[HoudiniInstallation]
    ) -> int:
        """Add newly detected executables and refresh matching records."""
        existing = {
            str(item.houdini_executable.resolve()).casefold(): item
            for item in settings.installations
        }
        added = 0
        for installation in detected:
            key = str(installation.houdini_executable.resolve()).casefold()
            if key in existing:
                current = existing[key]
                current.is_valid = installation.is_valid
                current.last_checked = installation.last_checked
                continue
            settings.installations.append(installation)
            existing[key] = installation
            added += 1
        settings.installations.sort(key=lambda item: item.version_tuple, reverse=True)
        return added

    @staticmethod
    def validate(installation: HoudiniInstallation) -> bool:
        """Refresh whether the registered executable paths still exist."""
        installation.is_valid = installation.houdini_executable.is_file()
        if installation.hython_executable:
            installation.hython_executable = Path(installation.hython_executable)
        return installation.is_valid

    @staticmethod
    def enabled(settings: LauncherSettings) -> list[HoudiniInstallation]:
        """Return enabled, valid builds in newest-first order."""
        return sorted(
            [item for item in settings.installations if item.enabled and item.is_valid],
            key=lambda item: item.version_tuple,
            reverse=True,
        )

    @staticmethod
    def by_id(
        settings: LauncherSettings, installation_id: str | None
    ) -> HoudiniInstallation | None:
        """Find one installation by stable ID."""
        return next(
            (
                item
                for item in settings.installations
                if item.installation_id == installation_id
            ),
            None,
        )

    @classmethod
    def select_preferred(
        cls, settings: LauncherSettings, preference_ids: list[str | None]
    ) -> HoudiniInstallation | None:
        """Resolve ordered preferences, falling back to the newest enabled build."""
        enabled = cls.enabled(settings)
        for installation_id in preference_ids:
            match = next(
                (
                    item
                    for item in enabled
                    if item.installation_id == installation_id
                ),
                None,
            )
            if match:
                return match
        return enabled[0] if enabled else None
