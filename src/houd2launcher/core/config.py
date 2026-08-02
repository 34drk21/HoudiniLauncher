from __future__ import annotations

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import TypeVar

from pydantic import BaseModel


LOGGER = logging.getLogger(__name__)
ModelT = TypeVar("ModelT", bound=BaseModel)


def launcher_home() -> Path:
    """Return the per-user launcher data directory."""
    override = os.getenv("HOUD2_HOME")
    if override:
        return Path(override).expanduser().resolve()
    local_app_data = os.getenv("LOCALAPPDATA")
    if local_app_data:
        return Path(local_app_data) / "HouD2Launcher"
    return Path.home() / ".houd2launcher"


def atomic_write_model(path: Path, model: BaseModel) -> Path:
    """Atomically persist a Pydantic model as UTF-8 JSON."""
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    try:
        temporary.write_text(
            model.model_dump_json(indent=2, exclude_none=False), encoding="utf-8"
        )
        os.replace(temporary, path)
    except OSError:
        temporary.unlink(missing_ok=True)
        raise
    return path


def load_model(path: Path, model_type: type[ModelT]) -> ModelT:
    """Load and validate a Pydantic model from JSON."""
    return model_type.model_validate_json(path.read_text(encoding="utf-8"))


def backup_file(path: Path, backup_root: Path | None = None) -> Path | None:
    """Create a timestamped backup of a settings file when it exists."""
    if not path.is_file():
        return None
    destination_root = backup_root or path.parent / "backups"
    destination_root.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    destination = destination_root / f"{path.stem}_{timestamp}{path.suffix}.bak"
    shutil.copy2(path, destination)
    LOGGER.info("Created settings backup: %s", destination)
    return destination


def load_json_object(path: Path) -> dict[str, object]:
    """Load a JSON object without changing any existing settings."""
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("JSON root must be an object")
    return data

