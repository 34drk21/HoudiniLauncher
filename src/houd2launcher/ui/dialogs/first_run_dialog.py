from __future__ import annotations

from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ...core.models import LauncherSettings
from ...core.validation import validate_filename_component
from ...houdini.installation_manager import HoudiniInstallationManager
from ..widgets import add_helped_row
from .launcher_settings_dialog import InstallationScanThread


class FirstRunDialog(QDialog):
    """Collect the required per-user identity before the first Launcher session."""

    def __init__(
        self, settings: LauncherSettings, parent: QWidget | None = None
    ) -> None:
        super().__init__(parent)
        self.working = settings.model_copy(deep=True)
        self._result: LauncherSettings | None = None
        self.scan_thread: InstallationScanThread | None = None
        self.setWindowTitle("HouD2Launcher First Run Setup")
        self.setMinimumWidth(680)

        layout = QVBoxLayout(self)
        title = QLabel("Set up this workstation")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        form = QFormLayout()
        self.display_name = QLineEdit(settings.display_name)
        self.display_name.setPlaceholderText("Example: Shota Yamada")
        self.initials = QLineEdit(settings.initials)
        self.initials.setMaxLength(8)
        self.initials.setPlaceholderText("Example: SY")
        self.language = QComboBox()
        self.language.addItem("Japanese", "ja")
        self.language.addItem("English", "en")
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        self.theme = QComboBox()
        self.theme.addItems(["dark", "light", "system"])
        self.theme.setCurrentText(settings.theme)

        self.project_root = QLineEdit(
            str(settings.default_project_root) if settings.default_project_root else ""
        )
        project_browse = QPushButton("Browse")
        project_browse.clicked.connect(
            lambda: self._browse_directory(self.project_root, "Default Project Root")
        )
        self.update_path = QLineEdit(
            str(settings.update_channel_path) if settings.update_channel_path else ""
        )
        update_browse = QPushButton("Browse")
        update_browse.clicked.connect(
            lambda: self._browse_directory(self.update_path, "Update Channel")
        )

        add_helped_row(
            form,
            "Display Name",
            self.display_name,
            "Cache creator information and Launcher history use this name.",
        )
        add_helped_row(
            form,
            "Initials",
            self.initials,
            "HIP filenames use this value for the {user} token.",
        )
        add_helped_row(form, "Language", self.language, "Launcher display language.")
        add_helped_row(form, "Theme", self.theme, "Initial Launcher appearance.")
        add_helped_row(
            form,
            "Default Project Root",
            self._path_row(self.project_root, project_browse),
            "Optional starting folder used by New Project.",
        )
        add_helped_row(
            form,
            "Update Channel",
            self._path_row(self.update_path, update_browse),
            "Optional shared folder containing latest.json and the Installer.",
        )
        layout.addLayout(form)

        houdini_row = QHBoxLayout()
        self.houdini = QComboBox()
        self.scan = QPushButton("Auto Detect Houdini")
        self.scan.clicked.connect(self._detect_houdini)
        houdini_row.addWidget(self.houdini, 1)
        houdini_row.addWidget(self.scan)
        layout.addWidget(QLabel("Default Houdini Installation"))
        layout.addLayout(houdini_row)
        self.scan_status = QLabel("Houdiniを検索します...")
        self.scan_status.setObjectName("FieldHelp")
        layout.addWidget(self.scan_status)
        self._refresh_houdini()

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel
            | QDialogButtonBox.StandardButton.Save
        )
        buttons.button(QDialogButtonBox.StandardButton.Cancel).setText("Exit")
        buttons.button(QDialogButtonBox.StandardButton.Save).setText("Finish")
        self.finish_button = buttons.button(QDialogButtonBox.StandardButton.Save)
        self.finish_button.setEnabled(False)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        QTimer.singleShot(0, self._detect_houdini)

    def result_settings(self) -> LauncherSettings:
        if self._result is None:
            raise RuntimeError("First Run Setup was not completed")
        return self._result

    def accept(self) -> None:
        name = self.display_name.text().strip()
        initials = self.initials.text().strip()
        if not name:
            QMessageBox.warning(self, "Display Name Required", "Enter a Display Name.")
            return
        if len(name) > 64:
            QMessageBox.warning(
                self, "Invalid Display Name", "Display Name must be 64 characters or fewer."
            )
            return
        if not initials:
            QMessageBox.warning(self, "Initials Required", "Enter filename initials.")
            return
        try:
            validate_filename_component(initials, "Initials")
        except ValueError as exc:
            QMessageBox.warning(self, "Invalid Initials", str(exc))
            return

        data = self.working.model_dump(mode="python")
        project_root = self.project_root.text().strip()
        update_path = self.update_path.text().strip()
        data.update(
            {
                "onboarding_completed": True,
                "display_name": name,
                "initials": initials,
                "language": self.language.currentData(),
                "theme": self.theme.currentText(),
                "default_project_root": Path(project_root) if project_root else None,
                "update_channel_path": Path(update_path) if update_path else None,
                "default_installation_id": self.houdini.currentData(),
            }
        )
        try:
            self._result = LauncherSettings.model_validate(data)
        except ValidationError as exc:
            QMessageBox.warning(self, "Invalid First Run Settings", str(exc))
            return
        super().accept()

    def reject(self) -> None:
        if self.scan_thread and self.scan_thread.isRunning():
            self.scan_thread.wait(10000)
        super().reject()

    def _detect_houdini(self) -> None:
        if self.scan_thread and self.scan_thread.isRunning():
            return
        self.scan.setEnabled(False)
        self.scan.setText("Scanning...")
        self.scan_status.setText("このPCにインストールされたHoudini Versionを検索中です...")
        self.finish_button.setEnabled(False)
        self.scan_thread = InstallationScanThread(self)
        self.scan_thread.completed.connect(self._houdini_detected)
        self.scan_thread.failed.connect(self._houdini_scan_failed)
        self.scan_thread.finished.connect(lambda: self.scan.setEnabled(True))
        self.scan_thread.finished.connect(lambda: self.scan.setText("Auto Detect Houdini"))
        self.scan_thread.start()

    def _houdini_detected(self, detected: object) -> None:
        values = list(detected) if isinstance(detected, list) else []
        HoudiniInstallationManager.merge_detected(self.working, values)
        self._refresh_houdini()
        self.scan_status.setText(
            f"{len(values)}個のHoudini Versionを検出しました。"
            if values
            else "Houdiniが見つかりませんでした。後からLauncher Settingsで追加できます。"
        )
        self.finish_button.setEnabled(True)

    def _houdini_scan_failed(self, message: str) -> None:
        self.scan_status.setText("Houdini Scanに失敗しました。後から再実行できます。")
        self.finish_button.setEnabled(True)
        QMessageBox.warning(self, "Houdini Scan Failed", message)

    def _refresh_houdini(self) -> None:
        selected = self.working.default_installation_id
        self.houdini.clear()
        self.houdini.addItem("Set later", None)
        for installation in HoudiniInstallationManager.enabled(self.working):
            self.houdini.addItem(installation.display_name, installation.installation_id)
        index = self.houdini.findData(selected)
        if (selected is None or index < 0) and self.houdini.count() > 1:
            index = 1
        self.houdini.setCurrentIndex(max(0, index))

    def _browse_directory(self, target: QLineEdit, title: str) -> None:
        path = QFileDialog.getExistingDirectory(self, title, target.text())
        if path:
            target.setText(path)

    @staticmethod
    def _path_row(edit: QLineEdit, button: QPushButton) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return widget
