from __future__ import annotations

from ..core.hip_manager import HipRecord
from ..core.models import (
    HoudiniInstallation,
    LauncherSettings,
    ProjectSettings,
)
from .compatibility import assess_compatibility


def should_show_open_dialog(
    launcher: LauncherSettings,
    project: ProjectSettings,
    hip: HipRecord,
    installations: list[HoudiniInstallation],
    selected: HoudiniInstallation,
    explicit_open_with: bool = False,
) -> bool:
    """Return whether version choice or risk requires the HIP Open dialog."""
    if explicit_open_with or launcher.show_open_dialog:
        return True
    if len(installations) > 1 or project.houdini.fallback_policy == "always_ask":
        return True
    known_ids = {item.installation_id for item in installations}
    preferred_id = hip.metadata.recommended_installation_id
    if preferred_id and preferred_id not in known_ids:
        return True
    saved = next(
        (
            item
            for item in installations
            if item.installation_id == hip.metadata.last_saved_with
        ),
        None,
    )
    compatibility = assess_compatibility(saved, selected)
    if compatibility.severity in {"warning", "high_risk"}:
        return True
    if hip.metadata.last_opened_with and hip.metadata.last_opened_with != selected.installation_id:
        return True
    return False

