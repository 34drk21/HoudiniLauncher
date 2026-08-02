from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from .application import ApplicationContext
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def main() -> int:
    """Start the standalone HouD2Launcher desktop application."""
    app = QApplication(sys.argv)
    app.setApplicationName("HouD2Launcher")
    app.setOrganizationName("HouD2")
    app.setStyle("Fusion")
    from pathlib import Path

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    context = ApplicationContext.create(root)
    app.aboutToQuit.connect(context.shutdown)
    apply_theme(app, context.settings.theme)
    window = MainWindow(context)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
