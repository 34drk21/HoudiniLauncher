from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QSize, Qt, Signal
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMenu,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

from ...core.hip_manager import HipRecord
from ...core.models import ProjectSettings, TaskSettings
from ...core.path_resolver import PathResolver
from ..widgets import ElideLabel


def default_task_thumbnail_path() -> Path:
    """Return the wide D2 placeholder used until a Task gets a thumbnail."""
    return (
        Path(__file__).resolve().parents[2]
        / "resources"
        / "icons"
        / "houd2_task_placeholder.jpg"
    )


class TaskItemWidget(QWidget):
    """Task card/list row whose text remains inside stable bounds."""

    def __init__(
        self,
        task: TaskSettings,
        hip: HipRecord | None,
        thumbnail: Path | None,
        mode: str,
        thumbnail_size: int,
    ) -> None:
        super().__init__()
        root = QVBoxLayout(self) if mode == "cards" else QHBoxLayout(self)
        root.setContentsMargins(7, 7, 7, 7)
        root.setSpacing(7)
        image = QLabel()
        image.setAlignment(Qt.AlignmentFlag.AlignCenter)
        if mode == "cards":
            image.setFixedSize(thumbnail_size, max(72, int(thumbnail_size * 0.56)))
        else:
            icon_size = 42 if mode == "compact" else 68
            image.setFixedSize(icon_size, icon_size)
        if thumbnail:
            pixmap = QPixmap(str(thumbnail)).scaled(
                image.size(),
                Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                Qt.TransformationMode.SmoothTransformation,
            )
            image.setPixmap(pixmap)
        else:
            image.setText("No preview")
            image.setObjectName("SecondaryText")
        root.addWidget(image)
        text_box = QWidget()
        text_layout = QVBoxLayout(text_box)
        text_layout.setContentsMargins(0, 0, 0, 0)
        text_layout.setSpacing(2)
        title = ElideLabel(task.name)
        title.setObjectName("ItemTitle")
        text_layout.addWidget(title)
        version = f"v{hip.version:03d} / {hip.user}" if hip else "No HIP versions"
        version_label = ElideLabel(version)
        version_label.setObjectName("SecondaryText")
        text_layout.addWidget(version_label)
        status = ElideLabel(task.status.replace("_", " ").title())
        status.setObjectName("SecondaryText")
        text_layout.addWidget(status)
        root.addWidget(text_box, 1)


class TaskPanel(QWidget):
    """Center task browser with search, sort, and thumbnail cards."""

    task_selected = Signal(object)
    task_activated = Signal(object)
    new_task_requested = Signal()
    open_requested = Signal(object)
    new_hip_requested = Signal()
    settings_requested = Signal()
    thumbnail_requested = Signal()
    reveal_requested = Signal(object)
    rename_requested = Signal(object)
    duplicate_requested = Signal(object)
    archive_requested = Signal(object)
    restore_requested = Signal(object)
    archived_visibility_changed = Signal(bool)
    export_requested = Signal(object)
    import_requested = Signal(object)
    package_export_requested = Signal(object)
    sdm_export_requested = Signal(object)
    delete_requested = Signal(object)

    def __init__(self, resolver: PathResolver, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumWidth(350)
        self.resolver = resolver
        self.project: ProjectSettings | None = None
        self._tasks: list[tuple[TaskSettings, HipRecord | None]] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(10)
        header = QHBoxLayout()
        title = QLabel("Tasks")
        title.setObjectName("PanelTitle")
        header.addWidget(title)
        header.addStretch()
        self.show_archived = QCheckBox("Show Archived")
        self.show_archived.setToolTip("Show archived Tasks in this list")
        self.show_archived.toggled.connect(self._archived_toggled)
        header.addWidget(self.show_archived)
        add_button = QToolButton()
        add_button.setText("+")
        add_button.setToolTip("New task")
        add_button.clicked.connect(self.new_task_requested)
        header.addWidget(add_button)
        layout.addLayout(header)
        controls = QHBoxLayout()
        self.search = QLineEdit()
        self.search.setPlaceholderText("Search tasks")
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._rebuild)
        controls.addWidget(self.search, 1)
        self.sort = QComboBox()
        self.sort.addItems(["Last Modified", "Name", "Latest Version", "Latest User"])
        self.sort.currentIndexChanged.connect(self._rebuild)
        controls.addWidget(self.sort)
        layout.addLayout(controls)
        self.list = QListWidget()
        self.list.setViewMode(QListWidget.ViewMode.IconMode)
        self.list.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.list.setMovement(QListWidget.Movement.Static)
        self.list.setIconSize(QSize(220, 124))
        self.list.setGridSize(QSize(248, 208))
        self.list.setSpacing(8)
        self._view_mode = "cards"
        self._thumbnail_size = 220
        self.list.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.list.customContextMenuRequested.connect(self._context_menu)
        self.list.currentItemChanged.connect(self._selection_changed)
        self.list.itemDoubleClicked.connect(self._activated)
        layout.addWidget(self.list)

    def set_view_mode(self, mode: str, thumbnail_size: int = 220) -> None:
        """Apply the configured card, compact, or detailed task presentation."""
        self._view_mode = mode
        self._thumbnail_size = thumbnail_size
        if mode == "cards":
            self.list.setViewMode(QListWidget.ViewMode.IconMode)
            self.list.setIconSize(QSize(thumbnail_size, max(72, int(thumbnail_size * 0.56))))
            self.list.setGridSize(QSize(thumbnail_size + 28, max(156, int(thumbnail_size * 0.88))))
        else:
            self.list.setViewMode(QListWidget.ViewMode.ListMode)
            icon_size = 42 if mode == "compact" else 74
            self.list.setIconSize(QSize(icon_size, icon_size))
            self.list.setGridSize(QSize())
        if self._tasks:
            self._rebuild()

    def set_tasks(
        self,
        project: ProjectSettings,
        tasks: list[TaskSettings],
        latest: dict[str, HipRecord | None],
        selected_id: str | None = None,
    ) -> None:
        """Display task cards and preserve a preferred selection."""
        self.project = project
        self._tasks = [(task, latest.get(task.task_id)) for task in tasks]
        self._rebuild(selected_id)

    def current_task(self) -> TaskSettings | None:
        """Return the selected task settings."""
        item = self.list.currentItem()
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def clear_tasks(self) -> None:
        """Clear stale Task cards when no Project is selected or visible."""
        self.project = None
        self._tasks = []
        self.list.clear()

    def _rebuild(self, selected_id: str | None = None) -> None:
        current = self.current_task()
        selected_id = selected_id or (current.task_id if current else None)
        search = self.search.text().strip().casefold()
        items = [
            item
            for item in self._tasks
            if search in item[0].name.casefold()
            and (self.show_archived.isChecked() or item[0].status != "archived")
        ]
        sort_name = self.sort.currentText()
        if sort_name == "Name":
            items.sort(key=lambda item: item[0].name.casefold())
        elif sort_name == "Latest Version":
            items.sort(key=lambda item: item[1].version if item[1] else 0, reverse=True)
        elif sort_name == "Latest User":
            items.sort(key=lambda item: item[1].user.casefold() if item[1] else "")
        else:
            items.sort(key=lambda item: item[0].modified_at, reverse=True)
        self.list.clear()
        target: QListWidgetItem | None = None
        for task, hip in items:
            item = QListWidgetItem()
            item.setData(Qt.ItemDataRole.UserRole, task)
            if self._view_mode == "cards":
                item.setSizeHint(
                    QSize(
                        self._thumbnail_size + 28,
                        max(176, int(self._thumbnail_size * 0.56) + 92),
                    )
                )
            else:
                item.setSizeHint(QSize(280, 62 if self._view_mode == "compact" else 86))
            self.list.addItem(item)
            self.list.setItemWidget(
                item,
                TaskItemWidget(
                    task,
                    hip,
                    self._thumbnail_path(task),
                    self._view_mode,
                    self._thumbnail_size,
                ),
            )
            if task.task_id == selected_id:
                target = item
        if target:
            self.list.setCurrentItem(target)
        elif self.list.count():
            self.list.setCurrentRow(0)

    def _thumbnail_path(self, task: TaskSettings) -> Path | None:
        if self.project:
            for extension in ("jpg", "jpeg", "png"):
                path = self.resolver.resolve_thumbnail_path(
                    self.project, task, extension=extension
                )
                if path.is_file():
                    return path
        placeholder = default_task_thumbnail_path()
        return placeholder if placeholder.is_file() else None

    def _selection_changed(self, current: QListWidgetItem | None) -> None:
        if current:
            self.task_selected.emit(current.data(Qt.ItemDataRole.UserRole))

    def _archived_toggled(self, checked: bool) -> None:
        self._rebuild()
        self.archived_visibility_changed.emit(checked)

    def _activated(self, item: QListWidgetItem) -> None:
        self.task_activated.emit(item.data(Qt.ItemDataRole.UserRole))

    def _context_menu(self, position: object) -> None:
        task = self.current_task()
        if task is None:
            return
        archived = task.status == "archived"
        menu = QMenu(self)
        actions = (
            ("Open Latest HIP", lambda: self.open_requested.emit(task)),
            ("New HIP", lambda: self.new_hip_requested.emit()),
            ("Task Settings", lambda: self.settings_requested.emit()),
            ("Import Task Settings", lambda: self.import_requested.emit(task)),
            ("Export Task Settings", lambda: self.export_requested.emit(task)),
            ("Export Task Package...", lambda: self.package_export_requested.emit(task)),
            ("to SDM2.0...", lambda: self.sdm_export_requested.emit(task)),
            ("Set Thumbnail from Image", lambda: self.thumbnail_requested.emit()),
            ("Open in Explorer", lambda: self.reveal_requested.emit(task)),
            ("Rename Task", lambda: self.rename_requested.emit(task)),
            ("Duplicate Task", lambda: self.duplicate_requested.emit(task)),
            (
                "Restore Task" if archived else "Archive Task",
                lambda: (
                    self.restore_requested.emit(task)
                    if archived
                    else self.archive_requested.emit(task)
                ),
            ),
            ("Delete Task (Move to Recycle Bin)...", lambda: self.delete_requested.emit(task)),
        )
        for label, callback in actions:
            action = menu.addAction(label)
            action.triggered.connect(callback)
        menu.exec(self.list.mapToGlobal(position))
