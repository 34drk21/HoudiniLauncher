from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication, QDialog

from . import __version__
from .application import ApplicationContext
from .ui.dialogs.first_run_dialog import FirstRunDialog
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def application_icon_path() -> Path:
    """Return the packaged brand image used by every native Launcher window."""
    return Path(__file__).resolve().parent / "resources" / "icons" / "houd2_launcher.jpg"


def main() -> int:
    """Start the standalone HouD2Launcher desktop application."""
    if "--db-admin" in sys.argv:
        sys.argv.remove("--db-admin")
        from .admin.server import main as admin_main

        return admin_main()
    app = QApplication(sys.argv)
    app.setApplicationName("HouD2Launcher")
    app.setApplicationVersion(__version__)
    app.setOrganizationName("HouD2")
    app.setStyle("Fusion")
    icon_path = application_icon_path()
    if icon_path.is_file():
        app.setWindowIcon(QIcon(str(icon_path)))

    root = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[2]))
    context = ApplicationContext.create(root)
    app.aboutToQuit.connect(context.shutdown)
    apply_theme(app, context.settings.theme)
    if not context.settings.onboarding_completed:
        setup = FirstRunDialog(context.settings)
        if setup.exec() != QDialog.DialogCode.Accepted:
            context.shutdown()
            return 0
        context.settings = setup.result_settings()
        context.save_settings()
        apply_theme(app, context.settings.theme)
    window = MainWindow(context)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
