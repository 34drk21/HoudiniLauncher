import shutil
import subprocess
import sys
from datetime import datetime
from pathlib import Path

from .exceptions import PathSafetyError


def send_to_trash(path: Path) -> None:
    """Move a file or directory to the OS Recycle Bin / Trash.

    If OS Recycle Bin is not supported on the target system or drive (e.g. network drives),
    safely moves the item to a local hidden .trash folder to guarantee zero data loss.
    """
    resolved = path.resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Path does not exist: {path}")

    if sys.platform == "win32":
        # Try 1: win32com.shell SHFileOperation with FOF_ALLOWUNDO
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

        # Try 2: PowerShell Microsoft.VisualBasic.FileIO.FileSystem SendToRecycleBin
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
        except Exception:
            pass

        # Try 3: PowerShell Shell.Application COM object
        try:
            parent_dir = str(resolved.parent)
            item_name = resolved.name
            cmd = (
                f"$shell = New-Object -ComObject Shell.Application; "
                f"$folder = $shell.Namespace('{parent_dir}'); "
                f"$item = $folder.ParseName('{item_name}'); "
                f"$item.InvokeVerb('delete')"
            )
            res = subprocess.run(
                ["powershell", "-NoProfile", "-Command", cmd],
                capture_output=True,
                text=True,
            )
            if res.returncode == 0 and not resolved.exists():
                return
        except Exception:
            pass
    else:
        # Try send2trash for macOS / Linux
        try:
            import send2trash  # type: ignore

            send2trash.send2trash(str(resolved))
            if not resolved.exists():
                return
        except Exception:
            pass

    # Safety Fallback for Network Drives / Unsupported Systems:
    # Move item into a hidden .trash folder in its parent directory so it is NEVER hard-deleted.
    try:
        trash_dir = resolved.parent / ".trash"
        trash_dir.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        destination = trash_dir / f"{resolved.name}_{timestamp}"
        shutil.move(str(resolved), str(destination))
    except Exception as exc:
        raise OSError(f"Failed to safely move '{resolved}' to trash: {exc}") from exc

