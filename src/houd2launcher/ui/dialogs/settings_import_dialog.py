from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.models import SettingsPackage
from ...settings.diff import Difference
from ...settings.importer import ImportIdentity


class SettingsImportDialog(QDialog):
    """Preview settings differences and select sections before import."""

    def __init__(
        self,
        package: SettingsPackage,
        differences: list[Difference],
        identity: ImportIdentity,
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.package = package
        self.setWindowTitle(f"Import {package.scope.title()} Settings")
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        status_text = {
            "exact": "Same ID: this package is an update for the selected target.",
            "name_match": (
                "Same name, different ID: verify the target carefully before updating."
            ),
            "mismatch": "Different target: settings will be imported as a template.",
            "legacy": "Legacy package: source identity is not available.",
        }[identity.status]
        project_context = ""
        if package.scope == "task":
            source_project = identity.source_project_name or "Unknown Project"
            project_context = (
                f"\nSource Project: {source_project} "
                f"({identity.source_project_id or 'No ID'})"
                f"\nTarget Project ID: {identity.target_project_id or 'No ID'}"
            )
        identity_label = QLabel(
            f"{status_text}\n"
            f"Source: {identity.source_name or 'Unknown'} "
            f"({identity.source_id or 'No ID'})\n"
            f"Target: {identity.target_name} ({identity.target_id})"
            f"{project_context}"
        )
        identity_label.setWordWrap(True)
        identity_label.setObjectName(f"settingsImportIdentity_{identity.status}")
        layout.addWidget(identity_label)
        self.mode = QComboBox()
        self.mode.addItem("Merge (keep existing keys)", "merge")
        self.mode.addItem("Merge and Overwrite", "overwrite")
        self.mode.addItem("Replace Section", "replace_section")
        if identity.is_update:
            self.mode.setCurrentIndex(self.mode.findData("replace_section"))
        layout.addWidget(self.mode)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["Apply", "Setting", "Current", "Incoming"])
        self.table.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)
        sections: dict[str, list[Difference]] = {}
        for difference in differences:
            sections.setdefault(difference.path.split(".", 1)[0], []).append(difference)
        for section, section_differences in sections.items():
            for difference in section_differences:
                row = self.table.rowCount()
                self.table.insertRow(row)
                check = QTableWidgetItem()
                check.setCheckState(Qt.CheckState.Checked)
                check.setData(Qt.ItemDataRole.UserRole, section)
                self.table.setItem(row, 0, check)
                self.table.setItem(row, 1, QTableWidgetItem(difference.path))
                self.table.setItem(row, 2, QTableWidgetItem(str(difference.current)))
                self.table.setItem(row, 3, QTableWidgetItem(str(difference.incoming)))
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Apply
        )
        apply_button = buttons.button(QDialogButtonBox.StandardButton.Apply)
        if apply_button is not None:
            apply_button.clicked.connect(self.accept)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_sections(self) -> set[str]:
        """Return sections represented by at least one checked difference."""
        return {
            str(self.table.item(row, 0).data(Qt.ItemDataRole.UserRole))
            for row in range(self.table.rowCount())
            if self.table.item(row, 0).checkState() == Qt.CheckState.Checked
        }
