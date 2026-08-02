from __future__ import annotations

import os
import subprocess


def hidden_console_options() -> dict[str, int]:
    """Return subprocess options that suppress console flashes on Windows."""
    if os.name != "nt":
        return {}
    return {"creationflags": subprocess.CREATE_NO_WINDOW}
