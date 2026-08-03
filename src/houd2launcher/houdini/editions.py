from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from ..core.exceptions import HoudiniLaunchError
from ..core.models import HoudiniInstallation


@dataclass(frozen=True, slots=True)
class HoudiniEdition:
    """A Houdini product UI available in one installation."""

    key: str
    label: str
    executable: Path


def available_houdini_editions(
    installation: HoudiniInstallation,
) -> tuple[HoudiniEdition, ...]:
    """Return installed product UIs in launch priority order (FX, then Core)."""
    executable = installation.houdini_executable
    suffix = executable.suffix
    candidates = (
        HoudiniEdition("fx", "Houdini FX", executable.with_name(f"houdinifx{suffix}")),
        HoudiniEdition(
            "core", "Houdini Core", executable.with_name(f"houdinicore{suffix}")
        ),
    )
    available = tuple(item for item in candidates if item.executable.is_file())
    if available:
        return available
    return (HoudiniEdition("auto", "Houdini (Automatic)", executable),)


def resolve_houdini_edition(
    installation: HoudiniInstallation, edition_key: str | None = None
) -> HoudiniEdition:
    """Resolve a requested product UI, defaulting to the highest-priority option."""
    editions = available_houdini_editions(installation)
    if edition_key is None:
        return editions[0]
    selected = next((item for item in editions if item.key == edition_key), None)
    if selected is None:
        raise HoudiniLaunchError(
            f"Houdini edition '{edition_key}' is not available in "
            f"{installation.display_name}"
        )
    return selected
