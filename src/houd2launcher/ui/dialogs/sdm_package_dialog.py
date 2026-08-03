from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QLabel, QTreeWidget, QTreeWidgetItem, QVBoxLayout,
)

from ...core.cache_manager import CacheRecord, group_cache_records
from ...core.models import ProjectSettings


class SdmPackageDialog(QDialog):
    """Choose configured Houdini folders and individual Geo Cache Versions."""

    def __init__(self, project: ProjectSettings, records: list[CacheRecord], parent=None) -> None:
        super().__init__(parent)
        self.setWindowTitle("to SDM2.0")
        self.resize(620, 560)
        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("All HIP files are always included. Choose additional Houdini folders and Geo Cache Versions."))
        self.role_checks: dict[str, QCheckBox] = {}
        defaults = project.sdm_default_folder_roles
        default_roles = set(defaults if defaults is not None else [item.role for item in project.folders if item.enabled])
        for folder in project.folders:
            if not folder.enabled or folder.role == "geo_cache":
                continue
            checkbox = QCheckBox(f"{folder.display_name}  ({folder.relative_path})")
            checkbox.setChecked(folder.role in default_roles)
            self.role_checks[folder.role] = checkbox
            layout.addWidget(checkbox)
        layout.addWidget(QLabel("Geo Caches"))
        self.cache_tree = QTreeWidget()
        self.cache_tree.setHeaderLabels(["Cache / Version", "Size", "Used"])
        self.cache_tree.header().setStretchLastSection(False)
        self.cache_tree.itemChanged.connect(self._cache_check_changed)
        for group in group_cache_records(records):
            parent_item = QTreeWidgetItem([group.name, _size(group.size), "Used" if group.is_used else "Unused"])
            parent_item.setFlags(parent_item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            parent_item.setCheckState(0, Qt.CheckState.Checked)
            self.cache_tree.addTopLevelItem(parent_item)
            for record in group.versions:
                child = QTreeWidgetItem([f"v{record.version:03d}" if record.version is not None else "Unversioned", _size(record.size), "Used" if record.is_used else "Unused"])
                child.setFlags(child.flags() | Qt.ItemFlag.ItemIsUserCheckable)
                child.setCheckState(0, Qt.CheckState.Checked)
                child.setData(0, Qt.ItemDataRole.UserRole, record)
                parent_item.addChild(child)
            parent_item.setExpanded(True)
        layout.addWidget(self.cache_tree)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def selected_roles(self) -> list[str]:
        return [role for role, checkbox in self.role_checks.items() if checkbox.isChecked()]

    def _cache_check_changed(self, item: QTreeWidgetItem, column: int) -> None:
        if column != 0 or item.parent() is not None:
            return
        self.cache_tree.blockSignals(True)
        for index in range(item.childCount()):
            item.child(index).setCheckState(0, item.checkState(0))
        self.cache_tree.blockSignals(False)

    def selected_caches(self) -> list[CacheRecord]:
        result: list[CacheRecord] = []
        for row in range(self.cache_tree.topLevelItemCount()):
            parent = self.cache_tree.topLevelItem(row)
            for child_row in range(parent.childCount()):
                child = parent.child(child_row)
                if child.checkState(0) == Qt.CheckState.Checked:
                    result.append(child.data(0, Qt.ItemDataRole.UserRole))
        return result


def _size(value: int) -> str:
    size = float(value)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024 or unit == "TB":
            return f"{size:.1f} {unit}"
        size /= 1024
    return f"{size:.1f} TB"
