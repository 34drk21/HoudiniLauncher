from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMenu,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...core.package_exchange import PackageImportPreview, PublishedPackageRecord


class PackageExchangeDialog(QDialog):
    """Browse Project and Task snapshots in one shared folder."""

    path_changed = Signal(str)
    refresh_requested = Signal(str)
    import_requested = Signal(object)

    def __init__(self, exchange_path: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Project / Task Exchange")
        self.resize(980, 620)
        self._records: list[PublishedPackageRecord] = []
        layout = QVBoxLayout(self)

        title = QLabel("Project / Task Exchange")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)

        path_row = QHBoxLayout()
        self.path = QLineEdit(exchange_path)
        self.path.setPlaceholderText("Shared Package folder, for example Z:/houd2_exchange")
        self.path.editingFinished.connect(self._path_edited)
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._refresh)
        path_row.addWidget(self.path, 1)
        path_row.addWidget(browse)
        path_row.addWidget(refresh)
        layout.addLayout(path_row)

        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search Project, Task, publisher, or Package ID")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rebuild)
        self.kind = QComboBox()
        self.kind.addItems(["All", "Projects", "Tasks"])
        self.kind.currentIndexChanged.connect(self._rebuild)
        controls.addWidget(self.search, 1)
        controls.addWidget(self.kind)
        layout.addLayout(controls)

        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(
            ["Type", "Project", "Task", "Size", "Publisher", "Published", "Package ID"]
        )
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.table.customContextMenuRequested.connect(self._context_menu)
        self.table.doubleClicked.connect(lambda _index: self._import_current())
        self.table.horizontalHeader().setStretchLastSection(True)
        layout.addWidget(self.table, 1)

        self.summary = QLabel("0 Packages")
        self.summary.setObjectName("SecondaryText")
        layout.addWidget(self.summary)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def set_records(self, records: tuple[PublishedPackageRecord, ...]) -> None:
        self._records = list(records)
        self._rebuild()

    def _rebuild(self) -> None:
        search = self.search.text().strip().casefold()
        kind = self.kind.currentText()
        visible: list[PublishedPackageRecord] = []
        for record in self._records:
            manifest = record.manifest
            if kind == "Projects" and manifest.package_kind != "project":
                continue
            if kind == "Tasks" and manifest.package_kind != "task":
                continue
            haystack = " ".join(
                (
                    manifest.source_project_name,
                    manifest.source_task_name or "",
                    manifest.publisher_name,
                    manifest.package_id,
                )
            ).casefold()
            if search and search not in haystack:
                continue
            visible.append(record)

        self.table.setRowCount(len(visible))
        for row, record in enumerate(visible):
            manifest = record.manifest
            values = (
                manifest.package_kind.title(),
                manifest.source_project_name,
                manifest.source_task_name or "-",
                _format_size(record.total_size),
                manifest.publisher_name or manifest.publisher_user_id or "-",
                manifest.published_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                manifest.package_id,
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record)
                self.table.setItem(row, column, item)
        self.table.resizeColumnsToContents()
        self.summary.setText(f"{len(visible)} Packages")

    def _current_record(self) -> PublishedPackageRecord | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def _context_menu(self, position: object) -> None:
        record = self._current_record()
        if record is None:
            return
        menu = QMenu(self)
        label = f"Import this {record.manifest.package_kind.title()}"
        menu.addAction(label, self._import_current)
        menu.exec(self.table.mapToGlobal(position))

    def _import_current(self) -> None:
        record = self._current_record()
        if record is not None:
            self.import_requested.emit(record)

    def _path_edited(self) -> None:
        value = self.path.text().strip()
        self.path_changed.emit(value)
        self.refresh_requested.emit(value)

    def _refresh(self) -> None:
        self.refresh_requested.emit(self.path.text().strip())

    def _browse(self) -> None:
        value = QFileDialog.getExistingDirectory(
            self, "Select Package Exchange Folder", self.path.text().strip()
        )
        if value:
            self.path.setText(value)
            self.path_changed.emit(value)
            self.refresh_requested.emit(value)


class PackageImportPreviewDialog(QDialog):
    """Confirm a checksum-verified Package import without overwrite."""

    def __init__(self, preview: PackageImportPreview, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Import Exchange Package")
        self.resize(620, 360)
        layout = QVBoxLayout(self)
        title = QLabel("Package Import Preview")
        title.setObjectName("DialogTitle")
        layout.addWidget(title)
        form = QFormLayout()
        manifest = preview.published.manifest
        form.addRow("Type", QLabel(manifest.package_kind.title()))
        form.addRow("Source Project", QLabel(manifest.source_project_name))
        if manifest.source_task_name:
            form.addRow("Source Task", QLabel(manifest.source_task_name))
        form.addRow("Target Name", QLabel(preview.target_name))
        form.addRow("Target Folder", QLabel(str(preview.target_root)))
        form.addRow("Files", QLabel(str(preview.file_count)))
        form.addRow("Package Size", QLabel(_format_size(preview.total_size)))
        form.addRow("Identity", QLabel("New Copy ID" if preview.renamed else "Preserved"))
        form.addRow(
            "Excluded Cache Roles",
            QLabel(", ".join(manifest.excluded_roles) or "None"),
        )
        layout.addLayout(form)
        note = QLabel(
            "Existing Projects and Tasks are never overwritten. Published files remain in the Exchange folder."
        )
        note.setWordWrap(True)
        note.setObjectName("SecondaryText")
        layout.addWidget(note)
        layout.addStretch()
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
