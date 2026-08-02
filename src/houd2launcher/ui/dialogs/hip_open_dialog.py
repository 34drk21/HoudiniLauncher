from __future__ import annotations

from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QRadioButton,
    QVBoxLayout,
    QWidget,
)

from ...core.hip_manager import HipRecord
from ...core.models import HoudiniInstallation
from ...houdini.compatibility import assess_compatibility
from ..widgets import add_helped_row


class HipOpenDialog(QDialog):
    """Select a Houdini build, mode, and preference persistence for HIP open."""

    def __init__(
        self,
        hip: HipRecord,
        installations: list[HoudiniInstallation],
        recommended: HoudiniInstallation | None,
        read_only: bool = False,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.hip = hip
        self.installations = installations
        self.setWindowTitle("Open HIP")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.addRow("HIP", QLabel(hip.path.name))
        saved = next(
            (
                item
                for item in installations
                if item.installation_id == hip.metadata.last_saved_with
            ),
            None,
        )
        form.addRow("Detected HIP Version", QLabel(saved.display_name if saved else "Unknown"))
        form.addRow("Recommended", QLabel(recommended.display_name if recommended else "Auto"))
        self.open_with = QComboBox()
        for installation in installations:
            self.open_with.addItem(installation.display_name, installation)
        if recommended:
            index = next(
                (
                    index
                    for index, item in enumerate(installations)
                    if item.installation_id == recommended.installation_id
                ),
                0,
            )
            self.open_with.setCurrentIndex(index)
        self.open_with.currentIndexChanged.connect(self._update_warning)
        form.addRow("Open With", self.open_with)
        mode = QWidget()
        mode_layout = QVBoxLayout(mode)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        self.normal = QRadioButton("Normal")
        self.read_only = QRadioButton("Read Only")
        (self.read_only if read_only else self.normal).setChecked(True)
        mode_layout.addWidget(self.normal)
        mode_layout.addWidget(self.read_only)
        form.addRow("Mode", mode)
        self.remember_hip = QCheckBox("Remember for this HIP")
        self.remember_task = QCheckBox("Remember for this Task")
        self.set_project_default = QCheckBox("Set as Project Default")
        self.set_launcher_default = QCheckBox("Set as Launcher Default")
        form.addRow("", self.remember_hip)
        form.addRow("", self.remember_task)
        form.addRow("", self.set_project_default)
        form.addRow("", self.set_launcher_default)
        layout.addLayout(form)
        self.warning = QLabel()
        self.warning.setWordWrap(True)
        self.warning.setObjectName("CompatibilityWarning")
        layout.addWidget(self.warning)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Open
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_warning()

    def selected_installation(self) -> HoudiniInstallation:
        """Return the build selected in the dialog."""
        return self.open_with.currentData()

    def _update_warning(self) -> None:
        selected = self.open_with.currentData()
        saved = next(
            (
                item
                for item in self.installations
                if item.installation_id == self.hip.metadata.last_saved_with
            ),
            None,
        )
        if selected:
            result = assess_compatibility(saved, selected)
            self.warning.setText(f"{result.severity.replace('_', ' ').title()}: {result.message}")


class NewHipDialog(QDialog):
    """Select a Houdini installation and comment for blank HIP creation."""

    def __init__(
        self,
        installations: list[HoudiniInstallation],
        recommended: HoudiniInstallation | None,
        preview_provider: Callable[[HoudiniInstallation], tuple[str, str]] | None = None,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle("New HIP")
        self.setMinimumWidth(560)
        self.preview_provider = preview_provider
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.installation = QComboBox()
        for item in installations:
            self.installation.addItem(item.display_name, item)
        if recommended:
            index = next(
                (
                    index
                    for index, item in enumerate(installations)
                    if item.installation_id == recommended.installation_id
                ),
                0,
            )
            self.installation.setCurrentIndex(index)
        self.comment = QLineEdit()
        self.comment.setPlaceholderText("例: Initial setup / smoke timing update")
        add_helped_row(form, "Create with", self.installation, "HIPを生成するhythonとライセンスを選択します。")
        add_helped_row(form, "Comment", self.comment, "作成理由や作業内容をHIP履歴へ記録します。")
        layout.addLayout(form)
        self.details = QLabel()
        self.details.setObjectName("FieldHelp")
        self.details.setWordWrap(True)
        layout.addWidget(self.details)
        self.installation.currentIndexChanged.connect(self._update_details)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._update_details()

    def _update_details(self) -> None:
        installation = self.installation.currentData()
        if installation is None:
            self.details.clear()
            return
        license_type = installation.license_type or "Unknown"
        extension = "自動判定"
        path = "作成時に決定"
        if self.preview_provider:
            extension, path = self.preview_provider(installation)
        self.details.setText(
            f"ライセンス: {license_type}\n保存形式: .{extension}\n保存予定: {path}"
        )
