from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QComboBox,
    QCheckBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QMenu,
    QScrollArea,
    QStyle,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTreeWidget,
    QTreeWidgetItem,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.hip_manager import HipRecord
from ...core.cache_manager import CacheGroup, CacheRecord, CacheScanResult, group_cache_records
from ...core.cache_exchange import PublishedCacheRecord
from ...core.models import ProjectSettings, TaskSettings
from ...core.path_resolver import PathResolver
from ..widgets import ElideLabel


class TaskDetailsPanel(QWidget):
    """Right-side task overview, HIP table, settings summary, and history."""

    open_requested = Signal(object, bool)
    version_up_requested = Signal(object)
    new_hip_requested = Signal()
    task_settings_requested = Signal()
    thumbnail_requested = Signal()
    reveal_hip_requested = Signal(object)
    copy_path_requested = Signal(object)
    cache_scan_requested = Signal(object)
    cache_delete_requested = Signal(object)
    reveal_cache_requested = Signal(object)
    cache_publish_requested = Signal(object, str)
    cache_import_requested = Signal(object, str, bool)
    exchange_path_changed = Signal(str)
    published_refresh_requested = Signal()

    def __init__(self, resolver: PathResolver, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(420)
        self.resolver = resolver
        self.project: ProjectSettings | None = None
        self.task: TaskSettings | None = None
        self.hips: list[HipRecord] = []
        self.cache_records: list[CacheRecord] = []
        self.published_records: list[PublishedCacheRecord] = []
        self._cache_hip: Path | None = None
        self._cache_loading = False
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        title = QLabel("Task Details")
        title.setObjectName("PanelTitle")
        layout.addWidget(title)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self._build_overview()
        self._build_hips()
        self._build_caches()
        self._build_imports()
        self._build_settings()
        self._build_history()
        self.tabs.currentChanged.connect(self._tab_changed)

    def _build_overview(self) -> None:
        page = QWidget()
        page_layout = QVBoxLayout(page)
        page_layout.setContentsMargins(0, 0, 0, 0)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        content = QWidget()
        layout = QVBoxLayout(content)
        self.thumbnail = QLabel("No thumbnail")
        self.thumbnail.setObjectName("TaskThumbnail")
        self.thumbnail.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.thumbnail.setMinimumHeight(190)
        self.thumbnail.mouseDoubleClickEvent = lambda event: self.thumbnail_requested.emit()
        layout.addWidget(self.thumbnail)
        form = QFormLayout()
        self.overview_labels: dict[str, QLabel] = {}
        for key, label in (
            ("name", "Task"),
            ("description", "Description"),
            ("status", "Status"),
            ("owner", "Owner"),
            ("modified", "Last Modified"),
            ("latest", "Latest HIP"),
            ("user", "Latest User"),
            ("frames", "Frame Range"),
            ("fps", "FPS"),
            ("houdini", "Recommended Houdini"),
        ):
            value = QLabel("-")
            value.setWordWrap(True)
            self.overview_labels[key] = value
            form.addRow(label, value)
        layout.addLayout(form)
        environment_title = QLabel("Expression Environment")
        environment_title.setObjectName("ItemTitle")
        layout.addWidget(environment_title)
        self.expression_table = QTableWidget(0, 2)
        self.expression_table.setHorizontalHeaderLabels(["Variable", "Value"])
        self.expression_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.expression_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.expression_table.setWordWrap(False)
        self.expression_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.expression_table.verticalHeader().setVisible(False)
        self.expression_table.verticalHeader().setDefaultSectionSize(32)
        self.expression_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents
        )
        self.expression_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.expression_table.setMinimumHeight(190)
        layout.addWidget(self.expression_table)
        layout.addStretch()
        scroll.setWidget(content)
        page_layout.addWidget(scroll)
        self.tabs.addTab(page, "Overview")

    def _build_hips(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        buttons = QHBoxLayout()
        for text, icon, callback in (
            ("New HIP", QStyle.StandardPixmap.SP_FileDialogNewFolder, lambda: self.new_hip_requested.emit()),
            ("Open HIP", QStyle.StandardPixmap.SP_MediaPlay, lambda: self._emit_open(False)),
            ("Open Read Only", QStyle.StandardPixmap.SP_DialogOpenButton, lambda: self._emit_open(True)),
            ("Version Up", QStyle.StandardPixmap.SP_ArrowUp, self._emit_version_up),
        ):
            button = QToolButton()
            button.setIcon(self.style().standardIcon(icon))
            button.setToolTip(text)
            button.setAccessibleName(text)
            button.clicked.connect(callback)
            buttons.addWidget(button)
        buttons.addStretch()
        layout.addLayout(buttons)
        self.hip_table = QTableWidget(0, 8)
        self.hip_table.setHorizontalHeaderLabels(
            ["Version", "File", "User", "Saved", "Comment", "Houdini", "Size", "Exists"]
        )
        self.hip_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.hip_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        self.hip_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.hip_table.setWordWrap(False)
        self.hip_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.hip_table.verticalHeader().setVisible(False)
        self.hip_table.verticalHeader().setDefaultSectionSize(34)
        self.hip_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.hip_table.customContextMenuRequested.connect(self._hip_context_menu)
        self.hip_table.itemSelectionChanged.connect(self._selected_hip_changed)
        self.hip_table.doubleClicked.connect(lambda: self._emit_open(False))
        self.hip_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        for column in (0, 2, 6, 7):
            self.hip_table.horizontalHeader().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        layout.addWidget(self.hip_table)
        self.tabs.addTab(page, "HIP")

    def _build_caches(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        path_row = QHBoxLayout()
        self.exchange_path = QLineEdit()
        self.exchange_path.setPlaceholderText("Published Cache folder, for example Z:/houd2_exchange")
        self.exchange_path.editingFinished.connect(self._exchange_path_edited)
        browse = QToolButton()
        browse.setText("...")
        browse.setToolTip("Choose Published Cache Folder")
        browse.clicked.connect(self._browse_exchange_path)
        path_row.addWidget(QLabel("Publish / Import Path"))
        path_row.addWidget(self.exchange_path, 1)
        path_row.addWidget(browse)
        layout.addLayout(path_row)
        header = QHBoxLayout()
        self.cache_hip_label = ElideLabel("Select a HIP version")
        self.cache_hip_label.setObjectName("SecondaryText")
        header.addWidget(self.cache_hip_label, 1)
        self.cache_refresh = QToolButton()
        self.cache_refresh.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload)
        )
        self.cache_refresh.setToolTip("Scan selected HIP caches")
        self.cache_refresh.clicked.connect(lambda: self._request_cache_scan(True))
        header.addWidget(self.cache_refresh)
        self.cache_delete = QToolButton()
        self.cache_delete.setIcon(
            self.style().standardIcon(QStyle.StandardPixmap.SP_TrashIcon)
        )
        self.cache_delete.setToolTip("Delete selected cache versions permanently")
        self.cache_delete.setEnabled(False)
        self.cache_delete.clicked.connect(self._emit_cache_delete)
        header.addWidget(self.cache_delete)
        layout.addLayout(header)

        filters = QHBoxLayout()
        self.cache_search = QLineEdit()
        self.cache_search.setPlaceholderText("Search cache, node, version, or path")
        self.cache_search.setClearButtonEnabled(True)
        self.cache_search.textChanged.connect(self._rebuild_cache_table)
        filters.addWidget(self.cache_search, 1)
        self.cache_status = QComboBox()
        self.cache_status.addItems(["All", "Used", "Unused", "Missing"])
        self.cache_status.currentIndexChanged.connect(self._rebuild_cache_table)
        filters.addWidget(self.cache_status)
        self.cache_sort = QComboBox()
        self.cache_sort.addItems(
            ["Used first", "Size: Heavy first", "Name", "Version", "Modified"]
        )
        self.cache_sort.currentIndexChanged.connect(self._rebuild_cache_table)
        filters.addWidget(self.cache_sort)
        layout.addLayout(filters)

        self.cache_summary = QLabel("Open this tab to scan the selected HIP.")
        self.cache_summary.setObjectName("FieldHelp")
        self.cache_summary.setWordWrap(True)
        layout.addWidget(self.cache_summary)
        self.cache_table = QTreeWidget()
        self.cache_table.setColumnCount(8)
        self.cache_table.setHeaderLabels(
            ["Status", "Cache / Version", "Versions", "Type", "Size", "Files", "Node", "Path"]
        )
        self.cache_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.cache_table.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.cache_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.cache_table.setWordWrap(False)
        self.cache_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.cache_table.setIndentation(20)
        self.cache_table.header().setSectionResizeMode(
            1, QHeaderView.ResizeMode.Stretch
        )
        self.cache_table.header().setSectionResizeMode(
            7, QHeaderView.ResizeMode.Stretch
        )
        for column in (0, 2, 3, 4, 5):
            self.cache_table.header().setSectionResizeMode(
                column, QHeaderView.ResizeMode.ResizeToContents
            )
        self.cache_table.itemSelectionChanged.connect(self._cache_selection_changed)
        self.cache_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.cache_table.customContextMenuRequested.connect(self._cache_context_menu)
        layout.addWidget(self.cache_table)
        self.cache_tab_index = self.tabs.addTab(page, "Caches")

    def _build_imports(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        path_row = QHBoxLayout()
        self.import_exchange_path = QLineEdit()
        self.import_exchange_path.setPlaceholderText("Published Cache folder")
        self.import_exchange_path.editingFinished.connect(self._import_path_edited)
        browse = QToolButton()
        browse.setText("...")
        browse.clicked.connect(self._browse_exchange_path)
        refresh = QToolButton()
        refresh.setIcon(self.style().standardIcon(QStyle.StandardPixmap.SP_BrowserReload))
        refresh.setToolTip("Refresh Published Caches")
        refresh.clicked.connect(lambda: self.published_refresh_requested.emit())
        path_row.addWidget(QLabel("Publish / Import Path"))
        path_row.addWidget(self.import_exchange_path, 1)
        path_row.addWidget(browse)
        path_row.addWidget(refresh)
        layout.addLayout(path_row)
        filters = QHBoxLayout()
        self.import_search = QLineEdit()
        self.import_search.setPlaceholderText("Search project, task, cache, version, or creator")
        self.import_search.setClearButtonEnabled(True)
        self.import_search.textChanged.connect(self._rebuild_import_table)
        self.import_delete_source = QCheckBox("Delete published copy after successful import")
        self.import_delete_source.setChecked(True)
        filters.addWidget(self.import_search, 1)
        filters.addWidget(self.import_delete_source)
        layout.addLayout(filters)
        self.import_summary = QLabel("Set a Publish / Import Path to browse shared Caches.")
        self.import_summary.setObjectName("FieldHelp")
        layout.addWidget(self.import_summary)
        self.import_table = QTableWidget(0, 7)
        self.import_table.setHorizontalHeaderLabels(["Cache", "Version", "Project", "Task", "Creator", "Size", "Published"])
        self.import_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.import_table.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.import_table.customContextMenuRequested.connect(self._import_context_menu)
        self.import_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column in range(1, 7):
            self.import_table.horizontalHeader().setSectionResizeMode(column, QHeaderView.ResizeMode.ResizeToContents)
        self.import_table.setSortingEnabled(True)
        layout.addWidget(self.import_table)
        self.import_tab_index = self.tabs.addTab(page, "Import")

    def _build_settings(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.settings_summary = QLabel("Select a task")
        self.settings_summary.setWordWrap(True)
        layout.addWidget(self.settings_summary)
        edit = QPushButton("Open Task Settings")
        edit.clicked.connect(self.task_settings_requested)
        layout.addWidget(edit)
        layout.addStretch()
        self.tabs.addTab(page, "Settings")

    def _build_history(self) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        self.history_table = QTableWidget(0, 3)
        self.history_table.setHorizontalHeaderLabels(["Time", "Event", "Details"])
        self.history_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        self.history_table.setWordWrap(False)
        self.history_table.setTextElideMode(Qt.TextElideMode.ElideRight)
        self.history_table.verticalHeader().setVisible(False)
        self.history_table.verticalHeader().setDefaultSectionSize(34)
        self.history_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch
        )
        layout.addWidget(self.history_table)
        self.tabs.addTab(page, "History")

    def set_task(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        hips: list[HipRecord],
        history: list[dict[str, object]],
        expression_environment: dict[str, str] | None = None,
    ) -> None:
        """Populate every detail tab for the selected task."""
        self.project = project
        self.task = task
        self.hips = hips
        self.cache_records = []
        self._cache_hip = None
        self._cache_loading = False
        latest = hips[0] if hips else None
        values = {
            "name": task.name,
            "description": task.description or "-",
            "status": task.status.replace("_", " ").title(),
            "owner": task.owner or "-",
            "modified": task.modified_at.astimezone().strftime("%Y-%m-%d %H:%M"),
            "latest": latest.path.name if latest else "-",
            "user": latest.user if latest else "-",
            "frames": f"{task.frames.start} - {task.frames.end}",
            "fps": f"{task.frames.fps:g}",
            "houdini": task.recommended_installation_id or "Project default",
        }
        for key, value in values.items():
            self.overview_labels[key].setText(value)
        self._load_thumbnail()
        self._load_hips()
        self._rebuild_cache_table()
        self.settings_summary.setText(
            f"Frame: {task.frames.start} - {task.frames.end}\n"
            f"Simulation start: {task.frames.sim_start}\n"
            f"FPS: {task.frames.fps:g}\n\n"
            f"Environment variables: {len(task.environment)}\n"
            f"Houdini override: {task.recommended_installation_id or 'Project default'}"
        )
        self._load_history(history)
        self._load_expression_environment(expression_environment or {})

    def set_exchange_path(self, value: str) -> None:
        self.exchange_path.setText(value)
        self.import_exchange_path.setText(value)

    def set_published_records(self, records: tuple[PublishedCacheRecord, ...]) -> None:
        self.published_records = list(records)
        self._rebuild_import_table()

    def open_import_tab(self, cache_id: str = "") -> None:
        self.tabs.setCurrentIndex(self.import_tab_index)
        self._rebuild_import_table()
        for index in range(self.import_table.rowCount()):
            item = self.import_table.item(index, 0)
            record = item.data(Qt.ItemDataRole.UserRole)
            if record and record.manifest.cache_id == cache_id:
                self.import_table.selectRow(index)
                self.import_table.scrollToItem(item)
                break

    def clear_task(self) -> None:
        """Clear stale details after the final Task in a Project is removed."""
        self.project = None
        self.task = None
        self.hips = []
        self.cache_records = []
        self._cache_hip = None
        self._cache_loading = False
        for label in self.overview_labels.values():
            label.setText("-")
        self.thumbnail.setPixmap(QPixmap())
        self.thumbnail.setText("No task selected")
        self.expression_table.setRowCount(0)
        self.hip_table.setRowCount(0)
        self.cache_table.clear()
        self.cache_hip_label.setText("Select a HIP version")
        self.cache_summary.setText("Select a Task and HIP to scan caches.")
        self.settings_summary.setText("Select a task")
        self.history_table.setRowCount(0)

    def _load_expression_environment(self, environment: dict[str, str]) -> None:
        self.expression_table.setRowCount(len(environment))
        for row, (name, value) in enumerate(sorted(environment.items())):
            name_item = QTableWidgetItem(name)
            value_item = QTableWidgetItem(value)
            name_item.setToolTip(name)
            value_item.setToolTip(value)
            self.expression_table.setItem(row, 0, name_item)
            self.expression_table.setItem(row, 1, value_item)

    def selected_hip(self) -> HipRecord | None:
        """Return the selected HIP row or latest HIP when no row is selected."""
        row = self.hip_table.currentRow()
        if row < 0 and self.hips:
            return self.hips[0]
        return self.hips[row] if 0 <= row < len(self.hips) else None

    def _load_thumbnail(self) -> None:
        if not self.project or not self.task:
            return
        path = next(
            (
                self.resolver.resolve_thumbnail_path(
                    self.project, self.task, extension=extension
                )
                for extension in ("jpg", "jpeg", "png")
                if self.resolver.resolve_thumbnail_path(
                    self.project, self.task, extension=extension
                ).is_file()
            ),
            None,
        )
        if path:
            pixmap = QPixmap(str(path)).scaled(
                520,
                260,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.thumbnail.setPixmap(pixmap)
        else:
            self.thumbnail.setPixmap(QPixmap())
            self.thumbnail.setText("Double-click to set thumbnail")

    def _load_hips(self) -> None:
        self.hip_table.setRowCount(len(self.hips))
        for row, hip in enumerate(self.hips):
            values = (
                f"v{hip.version:03d}",
                hip.path.name,
                hip.user,
                hip.modified_at.astimezone().strftime("%Y-%m-%d %H:%M"),
                hip.metadata.comment,
                hip.metadata.last_saved_with or "Unknown",
                self._format_size(hip.size),
                "Yes" if hip.path.is_file() else "Missing",
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(str(value))
                item.setToolTip(str(value))
                self.hip_table.setItem(row, column, item)
        if self.hips:
            self.hip_table.selectRow(0)

    def _load_history(self, history: list[dict[str, object]]) -> None:
        self.history_table.setRowCount(len(history))
        for row, event in enumerate(history):
            values = (
                str(event.get("created_at", ""))[:19].replace("T", " "),
                str(event.get("event_type", "")),
                self._details_text(event.get("details", "")),
            )
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setToolTip(value)
                self.history_table.setItem(row, column, item)

    def _hip_context_menu(self, position: object) -> None:
        if self.selected_hip() is None:
            return
        menu = QMenu(self)
        for label, callback in (
            ("Open", lambda: self._emit_open(False)),
            ("Open Read Only", lambda: self._emit_open(True)),
            ("Version Up", self._emit_version_up),
            ("Open in Explorer", self._emit_reveal),
            ("Copy Path", self._emit_copy),
        ):
            menu.addAction(label, callback)
        menu.exec(self.hip_table.mapToGlobal(position))

    def set_cache_loading(self, hip: HipRecord) -> None:
        """Show that the selected HIP is being inspected by hython."""
        self._cache_loading = True
        self.cache_refresh.setEnabled(False)
        self.cache_hip_label.setText(hip.path.name)
        self.cache_summary.setText("Scanning HIP file references and cache sizes...")

    def set_cache_result(self, result: CacheScanResult) -> None:
        """Display a completed cache inventory for the selected HIP."""
        selected = self.selected_hip()
        if selected is None or selected.path != result.hip_path:
            self._cache_loading = False
            self.cache_refresh.setEnabled(True)
            if selected:
                self._request_cache_scan(True)
            return
        self._cache_loading = False
        self.cache_refresh.setEnabled(True)
        self._cache_hip = result.hip_path
        self.cache_records = list(result.records)
        used = sum(record.is_used for record in self.cache_records)
        total = sum(record.size for record in self.cache_records)
        groups = group_cache_records(self.cache_records)
        self.cache_summary.setText(
            f"{len(groups)} caches  {len(self.cache_records)} versions  "
            f"Used: {used}  Total: {self._format_size(total)}"
        )
        self._rebuild_cache_table()

    def set_cache_error(self, message: str) -> None:
        """Restore controls after a failed cache scan."""
        self._cache_loading = False
        self.cache_refresh.setEnabled(True)
        self.cache_summary.setText(message)

    def _tab_changed(self, index: int) -> None:
        if index == self.cache_tab_index:
            self._request_cache_scan(False)

    def _selected_hip_changed(self) -> None:
        hip = self.selected_hip()
        self.cache_hip_label.setText(hip.path.name if hip else "Select a HIP version")
        if self.tabs.currentIndex() == self.cache_tab_index:
            self._request_cache_scan(False)

    def _request_cache_scan(self, force: bool) -> None:
        hip = self.selected_hip()
        if hip is None or self._cache_loading:
            return
        if force or self._cache_hip != hip.path:
            self.cache_scan_requested.emit(hip)

    def _rebuild_cache_table(self) -> None:
        search = self.cache_search.text().strip().casefold() if hasattr(self, "cache_search") else ""
        status = self.cache_status.currentText() if hasattr(self, "cache_status") else "All"
        groups: list[tuple[CacheGroup, list[CacheRecord]]] = []
        for group in group_cache_records(self.cache_records):
            parent_matches = search in f"{group.name} {group.path}".casefold()
            children = []
            for record in group.versions:
                searchable = " ".join(
                    (
                        record.name,
                        str(record.version or ""),
                        f"v{record.version:03d}" if record.version is not None else "unversioned",
                        record.kind,
                        str(record.path),
                        " ".join(record.node_paths),
                    )
                ).casefold()
                if search and not parent_matches and search not in searchable:
                    continue
                if status == "Used" and not (record.is_used and record.exists):
                    continue
                if status == "Unused" and not (not record.is_used and record.exists):
                    continue
                if status == "Missing" and record.exists:
                    continue
                children.append(record)
            if children:
                groups.append((group, children))
        sort_name = self.cache_sort.currentText() if hasattr(self, "cache_sort") else "Used first"
        if sort_name == "Size: Heavy first":
            groups.sort(key=lambda item: item[0].size, reverse=True)
        elif sort_name == "Name":
            groups.sort(key=lambda item: item[0].name.casefold())
        elif sort_name == "Version":
            groups.sort(key=lambda item: max((child.version or -1 for child in item[1])), reverse=True)
        elif sort_name == "Modified":
            groups.sort(key=lambda item: item[0].modified_at or datetime.min.astimezone(), reverse=True)
        else:
            groups.sort(key=lambda item: (not item[0].is_used, -item[0].size))
        self.cache_table.clear()
        published_keys = {
            (item.manifest.cache_name.casefold(), item.manifest.version)
            for item in self.published_records
            if self.project and self.task
            and item.manifest.project_id == self.project.project_id
            and item.manifest.task_id == self.task.task_id
        }
        for group, children in groups:
            group_published = any(
                (group.name.casefold(), child.version) in published_keys for child in group.versions
            )
            parent_values = (
                ("USED" if group.is_used else "UNUSED") + (" / PUBLISHED" if group_published else ""),
                group.name,
                f"{len(group.versions)} versions",
                ", ".join(sorted({item.kind for item in group.versions})),
                self._format_size(group.size),
                str(group.file_count),
                ", ".join(sorted({node for item in group.versions for node in item.node_paths})) or "-",
                str(group.path),
            )
            parent = QTreeWidgetItem(list(parent_values))
            parent.setData(0, Qt.ItemDataRole.UserRole, group)
            self._color_cache_item(parent, group.is_used)
            self.cache_table.addTopLevelItem(parent)
            if sort_name == "Size: Heavy first":
                children.sort(key=lambda item: item.size, reverse=True)
            else:
                children.sort(key=lambda item: item.version or -1)
            for record in children:
                state = "USED" if record.is_used else "UNUSED"
                if (record.name.casefold(), record.version) in published_keys:
                    state += " / PUBLISHED"
                if not record.exists:
                    state += " / MISSING"
                values = (
                    state,
                    f"v{record.version:03d}" if record.version is not None else "Unversioned",
                    "-",
                    record.kind,
                    self._format_size(record.size),
                    str(record.file_count),
                    ", ".join(record.node_paths) or "-",
                    str(record.path),
                )
                child = QTreeWidgetItem(parent, list(values))
                child.setData(0, Qt.ItemDataRole.UserRole, record)
                self._color_cache_item(child, record.is_used)
            parent.setExpanded(True)
        self._cache_selection_changed()

    @staticmethod
    def _color_cache_item(item: QTreeWidgetItem, is_used: bool) -> None:
        color = QColor("#78cf8e" if is_used else "#e27676")
        for column in range(item.columnCount()):
            item.setForeground(column, color)
            item.setToolTip(column, item.text(column))

    def _selected_cache_records(self) -> list[CacheRecord]:
        selected: list[CacheRecord] = []
        for item in self.cache_table.selectedItems():
            value = item.data(0, Qt.ItemDataRole.UserRole)
            selected.extend(value.versions if isinstance(value, CacheGroup) else [value])
        return list({record.path: record for record in selected if isinstance(record, CacheRecord)}.values())

    def _cache_selection_changed(self) -> None:
        records = self._selected_cache_records()
        self.cache_delete.setEnabled(
            bool(records) and all(record.managed and record.exists for record in records)
        )

    def _emit_cache_delete(self) -> None:
        records = self._selected_cache_records()
        if records:
            self.cache_delete_requested.emit(records)

    def _cache_context_menu(self, position: object) -> None:
        records = self._selected_cache_records()
        if not records:
            return
        menu = QMenu(self)
        publish = menu.addAction("Publish this Cache", lambda: self.cache_publish_requested.emit(records, self.exchange_path.text().strip()))
        publish.setEnabled(bool(self.exchange_path.text().strip()))
        menu.addSeparator()
        delete = menu.addAction("Delete Permanently", self._emit_cache_delete)
        delete.setEnabled(all(record.managed and record.exists for record in records))
        menu.addAction(
            "Open in Explorer", lambda: self.reveal_cache_requested.emit(records[0])
        )
        menu.addAction(
            "Copy Path", lambda: QApplication.clipboard().setText(str(records[0].path))
        )
        menu.exec(self.cache_table.mapToGlobal(position))

    def _exchange_path_edited(self) -> None:
        value = self.exchange_path.text().strip()
        self.import_exchange_path.setText(value)
        self.exchange_path_changed.emit(value)

    def _import_path_edited(self) -> None:
        value = self.import_exchange_path.text().strip()
        self.exchange_path.setText(value)
        self.exchange_path_changed.emit(value)

    def _browse_exchange_path(self) -> None:
        current = self.exchange_path.text().strip() or self.import_exchange_path.text().strip()
        value = QFileDialog.getExistingDirectory(self, "Choose Published Cache Folder", current)
        if value:
            self.exchange_path.setText(value)
            self.import_exchange_path.setText(value)
            self.exchange_path_changed.emit(value)

    def _rebuild_import_table(self) -> None:
        if not hasattr(self, "import_table"):
            return
        search = self.import_search.text().strip().casefold()
        self.import_table.setSortingEnabled(False)
        self.import_table.clearContents()
        self.import_table.setRowCount(0)
        visible = 0
        for record in self.published_records:
            manifest = record.manifest
            haystack = " ".join((manifest.project_name, manifest.task_name, manifest.cache_name,
                                 str(manifest.version), str(manifest.source_manifest.get("creator", "")))).casefold()
            if search and search not in haystack:
                continue
            creator = manifest.source_manifest.get("creator", {})
            creator_name = str(creator.get("display_name", creator.get("user_id", "Unknown"))) if isinstance(creator, dict) else "Unknown"
            size = sum(item.size for item in manifest.files)
            row = self.import_table.rowCount()
            self.import_table.insertRow(row)
            for column, value in enumerate((
                manifest.cache_name, f"v{manifest.version:03d}", manifest.project_name,
                manifest.task_name, creator_name, self._format_size(size), manifest.published_at[:19],
            )):
                item = QTableWidgetItem(value)
                if column == 0:
                    item.setData(Qt.ItemDataRole.UserRole, record)
                self.import_table.setItem(row, column, item)
            visible += 1
        self.import_summary.setText(f"{visible} published Cache Versions")
        self.import_table.setSortingEnabled(True)

    def _import_context_menu(self, position: object) -> None:
        item = self.import_table.itemAt(position)
        if item is None:
            return
        self.import_table.setCurrentItem(item)
        self.import_table.selectRow(item.row())
        record = self.import_table.item(item.row(), 0).data(Qt.ItemDataRole.UserRole)
        menu = QMenu(self)
        action = menu.addAction(
            "Import this Cache",
            lambda: self.cache_import_requested.emit(
                record, self.import_exchange_path.text().strip(), self.import_delete_source.isChecked()
            ),
        )
        action.setEnabled(self.project is not None and self.task is not None)
        menu.exec(self.import_table.mapToGlobal(position))

    @staticmethod
    def _details_text(value: object) -> str:
        try:
            parsed = json.loads(str(value))
            return ", ".join(f"{key}: {item}" for key, item in parsed.items())
        except (json.JSONDecodeError, AttributeError):
            return str(value)

    @staticmethod
    def _format_size(size: int) -> str:
        value = float(size)
        for unit in ("B", "KB", "MB", "GB"):
            if value < 1024 or unit == "GB":
                return f"{value:.1f} {unit}"
            value /= 1024
        return f"{value:.1f} GB"

    def _emit_open(self, read_only: bool) -> None:
        hip = self.selected_hip()
        if hip:
            self.open_requested.emit(hip, read_only)

    def _emit_version_up(self) -> None:
        hip = self.selected_hip()
        if hip:
            self.version_up_requested.emit(hip)

    def _emit_reveal(self) -> None:
        hip = self.selected_hip()
        if hip:
            self.reveal_hip_requested.emit(hip)

    def _emit_copy(self) -> None:
        hip = self.selected_hip()
        if hip:
            self.copy_path_requested.emit(hip)
