from __future__ import annotations

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.models import ProjectSettings
from ..widgets import ElideLabel


class ProjectItemWidget(QWidget):
    """Bounded project row with independently elided fields."""

    def __init__(
        self, project: ProjectSettings, state: str, accessed: str, favorite: bool
    ) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.setContentsMargins(7, 5, 7, 5)
        layout.setSpacing(2)
        name = ElideLabel(("* " if favorite else "") + project.name)
        name.setObjectName("ItemTitle")
        layout.addWidget(name)
        meta = ElideLabel(f"{state}   Last: {accessed or '-'}")
        meta.setObjectName("SecondaryText")
        layout.addWidget(meta)
        path = ElideLabel(str(project.project_root))
        path.setObjectName("SecondaryText")
        layout.addWidget(path)


class ProjectPanel(QWidget):
    """Left-side registered project list."""

    project_selected = Signal(object)
    new_project_requested = Signal()
    add_project_requested = Signal()
    new_task_requested = Signal()
    settings_requested = Signal(object)
    reveal_requested = Signal(object)
    unregister_requested = Signal(object)
    export_requested = Signal(object)
    import_requested = Signal(object)
    duplicate_requested = Signal(object)
    archive_requested = Signal(object)
    restore_requested = Signal(object)
    delete_requested = Signal(object)
    archived_visibility_changed = Signal(bool)
    favorite_requested = Signal(object, bool)
    package_import_requested = Signal(object)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setObjectName("ProjectPanel")
        self.setMinimumWidth(210)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Projects")
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch()
        add_button = QToolButton()
        add_button.setText("+")
        add_button.setToolTip("New project")
        add_button.clicked.connect(self.new_project_requested)
        header.addWidget(add_button)
        menu_button = QToolButton()
        menu_button.setText("...")
        menu_button.setToolTip("Project actions")
        menu_button.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        header_menu = QMenu(menu_button)
        header_menu.addAction("Add Existing Project", self.add_project_requested.emit)
        menu_button.setMenu(header_menu)
        header.addWidget(menu_button)
        layout.addLayout(header)
        self.show_archived = QCheckBox("Show Archived")
        self.show_archived.setToolTip("Show archived Projects in this list")
        self.show_archived.toggled.connect(self.archived_visibility_changed)
        layout.addWidget(self.show_archived)
        self.list = QListWidget()
        self.list.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._show_context_menu)
        self.list.currentItemChanged.connect(self._selection_changed)
        layout.addWidget(self.list)

    def set_projects(
        self,
        projects: list[ProjectSettings],
        selected_id: str | None = None,
        records: dict[str, dict[str, object]] | None = None,
    ) -> None:
        """Replace the project list and restore a selected project when possible."""
        self.list.clear()
        target: QListWidgetItem | None = None
        records = records or {}
        for project in projects:
            state = "Available" if project.project_root.is_dir() else "Missing"
            record = records.get(project.project_id, {})
            archived = bool(record.get("archived"))
            if archived:
                state = "Archived"
            favorite = bool(record.get("favorite"))
            accessed = str(record.get("last_accessed") or "")[:16].replace("T", " ")
            item = QListWidgetItem()
            item.setSizeHint(QSize(220, 78))
            item.setData(Qt.ItemDataRole.UserRole, project)
            item.setData(Qt.ItemDataRole.UserRole + 1, favorite)
            item.setData(Qt.ItemDataRole.UserRole + 2, archived)
            item.setToolTip(str(project.project_root))
            self.list.addItem(item)
            self.list.setItemWidget(
                item, ProjectItemWidget(project, state, accessed, favorite)
            )
            if project.project_id == selected_id:
                target = item
        if target:
            self.list.setCurrentItem(target)
        elif self.list.count():
            self.list.setCurrentRow(0)

    def current_project(self) -> ProjectSettings | None:
        """Return the currently selected project."""
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select_project(self, project: str | ProjectSettings) -> None:
        """Select a project by its ID or ProjectSettings object."""
        target_id = project.project_id if isinstance(project, ProjectSettings) else project
        for row in range(self.list.count()):
            item = self.list.item(row)
            data = item.data(Qt.ItemDataRole.UserRole)
            if isinstance(data, ProjectSettings) and data.project_id == target_id:
                self.list.setCurrentItem(item)
                return

    def _selection_changed(self, current: QListWidgetItem | None) -> None:
        if current:
            self.project_selected.emit(current.data(Qt.ItemDataRole.UserRole))

    def _show_context_menu(self, position: object) -> None:
        project = self.current_project()
        if project is None:
            return
        item = self.list.currentItem()
        archived = bool(item.data(Qt.ItemDataRole.UserRole + 2)) if item else False
        menu = QMenu(self)
        actions: list[tuple[str, object]] = [
            ("New Task", lambda: self.new_task_requested.emit()),
            ("Project Settings", lambda: self.settings_requested.emit(project)),
            ("Import Project Settings", lambda: self.import_requested.emit(project)),
            ("Export Project Settings", lambda: self.export_requested.emit(project)),
            ("Import Task Package...", lambda: self.package_import_requested.emit(project)),
            ("Open in Explorer", lambda: self.reveal_requested.emit(project)),
            ("Duplicate Project Configuration", lambda: self.duplicate_requested.emit(project)),
            (
                "Restore Project" if archived else "Archive Project",
                lambda: (
                    self.restore_requested.emit(project)
                    if archived
                    else self.archive_requested.emit(project)
                ),
            ),
            (
                "Remove from Favorites" if bool(self.list.currentItem().data(Qt.ItemDataRole.UserRole + 1)) else "Add to Favorites",
                lambda: self.favorite_requested.emit(
                    project,
                    not bool(self.list.currentItem().data(Qt.ItemDataRole.UserRole + 1)),
                ),
            ),
            ("Remove from Launcher", lambda: self.unregister_requested.emit(project)),
            ("Delete Project (Move to Recycle Bin)...", lambda: self.delete_requested.emit(project)),
        ]
        for label, callback in actions:
            action = QAction(label, menu)
            action.triggered.connect(callback)
            menu.addAction(action)
        menu.exec(self.list.mapToGlobal(position))
