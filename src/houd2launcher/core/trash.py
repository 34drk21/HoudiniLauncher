import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from uuid import uuid4

from send2trash import send2trash as native_send2trash

from .exceptions import PathSafetyError


@dataclass(frozen=True, slots=True)
class TrashResult:
    """Describe where a deleted item can be recovered from."""

    original_path: Path
    method: str
    recovery_path: Path | None = None


def send_to_trash(path: Path) -> TrashResult:
    """Move an item to native Trash, with a recoverable sibling fallback."""
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    try:
        native_send2trash(str(resolved))
        if not resolved.exists():
            return TrashResult(resolved, "native")
    except (OSError, RuntimeError):
        pass

    try:
        trash_dir = resolved.parent / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        destination = trash_dir / f"{resolved.name}_{uuid4().hex}"
        try:
            os.replace(resolved, destination)
        except OSError:
            shutil.move(str(resolved), str(destination))
        return TrashResult(resolved, "fallback", destination)
    except Exception as exc:
        raise OSError(f"Failed to safely move '{resolved}' to trash: {exc}") from exc
