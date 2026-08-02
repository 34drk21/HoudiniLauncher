from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QVBoxLayout,
    QWidget,
)

from ...core.task_package import TaskPackagePreview


class TaskPackageImportDialog(QDialog):
    """Read-only import preview shown after package integrity validation."""

    def __init__(self, preview: TaskPackagePreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Task Package")
        self.resize(660, 520)
        layout = QVBoxLayout(self)
        title = QLabel("Task Package Preview")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        form = QFormLayout()
        form.addRow("Source Project", QLabel(preview.manifest.source_project_name))
        form.addRow("Source Task", QLabel(preview.manifest.source_task_name))
        form.addRow("Target Task", QLabel(preview.target_task_name))
        form.addRow("Files", QLabel(str(len(preview.manifest.files))))
        form.addRow("Package Size", QLabel(_format_size(preview.total_size)))
        form.addRow(
            "Excluded Cache Roles",
            QLabel(", ".join(preview.manifest.excluded_roles) or "None"),
        )
        form.addRow("Task ID", QLabel("New ID" if preview.renamed else "Preserved"))
        layout.addLayout(form)

        differences = QLabel("Project Settings Differences")
        differences.setObjectName("ItemTitle")
        layout.addWidget(differences)
        self.difference_list = QListWidget()
        self.difference_list.addItems(
            list(preview.project_differences) or ["No portable setting differences"]
        )
        layout.addWidget(self.difference_list, 1)
        if preview.warnings:
            warning = QLabel("\n".join(preview.warnings))
            warning.setObjectName("WarningText")
            warning.setWordWrap(True)
            layout.addWidget(warning)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.button(QDialogButtonBox.StandardButton.Ok).setText("Import")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)


def _format_size(size: int) -> str:
    value = float(size)
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if value < 1024 or unit == "TB":
            return f"{value:.1f} {unit}"
        value /= 1024
    return f"{size} B"
