from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from ..core.models import HoudiniInstallation


Severity = Literal["information", "warning", "high_risk", "unknown"]


@dataclass(frozen=True, slots=True)
class CompatibilityResult:
    """Simple non-guaranteed compatibility assessment between Houdini builds."""

    severity: Severity
    message: str


def assess_compatibility(
    saved: HoudiniInstallation | None, selected: HoudiniInstallation
) -> CompatibilityResult:
    """Compare saved and selected Houdini versions using the PRD's simple rules."""
    if saved is None:
        return CompatibilityResult("unknown", "Detected HIP version is unknown.")
    saved_minor = saved.major, saved.minor
    selected_minor = selected.major, selected.minor
    if selected_minor == saved_minor:
        return CompatibilityResult(
            "information", "The selected Houdini uses the same major and minor version."
        )
    if selected_minor > saved_minor:
        return CompatibilityResult(
            "warning",
            "The selected Houdini is newer. Saving may upgrade the HIP and affect older builds.",
        )
    return CompatibilityResult(
        "high_risk",
        "The selected Houdini is older. Nodes or the HIP may not load correctly.",
    )

