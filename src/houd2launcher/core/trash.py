"""Utility to safely move files or directories to the system Recycle Bin / Trash."""

from __future__ import annotations

import sys
import subprocess
from pathlib import Path

from .exceptions import PathSafetyError


def send_to_trash(path: Path) -> None:
    """Move a file or directory to the OS Recycle Bin / Trash.

    Raises FileNotFoundError if path does not exist.
    Raises PathSafetyError or OSError if trashing fails.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if sys.platform == "win32":
        # Primary Windows method: win32com.shell SHFileOperation with FOF_ALLOWUNDO
        try:
            from win32com.shell import shell, shellcon  # type: ignore

            path_str = str(resolved) + "\0"
            res, aborted = shell.SHFileOperation(
                (
                    0,
                    shellcon.FO_DELETE,
                    path_str,
                    None,
                    shellcon.FOF_ALLOWUNDO
                    | shellcon.FOF_NOCONFIRMATION
                    | shellcon.FOF_SILENT,
                    None,
                    None,
                )
            )
            if res == 0 and not aborted and not resolved.exists():
                return
        except Exception:
            pass

        # Fallback Windows method: PowerShell Microsoft.VisualBasic.FileIO.FileSystem
        try:
            is_file = resolved.is_file()
            method = "DeleteFile" if is_file else "DeleteDirectory"
            cmd = (
                f"Add-Type -AssemblyName Microsoft.VisualBasic; "
                f"[Microsoft.VisualBasic.FileIO.FileSystem]::{method}("
                f"'{resolved}', 'OnlyErrorDialogs', 'SendToRecycleBin')"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and not resolved.exists():
                return
            raise OSError(
                f"PowerShell Recycle Bin failed with exit code {res.returncode}: {res.stderr or res.stdout}"
            )
        except Exception as exc:
            raise OSError(f"Failed to move '{resolved}' to Recycle Bin: {exc}") from exc
    else:
        # macOS / Linux fallback: try send2trash
        try:
            import send2trash  # type: ignore

            send2trash.send2trash(str(resolved))
            return
        except ImportError:
            pass

        raise OSError(f"Moving to trash is not supported on platform: {sys.platform}")
