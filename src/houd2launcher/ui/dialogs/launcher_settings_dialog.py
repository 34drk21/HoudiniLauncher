from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import QThread, Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
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
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.models import HoudiniInstallation, LauncherSettings
from ...houdini.installation_detector import HoudiniInstallationDetector
from ...houdini.installation_manager import HoudiniInstallationManager
from .project_task_dialogs import KeyValueTable
from ..widgets import add_helped_row


class InstallationScanThread(QThread):
    """Run filesystem installation detection away from the GUI thread."""

    completed = Signal(object)
    failed = Signal(str)

    def run(self) -> None:
        try:
            self.completed.emit(HoudiniInstallationDetector().scan())
        except OSError as exc:
            self.failed.emit(str(exc))


class InstallationValidationThread(QThread):
    """Run a real temporary HIP creation test outside the GUI thread."""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], object], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.operation = operation

    def run(self) -> None:
        try:
            self.completed.emit(self.operation())
        except Exception as exc:
            self.failed.emit(str(exc))


class ManualInstallationDialog(QDialog):
    """Collect a portable or custom Houdini installation registration."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Add Houdini Installation")
        self.setMinimumWidth(600)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.display_name = QLineEdit()
        self.display_name.setPlaceholderText("例: Houdini 21.0.671 Indie")
        self.version = QLineEdit("21.0.000")
        self.root = QLineEdit()
        self.root.setPlaceholderText(r"例: C:\Program Files\Side Effects Software\Houdini 21.0.671")
        self.houdini = QLineEdit()
        self.hython = QLineEdit()
        root_button = QPushButton("Browse")
        root_button.clicked.connect(self._browse_root)
        exe_button = QPushButton("Browse")
        exe_button.clicked.connect(lambda: self._browse_file(self.houdini, "houdini.exe"))
        hython_button = QPushButton("Browse")
        hython_button.clicked.connect(lambda: self._browse_file(self.hython, "hython.exe"))
        add_helped_row(form, "Display name", self.display_name, "Launcher内で表示する分かりやすい名前です。")
        add_helped_row(form, "Version", self.version, "major.minor.build形式で入力します。例: 21.0.671")
        add_helped_row(form, "Install root", self._row(self.root, root_button), "Houdiniのインストールフォルダを指定します。")
        add_helped_row(form, "houdini.exe", self._row(self.houdini, exe_button), "HIPを開くHoudini本体の実行ファイルです。")
        add_helped_row(form, "hython.exe", self._row(self.hython, hython_button), "新規HIP作成とライセンス確認に使用します。")
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def installation(self) -> HoudiniInstallation:
        """Build a validated manual installation model."""
        parts = self.version.text().strip().split(".")
        if len(parts) != 3 or not all(part.isdigit() for part in parts):
            raise ValueError("Version must use major.minor.build, for example 21.0.487")
        major, minor, build = map(int, parts)
        houdini_path = Path(self.houdini.text())
        if not houdini_path.is_file():
            raise ValueError("Select an existing houdini.exe")
        hython_path = Path(self.hython.text()) if self.hython.text().strip() else None
        return HoudiniInstallation(
            display_name=self.display_name.text().strip() or f"Houdini {self.version.text()}",
            major=major,
            minor=minor,
            build=build,
            version_string=self.version.text().strip(),
            install_root=Path(self.root.text()),
            houdini_executable=houdini_path,
            hython_executable=hython_path,
            hbatch_executable=(Path(self.root.text()) / "bin" / "hbatch.exe"),
            source="manual",
            is_valid=houdini_path.is_file(),
        )

    def accept(self) -> None:
        try:
            self.installation()
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid installation", str(exc))
            return
        super().accept()

    @staticmethod
    def _row(edit: QLineEdit, button: QPushButton) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(edit, 1)
        layout.addWidget(button)
        return widget

    def _browse_root(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Install Root", self.root.text())
        if path:
            self.root.setText(path)
            bin_root = Path(path) / "bin"
            self.houdini.setText(str(bin_root / "houdini.exe"))
            self.hython.setText(str(bin_root / "hython.exe"))

    def _browse_file(self, target: QLineEdit, expected: str) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, f"Select {expected}", target.text(), "Executables (*.exe)"
        )
        if path:
            target.setText(path)


class LauncherSettingsDialog(QDialog):
    """Edit per-user launcher behavior and Houdini installation registrations."""

    def __init__(
        self,
        settings: LauncherSettings,
        parent: QWidget | None = None,
        hip_validator: Callable[[HoudiniInstallation], object] | None = None,
    ) -> None:
        super().__init__(parent)
        self.original = settings
        self.working = settings.model_copy(deep=True)
        self._result: LauncherSettings | None = None
        self.scan_thread: InstallationScanThread | None = None
        self.validation_thread: InstallationValidationThread | None = None
        self.hip_validator = hip_validator
        self.setWindowTitle("Launcher Settings")
        self.resize(840, 620)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general = QWidget()
        general_form = QFormLayout(general)
        self.remember_project = QCheckBox()
        self.remember_project.setChecked(settings.remember_last_project)
        self.remember_task = QCheckBox()
        self.remember_task.setChecked(settings.remember_last_task)
        self.double_click = QCheckBox()
        self.double_click.setChecked(settings.open_latest_on_double_click)
        self.show_open = QCheckBox()
        self.show_open.setChecked(settings.show_open_dialog)
        self.auto_refresh = QCheckBox()
        self.auto_refresh.setChecked(settings.auto_refresh)
        self.language = QComboBox()
        self.language.addItem("Japanese", "ja")
        self.language.addItem("English", "en")
        self.language.setCurrentIndex(max(0, self.language.findData(settings.language)))
        add_helped_row(general_form, "Remember last project", self.remember_project, "次回起動時に最後のProjectを再選択します。")
        add_helped_row(general_form, "Remember last task", self.remember_task, "次回起動時に最後のTaskを再選択します。")
        add_helped_row(general_form, "Double-click", self.double_click, "Taskをダブルクリックしたとき最新HIPを開きます。")
        add_helped_row(general_form, "Open dialog", self.show_open, "HIPを開く前にHoudiniバージョンとモードを確認します。")
        add_helped_row(general_form, "Auto refresh", self.auto_refresh, "作成・保存後に一覧を自動更新します。")
        add_helped_row(general_form, "Language", self.language, "Launcherの表示言語です。現在は一部の説明のみ日本語です。")
        tabs.addTab(general, "General")
        user = QWidget()
        user_form = QFormLayout(user)
        self.user_id = QLineEdit(settings.user_id)
        self.user_id.setReadOnly(True)
        self.display_name = QLineEdit(settings.display_name)
        self.display_name.setPlaceholderText("例: Shota Yamada")
        self.initials = QLineEdit(settings.initials)
        self.initials.setPlaceholderText("例: SY")
        add_helped_row(user_form, "User ID", self.user_id, "内部参照用の固定IDです。編集できません。")
        add_helped_row(user_form, "Display name", self.display_name, "履歴などに表示するユーザー名です。")
        add_helped_row(user_form, "Initials", self.initials, "HIPファイル名の{user}に使用します。例: SY")
        tabs.addTab(user, "User")
        self.environment_editor = KeyValueTable(settings.launcher_environment)
        tabs.addTab(self.environment_editor, "Environment")
        installations = QWidget()
        installation_layout = QVBoxLayout(installations)
        controls = QHBoxLayout()
        self.detect_button = QPushButton("Auto Detect")
        self.detect_button.clicked.connect(self._detect)
        add = QPushButton("Add Manually")
        add.clicked.connect(self._add_manual)
        remove = QPushButton("Remove")
        remove.clicked.connect(self._remove)
        self.validate_button = QPushButton("Test HIP Creation")
        self.validate_button.clicked.connect(self._validate_selected)
        self.validate_button.setEnabled(self.hip_validator is not None)
        controls.addWidget(self.detect_button)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addWidget(self.validate_button)
        controls.addStretch()
        installation_layout.addLayout(controls)
        help_label = QLabel("登録したHoudiniを選択してTest HIP Creationを実行すると、ライセンス判定と一時HIP保存を確認できます。")
        help_label.setObjectName("FieldHelp")
        help_label.setWordWrap(True)
        installation_layout.addWidget(help_label)
        self.installation_table = QTableWidget(0, 8)
        self.installation_table.setHorizontalHeaderLabels(
            ["Enabled", "Display Name", "Version", "Build", "License", "Install Path", "Status", "Source"]
        )
        self.installation_table.setWordWrap(False)
        self.installation_table.verticalHeader().setVisible(False)
        self.installation_table.horizontalHeader().setStretchLastSection(True)
        installation_layout.addWidget(self.installation_table)
        default_row = QHBoxLayout()
        default_row.addWidget(QLabel("Launcher default"))
        self.default_installation = QComboBox()
        default_row.addWidget(self.default_installation, 1)
        installation_layout.addLayout(default_row)
        tabs.addTab(installations, "Houdini Installations")
        ui = QWidget()
        ui_form = QFormLayout(ui)
        self.theme = QComboBox()
        self.theme.addItems(["system", "light", "dark"])
        self.theme.setCurrentText(settings.theme)
        self.thumbnail_size = QSpinBox()
        self.thumbnail_size.setRange(96, 512)
        self.thumbnail_size.setValue(settings.thumbnail_size)
        self.view_mode = QComboBox()
        self.view_mode.addItems(["cards", "compact", "detailed"])
        self.view_mode.setCurrentText(settings.task_view_mode)
        add_helped_row(ui_form, "Theme", self.theme, "Darkが既定です。保存するとすぐに外観へ反映されます。")
        add_helped_row(ui_form, "Thumbnail size", self.thumbnail_size, "Taskカードの画像幅です。例: 220px")
        add_helped_row(ui_form, "Task view mode", self.view_mode, "cards、compact、detailedから一覧密度を選びます。")
        tabs.addTab(ui, "UI")
        self._refresh_installations()
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_settings(self) -> LauncherSettings:
        """Return launcher settings captured on acceptance."""
        if self._result is None:
            raise RuntimeError("Dialog was not accepted")
        return self._result

    def accept(self) -> None:
        self._sync_enabled()
        data = self.working.model_dump(mode="python")
        data.update(
            {
                "display_name": self.display_name.text().strip(),
                "initials": self.initials.text().strip(),
                "remember_last_project": self.remember_project.isChecked(),
                "remember_last_task": self.remember_task.isChecked(),
                "open_latest_on_double_click": self.double_click.isChecked(),
                "show_open_dialog": self.show_open.isChecked(),
                "auto_refresh": self.auto_refresh.isChecked(),
                "language": self.language.currentData(),
                "launcher_environment": self.environment_editor.values(),
                "default_installation_id": self.default_installation.currentData(),
                "theme": self.theme.currentText(),
                "thumbnail_size": self.thumbnail_size.value(),
                "task_view_mode": self.view_mode.currentText(),
            }
        )
        try:
            self._result = LauncherSettings.model_validate(data)
        except ValidationError as exc:
            QMessageBox.warning(self, "Invalid launcher settings", str(exc))
            return
        super().accept()

    def _detect(self) -> None:
        if self.scan_thread and self.scan_thread.isRunning():
            return
        self.detect_button.setEnabled(False)
        self.detect_button.setText("Scanning...")
        self.scan_thread = InstallationScanThread(self)
        self.scan_thread.completed.connect(self._detected)
        self.scan_thread.failed.connect(self._scan_failed)
        self.scan_thread.finished.connect(lambda: self.detect_button.setEnabled(True))
        self.scan_thread.finished.connect(lambda: self.detect_button.setText("Auto Detect"))
        self.scan_thread.start()

    def _detected(self, installations: list[HoudiniInstallation]) -> None:
        added = HoudiniInstallationManager.merge_detected(self.working, installations)
        self._refresh_installations()
        QMessageBox.information(self, "Houdini Scan", f"Added {added} installation(s).")

    def _scan_failed(self, message: str) -> None:
        QMessageBox.warning(self, "Houdini Scan Failed", message)

    def _add_manual(self) -> None:
        dialog = ManualInstallationDialog(self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            HoudiniInstallationManager.register(self.working, dialog.installation())
        except Exception as exc:
            QMessageBox.warning(self, "Cannot register Houdini", str(exc))
            return
        self._refresh_installations()

    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.installation_table.selectedItems()}, reverse=True)
        for row in rows:
            if 0 <= row < len(self.working.installations):
                removed = self.working.installations.pop(row)
                if self.working.default_installation_id == removed.installation_id:
                    self.working.default_installation_id = None
        self._refresh_installations()

    def _validate_selected(self) -> None:
        row = self.installation_table.currentRow()
        if row < 0 or row >= len(self.working.installations) or not self.hip_validator:
            QMessageBox.information(self, "HIP Creation Test", "テストするHoudiniを選択してください。")
            return
        if self.validation_thread and self.validation_thread.isRunning():
            return
        installation = self.working.installations[row]
        self.validate_button.setEnabled(False)
        self.validate_button.setText("Testing...")
        self.validation_thread = InstallationValidationThread(
            lambda: self.hip_validator(installation), self
        )
        self.validation_thread.completed.connect(
            lambda result: self._validation_completed(installation, result)
        )
        self.validation_thread.failed.connect(
            lambda message: QMessageBox.warning(self, "HIP Creation Test Failed", message)
        )
        self.validation_thread.finished.connect(lambda: self.validate_button.setEnabled(True))
        self.validation_thread.finished.connect(lambda: self.validate_button.setText("Test HIP Creation"))
        self.validation_thread.start()

    def _validation_completed(
        self, installation: HoudiniInstallation, result: object
    ) -> None:
        self._refresh_installations()
        license_type = getattr(result, "license_type", installation.license_type)
        extension = getattr(result, "extension", "hip")
        version = getattr(result, "version", installation.version_string)
        QMessageBox.information(
            self,
            "HIP Creation Test",
            f"HIP作成に成功しました。\nHoudini: {version}\nLicense: {license_type}\nFormat: .{extension}",
        )

    def _sync_enabled(self) -> None:
        for row, installation in enumerate(self.working.installations):
            item = self.installation_table.item(row, 0)
            if item:
                installation.enabled = item.checkState().value == 2

    def _refresh_installations(self) -> None:
        self.installation_table.setRowCount(len(self.working.installations))
        for row, installation in enumerate(self.working.installations):
            enabled = QTableWidgetItem()
            enabled.setCheckState(
                Qt.CheckState.Checked if installation.enabled else Qt.CheckState.Unchecked
            )
            self.installation_table.setItem(row, 0, enabled)
            values = (
                installation.display_name,
                installation.version_string,
                str(installation.build),
                installation.license_type,
                str(installation.install_root),
                "Available" if installation.is_valid else "Missing",
                installation.source,
            )
            for column, value in enumerate(values, start=1):
                self.installation_table.setItem(row, column, QTableWidgetItem(value))
        current = self.working.default_installation_id
        self.default_installation.clear()
        self.default_installation.addItem("Auto-select newest", None)
        for installation in self.working.installations:
            self.default_installation.addItem(
                installation.display_name, installation.installation_id
            )
        index = self.default_installation.findData(current)
        self.default_installation.setCurrentIndex(max(0, index))
