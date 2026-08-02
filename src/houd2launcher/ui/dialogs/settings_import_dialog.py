from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.models import SettingsPackage
from ...settings.diff import Difference


class SettingsImportDialog(QDialog):
    """Preview settings differences and select sections before import."""

    def __init__(
        self,
        package: SettingsPackage,
        differences: list[Difference],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.package = package
        self.setWindowTitle(f"Import {package.scope.title()} Settings")
        self.resize(820, 520)
        layout = QVBoxLayout(self)
        self.mode = QComboBox()
        self.mode.addItem("Merge (keep existing keys)", "merge")
        self.mode.addItem("Merge and Overwrite", "overwrite")
        self.mode.addItem("Replace Section", "replace_section")
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

