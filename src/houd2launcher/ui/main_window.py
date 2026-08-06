from __future__ import annotations

import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from PySide6.QtCore import (
    QByteArray,
    QFileSystemWatcher,
    QThread,
    QTimer,
    QUrl,
    Signal,
)
from PySide6.QtGui import QCloseEvent, QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QInputDialog,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QSplitter,
)

from ..application import ApplicationContext
from .. import __version__
from ..core.config import atomic_write_model, backup_file
from ..core.folder_migration import FolderMigrationPlan
from ..core.hip_manager import HipRecord
from ..core.models import HoudiniInstallation, ProjectSettings, TaskSettings
from ..core.update_manager import AvailableUpdate
from ..houdini.editions import available_houdini_editions
from ..houdini.installation_manager import HoudiniInstallationManager
from ..houdini.open_policy import should_show_open_dialog
from ..settings.exporter import export_package
from ..settings.importer import (
    ImportIdentity,
    build_import_candidate,
    identify_import,
    load_package,
    preview_import,
)
from .dialogs.hip_open_dialog import HipOpenDialog, NewHipDialog
from .dialogs.launcher_settings_dialog import LauncherSettingsDialog
from .dialogs.project_task_dialogs import (
    NewProjectDialog,
    NewTaskDialog,
    ProjectSettingsDialog,
    TaskSettingsDialog,
)
from .dialogs.settings_import_dialog import SettingsImportDialog
from .dialogs.task_package_dialog import TaskPackageImportDialog
from .dialogs.sdm_package_dialog import SdmPackageDialog
from .panels.project_panel import ProjectPanel
from .panels.task_details_panel import TaskDetailsPanel
from .panels.task_panel import TaskPanel
from .theme import apply_theme


LOGGER = logging.getLogger(__name__)


class OperationThread(QThread):
    """Execute one potentially slow core operation outside the GUI thread."""

    completed = Signal(object)
    failed = Signal(str)

    def __init__(self, operation: Callable[[], Any], parent: object | None = None) -> None:
        super().__init__(parent)
        self.operation = operation

    def run(self) -> None:
        try:
            self.completed.emit(self.operation())
        except Exception as exc:
            LOGGER.exception("Background operation failed")
            self.failed.emit(str(exc))


class ProgressOperationThread(QThread):
    """Execute an operation that reports integer percentage updates."""

    completed = Signal(object)
    failed = Signal(str)
    progress = Signal(int, str)

    def __init__(
        self,
        operation: Callable[[Callable[[int, str], None]], Any],
        parent: object | None = None,
    ) -> None:
        super().__init__(parent)
        self.operation = operation

    def run(self) -> None:
        try:
            self.completed.emit(self.operation(self.progress.emit))
        except Exception as exc:
            LOGGER.exception("Background progress operation failed")
            self.failed.emit(str(exc))


class MainWindow(QMainWindow):
    """HouD2Launcher's resizable three-column main window."""

    open_import_requested = Signal(str)

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__()
        self.context = context
        self.current_project: ProjectSettings | None = None
        self.current_task: TaskSettings | None = None
        self._threads: set[QThread] = set()
        self._progress_thread: ProgressOperationThread | None = None
        self._update_check_running = False
        self._hda_builds: set[str] = set()
        self._hda_waiters: dict[str, list[Callable[[], None]]] = {}
        self._hda_warnings: set[str] = set()
        self._ignored_task_candidates: set[tuple[str, str]] = set()
        self._suppress_adoption_prompts = True
        self._filesystem_watcher = QFileSystemWatcher(self)
        self._filesystem_timer = QTimer(self)
        self._filesystem_timer.setSingleShot(True)
        self._filesystem_timer.setInterval(1200)
        self._filesystem_watcher.directoryChanged.connect(
            lambda _path: self._filesystem_timer.start()
        )
        self._filesystem_timer.timeout.connect(self._filesystem_changed)
        self.setWindowTitle("HouD2Launcher")
        self.resize(1480, 860)
        self.setMinimumSize(1080, 680)
        self._build_menu()
        self.project_panel = ProjectPanel()
        self.task_panel = TaskPanel(context.resolver)
        self.task_panel.set_view_mode(
            context.settings.task_view_mode, context.settings.thumbnail_size
        )
        self.details_panel = TaskDetailsPanel(context.resolver)
        self.splitter = QSplitter()
        self.splitter.addWidget(self.project_panel)
        self.splitter.addWidget(self.task_panel)
        self.splitter.addWidget(self.details_panel)
        self.splitter.setSizes([296, 518, 666])
        self.splitter.setCollapsible(0, False)
        self.splitter.setCollapsible(1, False)
        self.splitter.setCollapsible(2, False)
        self._restore_ui_state()
        self.setCentralWidget(self.splitter)
        self._connect_signals()
        self.open_import_requested.connect(self._open_import_for_cache)
        self.context.catalog_api.open_import_callback = self.open_import_requested.emit
        self.import_progress = QProgressBar(self)
        self.import_progress.setRange(0, 100)
        self.import_progress.setFixedWidth(280)
        self.import_progress.setTextVisible(True)
        self.statusBar().addPermanentWidget(self.import_progress)
        self.import_progress.hide()
        self.statusBar().showMessage("Ready")
        self.refresh_projects()
        self._suppress_adoption_prompts = False
        QTimer.singleShot(2500, self._maybe_check_updates)
        QTimer.singleShot(800, self._prepare_default_hda)

    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("File")
        file_menu.addAction("New Project", self.new_project)
        file_menu.addAction("Add Existing Project", self.add_existing_project)
        file_menu.addSeparator()
        file_menu.addAction("Export Project Settings", self.export_project_settings)
        file_menu.addAction("Import Project Settings", self.import_project_settings)
        file_menu.addSeparator()
        file_menu.addAction("Exit", self.close)
        view_menu = self.menuBar().addMenu("View")
        view_menu.addAction("Refresh", self.refresh_current)
        tools_menu = self.menuBar().addMenu("Tools")
        tools_menu.addAction("Launcher Settings", self.launcher_settings)
        tools_menu.addSeparator()
        tools_menu.addAction("Export Task Settings", self.export_task_settings)
        tools_menu.addAction("Import Task Settings", self.import_task_settings)
        tools_menu.addAction("Open Logs", self.open_logs)
        help_menu = self.menuBar().addMenu("Help")
        help_menu.addAction("Open Handbook", self.open_handbook)
        help_menu.addAction("Check for Updates", lambda: self.check_for_updates(True))
        help_menu.addSeparator()
        help_menu.addAction("About", self.about)

    def _connect_signals(self) -> None:
        self.project_panel.project_selected.connect(self._select_project)
        self.project_panel.new_project_requested.connect(self.new_project)
        self.project_panel.add_project_requested.connect(self.add_existing_project)
        self.project_panel.new_task_requested.connect(self.new_task)
        self.project_panel.settings_requested.connect(self.project_settings)
        self.project_panel.reveal_requested.connect(
            lambda project: self._reveal(project.project_root)
        )
        self.project_panel.unregister_requested.connect(self.unregister_project)
        self.project_panel.export_requested.connect(self._export_project_from_context)
        self.project_panel.import_requested.connect(self._import_project_from_context)
        self.project_panel.duplicate_requested.connect(self.duplicate_project_configuration)
        self.project_panel.archive_requested.connect(self.archive_project)
        self.project_panel.restore_requested.connect(self.restore_project)
        self.project_panel.delete_requested.connect(self.delete_project_permanently)
        self.project_panel.archived_visibility_changed.connect(
            lambda _checked: self.refresh_projects()
        )
        self.project_panel.favorite_requested.connect(self.set_project_favorite)
        self.project_panel.package_import_requested.connect(self.import_task_package)
        self.task_panel.task_selected.connect(self._select_task)
        self.task_panel.new_task_requested.connect(self.new_task)
        self.task_panel.task_activated.connect(self._task_activated)
        self.task_panel.open_requested.connect(self._open_latest_for_task)
        self.task_panel.new_hip_requested.connect(self.new_hip)
        self.task_panel.settings_requested.connect(self.task_settings)
        self.task_panel.thumbnail_requested.connect(self.set_thumbnail)
        self.task_panel.reveal_requested.connect(self.reveal_task)
        self.task_panel.rename_requested.connect(self.rename_task)
        self.task_panel.duplicate_requested.connect(self.duplicate_task)
        self.task_panel.archive_requested.connect(self.archive_task)
        self.task_panel.restore_requested.connect(self.restore_task)
        self.task_panel.archived_visibility_changed.connect(
            self._task_archived_visibility_changed
        )
        self.task_panel.export_requested.connect(self._export_task_from_context)
        self.task_panel.import_requested.connect(self._import_task_from_context)
        self.task_panel.package_export_requested.connect(self.export_task_package)
        self.task_panel.sdm_export_requested.connect(self.export_sdm_package)
        self.task_panel.delete_requested.connect(self.delete_task_permanently)
        self.details_panel.open_requested.connect(self.open_hip)
        self.details_panel.version_up_requested.connect(self.version_up)
        self.details_panel.new_hip_requested.connect(self.new_hip)
        self.details_panel.task_settings_requested.connect(self.task_settings)
        self.details_panel.thumbnail_requested.connect(self.set_thumbnail)
        self.details_panel.reveal_hip_requested.connect(
            lambda hip: self._reveal(hip.path.parent)
        )
        self.details_panel.copy_path_requested.connect(self.copy_hip_path)
        self.details_panel.cache_scan_requested.connect(self.scan_hip_caches)
        self.details_panel.cache_delete_requested.connect(self.delete_caches)
        self.details_panel.reveal_cache_requested.connect(self.reveal_cache)
        self.details_panel.cache_publish_requested.connect(self.publish_caches)
        self.details_panel.cache_import_requested.connect(self.import_published_cache)
        self.details_panel.exchange_path_changed.connect(self._exchange_path_changed)
        self.details_panel.published_refresh_requested.connect(self.refresh_published_caches)

    def refresh_projects(self) -> None:
        """Reload registered projects from canonical JSON files."""
        selected = self.current_project.project_id if self.current_project else None
        include_archived = self.project_panel.show_archived.isChecked()
        try:
            projects = self.context.projects.registered(include_archived=include_archived)
        except Exception as exc:
            self._error("Cannot load projects", exc)
            projects = []
        project_records = {
            str(record["project_id"]): record
            for record in self.context.repository.list_projects(
                include_archived=include_archived
            )
        }
        self.project_panel.set_projects(
            projects,
            selected or (
                self.context.settings.last_project_id
                if self.context.settings.remember_last_project
                else None
            ),
            project_records,
        )
        if not projects:
            self.current_project = None
            self.current_task = None
            self.task_panel.clear_tasks()
            self.details_panel.clear_task()
            self.statusBar().showMessage("No project registered")

    def refresh_current(self) -> None:
        """Refresh current project tasks and HIP indexes."""
        if self.current_project:
            self._ignored_task_candidates.clear()
            self._load_tasks(self.current_project)
            if self.current_task:
                self._select_task(self.current_task)
        else:
            self.refresh_projects()

    def _select_project(self, project: ProjectSettings) -> None:
        self.current_project = project
        if self.context.settings.remember_last_project:
            self.context.settings.last_project_id = project.project_id
            self.context.save_settings()
        self._load_tasks(project)

    def _load_tasks(self, project: ProjectSettings) -> None:
        try:
            recovery = self.context.folder_migrator.recover_pending(project)
            if recovery:
                LOGGER.warning("; ".join(recovery))
            report = self.context.filesystem.reconcile(project)
            candidates = [
                name
                for name in report.task_candidates
                if (project.project_id, name) not in self._ignored_task_candidates
            ]
            if candidates:
                if self._suppress_adoption_prompts:
                    self._ignored_task_candidates.update(
                        (project.project_id, name) for name in candidates
                    )
                    candidates = []
                adopted = False
                for name in candidates:
                    dialog = NewTaskDialog(project, self)
                    dialog.setWindowTitle(f"Adopt Task Folder - {name}")
                    dialog.name.setText(name)
                    dialog.name.setReadOnly(True)
                    dialog.owner.setText(self._user_name())
                    if dialog.exec() == QDialog.DialogCode.Accepted:
                        self.context.tasks.adopt_existing(project, dialog.settings())
                        adopted = True
                    else:
                        self._ignored_task_candidates.add((project.project_id, name))
                if adopted:
                    report = self.context.filesystem.reconcile(project)
            tasks = list(report.tasks)
            latest = {
                task.task_id: next(iter(self.context.hips.list_hips(project, task)), None)
                for task in tasks
            }
            selected = (
                self.context.settings.last_task_id
                if self.context.settings.remember_last_task
                else None
            )
            self.task_panel.set_tasks(project, tasks, latest, selected)
            if report.errors:
                LOGGER.warning("Filesystem reconciliation: %s", "; ".join(report.errors))
                self.statusBar().showMessage(
                    f"{project.name}: {len(tasks)} task(s), "
                    f"{len(report.errors)} filesystem warning(s)"
                )
            else:
                self.statusBar().showMessage(f"{project.name}: {len(tasks)} task(s)")
            self._configure_filesystem_watcher(project, tasks)
        except Exception as exc:
            self._error("Cannot load tasks", exc)

    def _configure_filesystem_watcher(
        self, project: ProjectSettings, tasks: list[TaskSettings]
    ) -> None:
        existing = self._filesystem_watcher.directories()
        if existing:
            self._filesystem_watcher.removePaths(existing)
        paths = [self.context.resolver.resolve_project_root(project)]
        paths.extend(
            self.context.resolver.resolve_houdini_root(project, task)
            for task in tasks
        )
        valid = [str(path) for path in paths if path.is_dir()]
        if valid:
            self._filesystem_watcher.addPaths(valid)

    def _filesystem_changed(self) -> None:
        if self.current_project:
            self._load_tasks(self.current_project)
            if self.current_task:
                self._select_task(self.current_task)

    def _select_task(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        self.current_task = task
        if self.context.settings.remember_last_task:
            self.context.settings.last_task_id = task.task_id
            self.context.save_settings()
        try:
            hips = self.context.hips.list_hips(self.current_project, task)
            history = self.context.repository.history(
                self.current_project.project_id, task.task_id
            )
            installations = self._installations()
            installation = (
                self._recommended_installation(hips[0] if hips else None, installations)
                if installations
                else None
            )
            integration = (
                self.context.hdas.integration(installation) if installation else None
            )
            expression_environment = self.context.environment.expression_environment(
                self.current_project,
                task,
                installation,
                launcher_environment=self.context.settings.launcher_environment,
                launcher_root=str(self.context.root),
                hip_path=str(hips[0].path) if hips else "",
                user=self._user_name(),
                user_id=self.context.settings.user_id,
                machine_id=self.context.settings.machine_id,
                api_url=self.context.catalog_api.url,
                managed_hda_root=(
                    str(integration.root) if integration else ""
                ),
                managed_hda_version=(
                    integration.builder_fingerprint if integration else ""
                ),
            )
            self.details_panel.set_task(
                self.current_project,
                task,
                hips,
                history,
                expression_environment,
            )
            exchange_path = self.context.settings.cache_exchange_paths.get(
                self.current_project.project_id, ""
            )
            self.details_panel.set_exchange_path(exchange_path)
            self._refresh_published_caches()
        except Exception as exc:
            self._error("Cannot load task details", exc)

    def new_project(self) -> None:
        dialog = NewProjectDialog(self.context.settings.default_project_root, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            project = self.context.projects.create(dialog.settings())
            self.current_project = project
            self.refresh_projects()
        except Exception as exc:
            self._error("Cannot create project", exc)

    def add_existing_project(self) -> None:
        root = QFileDialog.getExistingDirectory(self, "Add Existing HouD2 Project")
        if not root:
            return
        try:
            project = self.context.projects.add_existing(Path(root))
            self.project_panel.select_project(project)
            self._select_project(project)
            self.refresh_projects()
            self.statusBar().showMessage(f"Added existing project: {project.name}", 6000)
        except Exception as exc:
            self._error("Cannot add project", exc)

    def unregister_project(self, project: ProjectSettings) -> None:
        result = QMessageBox.question(
            self,
            "Remove Project",
            "Remove this project from the launcher? Project files will not be deleted.",
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self.context.projects.unregister(project.project_id)
        self.current_project = None
        self.current_task = None
        self.refresh_projects()

    def set_project_favorite(self, project: ProjectSettings, favorite: bool) -> None:
        self.context.repository.set_project_favorite(project.project_id, favorite)
        self.refresh_projects()

    def archive_project(self, project: ProjectSettings) -> None:
        result = QMessageBox.question(
            self,
            "Archive Project",
            f"Archive {project.name} in this launcher? Project files will remain in place.",
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        self.context.repository.set_project_archived(project.project_id, True)
        self.current_project = None
        self.current_task = None
        self.details_panel.clear_task()
        self.refresh_projects()

    def restore_project(self, project: ProjectSettings) -> None:
        self.context.repository.set_project_archived(project.project_id, False)
        self.current_project = project
        self.refresh_projects()
        self.statusBar().showMessage(f"Project restored: {project.name}", 6000)

    def delete_project_permanently(self, project: ProjectSettings) -> None:
        answer = QMessageBox.warning(
            self,
            "Delete Project (Move to Recycle Bin)",
            f"Move Project '{project.name}' to the Recycle Bin?\n\n"
            "The Project folder and its files will be moved to the system Recycle Bin (Trash). "
            "You can restore it from the Recycle Bin if needed.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        confirmation, accepted = QInputDialog.getText(
            self,
            "Confirm Project Deletion",
            f'Type the Project name "{project.name}" to confirm moving to Recycle Bin:',
        )
        if not accepted:
            return
        if confirmation != project.name:
            QMessageBox.warning(
                self,
                "Project Not Deleted",
                "The entered Project name did not match.",
            )
            return
        self._run_operation(
            f"Moving Project {project.name} to Recycle Bin...",
            lambda: self.context.projects.delete_permanently(project),
            lambda _: self._project_deleted(project),
        )

    def _project_deleted(self, project: ProjectSettings) -> None:
        if self.current_project and self.current_project.project_id == project.project_id:
            self.current_project = None
            self.current_task = None
            self.details_panel.clear_task()
        if self.context.settings.last_project_id == project.project_id:
            self.context.settings.last_project_id = None
            self.context.settings.last_task_id = None
            self.context.save_settings()
        self.refresh_projects()
        self.statusBar().showMessage(
            f"Project moved to Recycle Bin: {project.name}", 8000
        )

    def duplicate_project_configuration(self, project: ProjectSettings) -> None:
        dialog = NewProjectDialog(project.project_root.parent, self)
        dialog.name.setText(f"{project.name}_copy")
        dialog.description.setPlainText(project.description)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            basic = dialog.settings()
            data = project.model_dump(mode="python")
            for key in ("project_id", "created_at", "modified_at"):
                data.pop(key, None)
            data.update(
                {
                    "name": basic.name,
                    "description": basic.description,
                    "project_root": basic.project_root,
                }
            )
            duplicate = ProjectSettings.model_validate(data)
            self.current_project = self.context.projects.create(duplicate)
            self.refresh_projects()
        except Exception as exc:
            self._error("Cannot duplicate project configuration", exc)

    def new_task(self) -> None:
        if not self._require_project():
            return
        assert self.current_project
        dialog = NewTaskDialog(self.current_project, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            task = self.context.tasks.create(self.current_project, dialog.settings())
            self.current_task = task
            self._load_tasks(self.current_project)
        except Exception as exc:
            self._error("Cannot create task", exc)

    def project_settings(self, project: ProjectSettings | None = None) -> None:
        project = project or self.current_project
        if project is None:
            return
        dialog = ProjectSettingsDialog(project, self._installations(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            proposed = dialog.result_settings()
            report = self.context.filesystem.reconcile(project)
            migration = self.context.folder_migrator.plan(
                project, proposed, list(report.tasks)
            )
            if migration.blockers:
                QMessageBox.critical(
                    self,
                    "Cannot update Folder Structure",
                    "Resolve these filesystem conflicts before saving:\n\n"
                    + "\n".join(f"- {item}" for item in migration.blockers),
                )
                return
            if migration.requires_confirmation:
                moves = sum(item.kind == "move" for item in migration.actions)
                creates = sum(item.kind == "create" for item in migration.actions)
                details = "\n".join(
                    f"- {item.task_name}: {item.role} -> {item.destination}"
                    for item in migration.actions[:12]
                )
                if len(migration.actions) > 12:
                    details += f"\n- ... and {len(migration.actions) - 12} more"
                answer = QMessageBox.question(
                    self,
                    "Apply Folder Structure",
                    f"Move {moves} folder(s) and create {creates} folder(s)?\n\n"
                    f"{details}\n\nRemoved or disabled folders will not be deleted.",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Yes,
                )
                if answer != QMessageBox.StandardButton.Yes:
                    return
                self.context.folder_migrator.apply(project, migration)
                self.context.repository.record_activity(
                    project.project_id,
                    "folder_structure_migrated",
                    {"moves": moves, "creates": creates},
                )
            self.current_project = proposed
            self.context.projects.save(proposed)
            self.context.folder_migrator.recover_pending(proposed)
            self.refresh_projects()
        except Exception as exc:
            self._error("Cannot save project settings", exc)

    def task_settings(self) -> None:
        if not self._require_task():
            return
        assert self.current_project and self.current_task
        dialog = TaskSettingsDialog(self.current_task, self._installations(), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            self.current_task = dialog.result_settings()
            self.context.tasks.save(self.current_project, self.current_task)
            self._load_tasks(self.current_project)
        except Exception as exc:
            self._error("Cannot save task settings", exc)

    def launcher_settings(self) -> None:
        dialog = LauncherSettingsDialog(
            self.context.settings,
            self,
            hip_validator=self.context.houdini.validate_hip_creation,
            hda_status=self.context.hdas.status,
            hda_builder=self.context.hdas.build,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self.context.settings = dialog.result_settings()
        self.context.save_settings()
        apply_theme(QApplication.instance(), self.context.settings.theme)
        self.task_panel.set_view_mode(
            self.context.settings.task_view_mode, self.context.settings.thumbnail_size
        )
        self.statusBar().showMessage("Launcher settings saved", 4000)

    def new_hip(self) -> None:
        if not self._require_task():
            return
        installations = self._installations()
        if not installations:
            QMessageBox.information(
                self,
                "No Houdini Installation",
                "Register or auto-detect Houdini in Launcher Settings first.",
            )
            self.launcher_settings()
            return
        assert self.current_project and self.current_task
        recommended = self._recommended_installation(None, installations)
        dialog = NewHipDialog(
            installations,
            recommended,
            preview_provider=self._new_hip_preview,
            parent=self,
        )
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        installation = dialog.installation.currentData()
        project, task = self.current_project, self.current_task
        comment = dialog.comment.text().strip()
        self._ensure_hda_then(
            installation,
            lambda: self._run_operation(
                "Creating HIP...",
                lambda: self.context.houdini.create_blank_hip(
                    project,
                    task,
                    installation,
                    self.context.settings,
                    self._user_name(),
                    comment,
                ),
                lambda _: self._hip_created(installation),
            ),
        )

    def _new_hip_preview(
        self, installation: HoudiniInstallation
    ) -> tuple[str, str]:
        assert self.current_project and self.current_task
        fallback = self.current_project.naming.default_extension
        extension = self.context.houdini.extension_for_license(
            installation.license_type, fallback
        )
        _, path = self.context.hips.next_path(
            self.current_project,
            self.current_task,
            self._user_name(),
            extension,
            installation.version_string,
        )
        return extension, str(path)

    def _hip_created(self, installation: HoudiniInstallation) -> None:
        self.context.save_settings()
        self._operation_refresh(
            f"HIP created as .{self.context.houdini.extension_for_license(installation.license_type)}"
        )

    def version_up(self, hip: HipRecord | None = None) -> None:
        if not self._require_task():
            return
        hip = hip or self.details_panel.selected_hip()
        if hip is None:
            QMessageBox.information(self, "Version Up", "Select a HIP version first.")
            return
        assert self.current_project and self.current_task
        project, task = self.current_project, self.current_task
        self._run_operation(
            "Creating next HIP version...",
            lambda: self.context.hips.version_up(
                project, task, hip, self._user_name(), "Version up"
            ),
            lambda _: self._operation_refresh("HIP version created"),
        )

    def open_selected_hip(self) -> None:
        hip = self.details_panel.selected_hip()
        if hip:
            self.open_hip(hip, False)
        else:
            QMessageBox.information(self, "Open HIP", "Select a HIP version first.")

    def open_hip(self, hip: HipRecord, read_only: bool = False) -> None:
        if not self._require_task():
            return
        installations = self._installations()
        if not installations:
            QMessageBox.warning(self, "Open HIP", "No valid Houdini installation is registered.")
            return
        assert self.current_project and self.current_task
        recommended = self._recommended_installation(hip, installations)
        has_edition_choice = len(available_houdini_editions(recommended)) > 1
        if not has_edition_choice and not should_show_open_dialog(
            self.context.settings,
            self.current_project,
            hip,
            installations,
            recommended,
        ):
            self._launch_hip(hip, recommended, read_only)
            return
        dialog = HipOpenDialog(hip, installations, recommended, read_only, self)
        if not self.current_project.houdini.allow_version_override:
            dialog.open_with.setEnabled(False)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        installation = dialog.selected_installation()
        if dialog.remember_hip.isChecked():
            hip.metadata.recommended_installation_id = installation.installation_id
            self.context.hips.save_metadata(
                self.current_project, self.current_task, hip.path, hip.metadata
            )
        if dialog.remember_task.isChecked():
            self.current_task.recommended_installation_id = installation.installation_id
            self.context.tasks.save(self.current_project, self.current_task)
        if dialog.set_project_default.isChecked():
            self.current_project.houdini.default_installation_id = installation.installation_id
            self.context.projects.save(self.current_project)
        if dialog.set_launcher_default.isChecked():
            self.context.settings.default_installation_id = installation.installation_id
            self.context.save_settings()
        self._launch_hip(
            hip,
            installation,
            dialog.read_only.isChecked(),
            dialog.selected_edition(),
        )

    def _launch_hip(
        self,
        hip: HipRecord,
        installation: HoudiniInstallation,
        read_only: bool,
        edition: str | None = None,
        ensure_hda: bool = True,
    ) -> None:
        if not self.current_project or not self.current_task:
            return
        if ensure_hda:
            self._ensure_hda_then(
                installation,
                lambda: self._launch_hip(
                    hip, installation, read_only, edition, ensure_hda=False
                ),
            )
            return
        try:
            self.context.houdini.open_hip(
                self.current_project,
                self.current_task,
                hip,
                installation,
                self.context.settings,
                self._user_name(),
                read_only,
                edition=edition,
            )
            self.statusBar().showMessage(
                f"Opened {hip.path.name} with {installation.display_name}", 8000
            )
            self._select_task(self.current_task)
        except Exception as exc:
            self._error("Cannot open HIP", exc)

    def _prepare_default_hda(self) -> None:
        installations = self._installations()
        if not installations:
            return
        installation = HoudiniInstallationManager.select_preferred(
            self.context.settings,
            [self.context.settings.default_installation_id],
        )
        if installation and self.context.hdas.should_auto_build(installation):
            self._start_hda_build(installation)

    def _ensure_hda_then(
        self, installation: HoudiniInstallation, continuation: Callable[[], None]
    ) -> None:
        status = self.context.hdas.status(installation)
        if status.state == "ready":
            continuation()
            return
        if self.context.hdas.should_auto_build(installation):
            self._start_hda_build(installation, continuation)
            return
        if status.integration is None:
            self._warn_hda_unavailable(installation, status.message or status.label)
        continuation()

    def _start_hda_build(
        self,
        installation: HoudiniInstallation,
        continuation: Callable[[], None] | None = None,
    ) -> None:
        key = installation.installation_id
        if continuation:
            self._hda_waiters.setdefault(key, []).append(continuation)
        if key in self._hda_builds:
            return
        self._hda_builds.add(key)
        self._run_operation(
            f"Building Cache HDA for {installation.display_name}...",
            lambda: self.context.hdas.build(installation),
            lambda _: self._hda_build_finished(installation),
            failed=lambda error: self._hda_build_failed(installation, error),
        )

    def _hda_build_finished(self, installation: HoudiniInstallation) -> None:
        key = installation.installation_id
        self._hda_builds.discard(key)
        self.statusBar().showMessage(
            f"Cache HDA ready for {installation.display_name}", 6000
        )
        for continuation in self._hda_waiters.pop(key, []):
            continuation()

    def _hda_build_failed(
        self, installation: HoudiniInstallation, error: str
    ) -> None:
        key = installation.installation_id
        self._hda_builds.discard(key)
        self._warn_hda_unavailable(installation, error)
        for continuation in self._hda_waiters.pop(key, []):
            continuation()

    def _warn_hda_unavailable(
        self, installation: HoudiniInstallation, message: str
    ) -> None:
        key = installation.installation_id
        if key in self._hda_warnings:
            return
        self._hda_warnings.add(key)
        QMessageBox.warning(
            self,
            "Cache HDA is Not Available",
            f"{installation.display_name}用のCommercial HDAを準備できませんでした。\n\n"
            f"{message}\n\nHoudiniはHDAなしで開きます。Launcher Settingsから再試行できます。",
        )

    def _task_activated(self, task: TaskSettings) -> None:
        if not self.context.settings.open_latest_on_double_click:
            return
        self._select_task(task)
        hip = self.details_panel.selected_hip()
        if hip:
            self.open_hip(hip, False)

    def _open_latest_for_task(self, task: TaskSettings) -> None:
        self._select_task(task)
        hip = self.details_panel.selected_hip()
        if hip:
            self.open_hip(hip, False)

    def reveal_task(self, task: TaskSettings) -> None:
        if self.current_project:
            self._reveal(self.context.resolver.resolve_task_root(self.current_project, task.name))

    def rename_task(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        name, accepted = QInputDialog.getText(
            self, "Rename Task", "New task name", text=task.name
        )
        if not accepted or name.strip() == task.name:
            return
        try:
            self.current_task = self.context.tasks.rename(
                self.current_project, task, name.strip()
            )
            self._load_tasks(self.current_project)
        except Exception as exc:
            self._error("Cannot rename task", exc)

    def duplicate_task(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        name, accepted = QInputDialog.getText(
            self, "Duplicate Task", "New task name", text=f"{task.name}_copy"
        )
        if not accepted:
            return
        try:
            data = task.model_dump(mode="python")
            data.pop("task_id", None)
            data["name"] = name.strip()
            data["status"] = "active"
            duplicate = TaskSettings.model_validate(data)
            self.current_task = self.context.tasks.create(self.current_project, duplicate)
            self._load_tasks(self.current_project)
        except Exception as exc:
            self._error("Cannot duplicate task", exc)

    def archive_task(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        result = QMessageBox.question(
            self, "Archive Task", f"Archive {task.name}? Files will remain in place."
        )
        if result != QMessageBox.StandardButton.Yes:
            return
        try:
            self.context.tasks.archive(self.current_project, task)
            if not self.task_panel.show_archived.isChecked():
                self.current_task = None
                self.details_panel.clear_task()
            self._load_tasks(self.current_project)
        except Exception as exc:
            self._error("Cannot archive task", exc)

    def restore_task(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        try:
            self.context.tasks.restore(self.current_project, task)
            self.current_task = task
            self._load_tasks(self.current_project)
            self.statusBar().showMessage(f"Task restored: {task.name}", 6000)
        except Exception as exc:
            self._error("Cannot restore task", exc)

    def _task_archived_visibility_changed(self, show_archived: bool) -> None:
        if (
            not show_archived
            and self.current_task
            and self.current_task.status == "archived"
        ):
            self.current_task = None
            self.details_panel.clear_task()

    def delete_task_permanently(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        answer = QMessageBox.warning(
            self,
            "Delete Task (Move to Recycle Bin)",
            f"Move Task '{task.name}' to the Recycle Bin?\n\n"
            "All HIP files, caches, metadata, thumbnails, and other files in this "
            "Task will be moved to the system Recycle Bin (Trash).",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        confirmation, accepted = QInputDialog.getText(
            self,
            "Confirm Task Deletion",
            f'Type the Task name "{task.name}" to confirm moving to Recycle Bin:',
        )
        if not accepted:
            return
        if confirmation != task.name:
            QMessageBox.warning(
                self,
                "Task Not Deleted",
                "The entered Task name did not match.",
            )
            return
        project = self.current_project
        self._run_operation(
            f"Moving {task.name} to Recycle Bin...",
            lambda: self.context.tasks.delete_permanently(project, task),
            lambda _: self._task_deleted(project, task),
        )

    def _task_deleted(self, project: ProjectSettings, task: TaskSettings) -> None:
        if self.current_task and self.current_task.task_id == task.task_id:
            self.current_task = None
            self.details_panel.clear_task()
        if self.context.settings.last_task_id == task.task_id:
            self.context.settings.last_task_id = None
            self.context.save_settings()
        self._load_tasks(project)
        self.statusBar().showMessage(f"Task moved to Recycle Bin: {task.name}", 8000)

    def set_thumbnail(self) -> None:
        if not self._require_task():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Set Task Thumbnail", "", "Images (*.jpg *.jpeg *.png)"
        )
        if not path:
            return
        assert self.current_project and self.current_task
        try:
            self.context.tasks.set_thumbnail(
                self.current_project, self.current_task, Path(path)
            )
            self._load_tasks(self.current_project)
        except Exception as exc:
            self._error("Cannot set thumbnail", exc)

    def export_project_settings(self) -> None:
        if not self._require_project():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Project Settings", "project_settings.json", "JSON (*.json)"
        )
        if path:
            try:
                export_package(self.current_project, Path(path))
                self.statusBar().showMessage("Project settings exported", 4000)
            except Exception as exc:
                self._error("Cannot export settings", exc)

    def import_project_settings(self) -> None:
        if not self._require_project():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Project Settings", "", "JSON (*.json)"
        )
        if not path:
            return
        assert self.current_project
        try:
            current = self.current_project
            package = load_package(Path(path))
            identity = identify_import(current, package)
            differences = preview_import(current, package)
            dialog = SettingsImportDialog(package, differences, identity, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selected = dialog.selected_sections()
            if not selected:
                QMessageBox.information(
                    self, "Nothing to Import", "No changed settings were selected."
                )
                return
            imported = build_import_candidate(
                current,
                package,
                dialog.mode.currentData(),
                selected,
            )
            report = self.context.filesystem.reconcile(current)
            migration = self.context.folder_migrator.plan(
                current, imported, list(report.tasks)
            )
            if migration.blockers:
                QMessageBox.critical(
                    self,
                    "Cannot Import Folder Structure",
                    "Resolve these filesystem conflicts before importing:\n\n"
                    + "\n".join(f"- {item}" for item in migration.blockers),
                )
                return
            if not self._confirm_settings_import(
                identity,
                "Project",
                selected,
                dialog.mode.currentData(),
                migration,
            ):
                return
            config_path = self.context.resolver.resolve_project_metadata_path(
                current
            )
            backup = backup_file(config_path)
            migration_applied = False
            save_started = False
            try:
                if migration.actions:
                    self.context.folder_migrator.apply(current, migration)
                    migration_applied = True
                save_started = True
                self.context.projects.save(imported)
                self.context.folder_migrator.recover_pending(imported)
            except Exception:
                if save_started:
                    try:
                        atomic_write_model(config_path, current)
                    except Exception:
                        LOGGER.exception("Cannot restore Project settings backup")
                if migration_applied:
                    try:
                        self.context.folder_migrator.recover_pending(current)
                    except Exception:
                        LOGGER.exception("Cannot roll back imported folder structure")
                raise
            self.current_project = imported
            self.context.repository.record_settings_import(
                "project", imported.project_id, Path(path), backup
            )
            self.context.repository.record_activity(
                imported.project_id,
                "project_settings_imported",
                {
                    "source_id": identity.source_id,
                    "source_name": identity.source_name,
                    "identity_match": identity.status,
                    "sections": sorted(selected),
                    "folder_moves": sum(
                        item.kind == "move" for item in migration.actions
                    ),
                    "folder_creates": sum(
                        item.kind == "create" for item in migration.actions
                    ),
                    "retained_folders": len(migration.retained),
                },
            )
            self.refresh_projects()
            self.statusBar().showMessage(f"Imported settings. Backup: {backup}", 8000)
        except Exception as exc:
            self._error("Cannot import settings", exc)

    def export_task_settings(self) -> None:
        if not self._require_task():
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Task Settings", "task_settings.json", "JSON (*.json)"
        )
        if path:
            try:
                export_package(self.current_task, Path(path), self.current_project)
                self.statusBar().showMessage("Task settings exported", 4000)
            except Exception as exc:
                self._error("Cannot export task settings", exc)

    def import_task_settings(self) -> None:
        if not self._require_task():
            return
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Task Settings", "", "JSON (*.json)"
        )
        if not path:
            return
        assert self.current_project and self.current_task
        try:
            current = self.current_task
            package = load_package(Path(path))
            identity = identify_import(current, package)
            differences = preview_import(current, package)
            dialog = SettingsImportDialog(package, differences, identity, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            selected = dialog.selected_sections()
            if not selected:
                QMessageBox.information(
                    self, "Nothing to Import", "No changed settings were selected."
                )
                return
            imported = build_import_candidate(
                current,
                package,
                dialog.mode.currentData(),
                selected,
            )
            if not self._confirm_settings_import(
                identity, "Task", selected, dialog.mode.currentData()
            ):
                return
            config_path = self.context.resolver.resolve_task_metadata_path(
                self.current_project, current
            )
            backup = backup_file(config_path)
            try:
                self.context.tasks.save(self.current_project, imported)
            except Exception:
                try:
                    atomic_write_model(config_path, current)
                except Exception:
                    LOGGER.exception("Cannot restore Task settings backup")
                raise
            self.current_task = imported
            self.context.repository.record_settings_import(
                "task", imported.task_id, Path(path), backup
            )
            self.context.repository.record_activity(
                self.current_project.project_id,
                "task_settings_imported",
                {
                    "source_id": identity.source_id,
                    "source_name": identity.source_name,
                    "identity_match": identity.status,
                    "sections": sorted(selected),
                },
                imported.task_id,
            )
            self._load_tasks(self.current_project)
            self._select_task(imported)
            self.statusBar().showMessage(f"Imported task settings. Backup: {backup}", 8000)
        except Exception as exc:
            self._error("Cannot import task settings", exc)

    def _confirm_settings_import(
        self,
        identity: ImportIdentity,
        scope: str,
        sections: set[str],
        mode: str,
        migration: FolderMigrationPlan | None = None,
    ) -> bool:
        """Require an explicit confirmation for updates and folder mutations."""
        actions = migration.actions if migration else ()
        moves = sum(item.kind == "move" for item in actions)
        creates = sum(item.kind == "create" for item in actions)
        retained = len(migration.retained) if migration else 0
        operation = {
            "merge": "Merge",
            "overwrite": "Merge and overwrite",
            "replace_section": "Replace",
        }.get(mode, "Import")
        summary = (
            f"{operation} {len(sections)} portable setting section(s) on "
            f'{scope} "{identity.target_name}"?'
        )
        if migration:
            summary += (
                f"\n\nFolder changes: {moves} move(s), {creates} create(s), "
                f"{retained} retained old folder(s)."
                "\nRemoved or disabled folders will not be deleted."
            )
            changed_paths = [
                f"- {item.task_name}/{item.role}: {item.kind} -> {item.destination}"
                for item in actions[:10]
            ]
            if len(actions) > 10:
                changed_paths.append(f"- ... and {len(actions) - 10} more")
            retained_paths = [f"- retain: {path}" for path in migration.retained[:5]]
            if len(migration.retained) > 5:
                retained_paths.append(
                    f"- ... and {len(migration.retained) - 5} more retained"
                )
            preview = changed_paths + retained_paths
            if preview:
                summary += "\n\n" + "\n".join(preview)
        if identity.status == "name_match":
            summary += (
                "\n\nThe name matches, but the IDs are different. "
                "Type the target name to confirm."
            )
            confirmation, accepted = QInputDialog.getText(
                self, f"Confirm {scope} Settings Update", summary
            )
            return accepted and confirmation == identity.target_name
        if identity.status == "exact" or actions:
            answer = QMessageBox.question(
                self,
                f"Confirm {scope} Settings Import",
                summary,
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                QMessageBox.StandardButton.Yes,
            )
            return answer == QMessageBox.StandardButton.Yes
        return True

    def _export_project_from_context(self, project: ProjectSettings) -> None:
        self.current_project = project
        self.export_project_settings()

    def _import_project_from_context(self, project: ProjectSettings) -> None:
        self.current_project = project
        self.import_project_settings()

    def _export_task_from_context(self, task: TaskSettings) -> None:
        self.current_task = task
        self.export_task_settings()

    def _import_task_from_context(self, task: TaskSettings) -> None:
        self.current_task = task
        self.import_task_settings()

    def export_task_package(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        destination = QFileDialog.getExistingDirectory(
            self,
            "Export Task Package",
            str(self.current_project.project_root.parent),
        )
        if not destination:
            return
        project = self.current_project
        installation_versions = {
            item.installation_id: item.version_string
            for item in self.context.settings.installations
        }
        source_versions = sorted(
            {
                installation_versions[installation_id]
                for hip in self.context.hips.list_hips(project, task)
                for installation_id in (
                    hip.metadata.last_saved_with,
                    hip.metadata.recommended_installation_id,
                )
                if installation_id in installation_versions
            }
        )
        self._run_operation(
            f"Exporting {task.name} Task Package...",
            lambda: self.context.task_packages.export(
                project, task, Path(destination), source_versions
            ),
            lambda path: self.statusBar().showMessage(
                f"Task Package exported: {path}", 8000
            ),
        )

    def export_sdm_package(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        project = self.current_project
        try:
            records = list(self.context.caches.discover(project, task, []))
        except Exception as exc:
            self._error("Cannot scan Geo Caches", exc)
            return
        dialog = SdmPackageDialog(project, records, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        destination = QFileDialog.getExistingDirectory(
            self, "Export SDM2.0 Package", str(project.project_root.parent)
        )
        if not destination:
            return
        roles = dialog.selected_roles()
        caches = dialog.selected_caches()
        self._run_operation(
            f"Exporting {task.name} to SDM2.0...",
            lambda: self.context.sdm_packages.export(
                project, task, Path(destination), roles, caches
            ),
            lambda path: self.statusBar().showMessage(f"SDM2.0 Package exported: {path}", 8000),
            failed=lambda error: self._error("Cannot export SDM2.0 Package", error),
        )

    def import_task_package(self, project: ProjectSettings) -> None:
        package = QFileDialog.getExistingDirectory(
            self,
            "Select Task Package Folder",
            str(project.project_root.parent),
        )
        if not package:
            return
        package_path = Path(package)
        self._run_operation(
            "Validating Task Package checksums...",
            lambda: self.context.task_packages.preview_import(package_path, project),
            lambda preview: self._show_task_package_preview(project, preview),
        )

    def _show_task_package_preview(self, project: ProjectSettings, preview: object) -> None:
        dialog = TaskPackageImportDialog(preview, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        self._run_operation(
            f"Importing {preview.target_task_name}...",
            lambda: self.context.task_packages.import_package(
                preview.package_root, project, preview
            ),
            lambda task: self._task_package_imported(project, task),
        )

    def _task_package_imported(
        self, project: ProjectSettings, task: TaskSettings
    ) -> None:
        self.current_project = project
        self.current_task = task
        self.context.settings.last_task_id = task.task_id
        self.context.save_settings()
        self._load_tasks(project)
        self.statusBar().showMessage(f"Task Package imported as {task.name}", 8000)

    def copy_hip_path(self, hip: HipRecord) -> None:
        QApplication.clipboard().setText(str(hip.path))
        self.statusBar().showMessage("HIP path copied", 3000)

    def scan_hip_caches(self, hip: HipRecord) -> None:
        if not self._require_task():
            return
        installations = self._installations()
        if not installations:
            QMessageBox.warning(
                self, "Cache Scan", "No valid Houdini installation is registered."
            )
            return
        assert self.current_project and self.current_task
        installation = self._recommended_installation(hip, installations)
        project, task = self.current_project, self.current_task
        self.details_panel.set_cache_loading(hip)
        self._run_operation(
            f"Scanning caches in {hip.path.name}...",
            lambda: self.context.cache_scanner.scan(
                project,
                task,
                hip,
                installation,
                self.context.settings,
                self._user_name(),
            ),
            self._cache_scan_completed,
            failed=self._cache_scan_failed,
        )

    def _cache_scan_completed(self, result: object) -> None:
        self.details_panel.set_cache_result(result)
        self._refresh_published_caches()
        self.statusBar().showMessage("Cache scan completed", 5000)

    def _cache_scan_failed(self, message: str) -> None:
        self.details_panel.set_cache_error(message)
        self._error("Cache scan failed", message)

    def delete_caches(self, records: list[object]) -> None:
        if not self._require_task() or not records:
            return
        used = [record for record in records if record.is_used]
        total = sum(record.size for record in records)
        warning = (
            "\n\nWARNING: The selected HIP currently references one or more of these versions."
            if used
            else ""
        )
        answer = QMessageBox.warning(
            self,
            "Delete Caches Permanently",
            f"Permanently delete {len(records)} cache version(s) "
            f"({self.details_panel._format_size(total)})?\n\n"
            f"This cannot be undone.{warning}",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        assert self.current_project and self.current_task
        project, task = self.current_project, self.current_task
        self._run_operation(
            "Deleting caches permanently...",
            lambda: self.context.caches.delete_permanently(project, task, records),
            lambda _: self._rescan_after_cache_delete(),
        )

    def _rescan_after_cache_delete(self) -> None:
        self.statusBar().showMessage("Caches deleted permanently", 5000)
        hip = self.details_panel.selected_hip()
        if hip:
            self.scan_hip_caches(hip)

    def reveal_cache(self, record: object) -> None:
        path = record.path
        self._reveal(path if path.is_dir() else path.parent)

    def _exchange_path_changed(self, value: str) -> None:
        if not self.current_project:
            return
        if value:
            self.context.settings.cache_exchange_paths[self.current_project.project_id] = value
        else:
            self.context.settings.cache_exchange_paths.pop(self.current_project.project_id, None)
        self.context.save_settings()
        self.context.cache_catalog.refresh()
        self._refresh_published_caches()

    def _refresh_published_caches(self) -> bool:
        if not self.current_project:
            self.details_panel.set_published_records(())
            return True
        value = self.context.settings.cache_exchange_paths.get(self.current_project.project_id, "")
        try:
            records = self.context.cache_exchange.discover(Path(value)) if value else ()
            self.details_panel.set_published_records(records)
            return True
        except Exception as exc:
            LOGGER.exception("Cannot read Published Caches")
            self.details_panel.set_published_records(())
            self.statusBar().showMessage(f"Cannot read Published Caches: {exc}")
            return False

    def refresh_published_caches(self) -> None:
        self.context.cache_catalog.refresh()
        if self._refresh_published_caches():
            self.statusBar().showMessage("Published Caches refreshed", 5000)

    def publish_caches(self, records: list[object], exchange_path: str) -> None:
        if not self.current_project or not self.current_task or not exchange_path:
            self._error("Cannot publish Cache", "Set a Publish / Import Path first")
            return
        project, task = self.current_project, self.current_task
        self._run_operation(
            "Publishing Cache...",
            lambda: self.context.cache_exchange.publish(Path(exchange_path), project, task, records),
            lambda result: self._cache_transfer_completed(f"Published {len(result)} Cache Version(s)"),
            failed=lambda error: self._error("Cannot publish Cache", error),
        )

    def import_published_cache(
        self, record: object, _exchange_path: str, delete_source: bool
    ) -> None:
        if not self.current_project or not self.current_task:
            return
        project, task = self.current_project, self.current_task
        self._run_progress_operation(
            "Importing Cache...",
            lambda progress: self.context.cache_exchange.import_cache(
                record,
                project,
                task,
                delete_source=delete_source,
                progress=progress,
            ),
            lambda result: self._cache_transfer_completed(
                result.warning or "Cache imported successfully"
            ),
            failed=lambda error: self._error("Cannot import Cache", error),
        )

    def _cache_transfer_completed(self, message: str) -> None:
        self.context.cache_catalog.refresh()
        self.statusBar().showMessage(message, 5000)
        self._refresh_published_caches()
        hip = self.details_panel.selected_hip()
        if hip:
            self.scan_hip_caches(hip)

    def _open_import_for_cache(self, cache_id: str) -> None:
        self.showNormal()
        self.raise_()
        self.activateWindow()
        try:
            record = self.context.cache_catalog.find_cache(cache_id)
            project = next(
                item for item in self.context.projects.registered()
                if item.project_id == str(record["project_id"])
            )
            task = next(
                item for item in self.context.tasks.discover(project)
                if item.task_id == str(record["task_id"])
            )
            if not self.current_project or self.current_project.project_id != project.project_id:
                self._select_project(project)
            self._select_task(task)
        except Exception as exc:
            LOGGER.warning("Could not select Cache import context: %s", exc)
        self._refresh_published_caches()
        self.details_panel.open_import_tab(cache_id)

    def _recommended_installation(
        self, hip: HipRecord | None, installations: list[HoudiniInstallation]
    ) -> HoudiniInstallation:
        ids = [
            hip.metadata.recommended_installation_id if hip else None,
            self.current_task.recommended_installation_id if self.current_task else None,
            self.current_project.houdini.default_installation_id
            if self.current_project
            else None,
            self.context.settings.default_installation_id,
        ]
        selected = HoudiniInstallationManager.select_preferred(
            self.context.settings, ids
        )
        return selected or installations[0]

    def _installations(self) -> list[HoudiniInstallation]:
        return HoudiniInstallationManager.enabled(self.context.settings)

    def _run_operation(
        self,
        message: str,
        operation: Callable[[], Any],
        completed: Callable[[object], None],
        failed: Callable[[str], None] | None = None,
    ) -> None:
        self.statusBar().showMessage(message)
        thread = OperationThread(operation, self)
        self._threads.add(thread)
        thread.completed.connect(completed)
        thread.failed.connect(failed or (lambda error: self._error("Operation failed", error)))
        thread.finished.connect(lambda: self._threads.discard(thread))
        thread.start()

    def _run_progress_operation(
        self,
        message: str,
        operation: Callable[[Callable[[int, str], None]], Any],
        completed: Callable[[object], None],
        failed: Callable[[str], None] | None = None,
    ) -> None:
        if self._progress_thread and self._progress_thread.isRunning():
            QMessageBox.information(
                self,
                "Operation in Progress",
                "Wait for the current file operation to finish.",
            )
            return
        self.statusBar().showMessage(message)
        self.import_progress.setValue(0)
        self.import_progress.setFormat("Preparing: %p%")
        self.import_progress.show()
        thread = ProgressOperationThread(operation, self)
        self._progress_thread = thread
        self._threads.add(thread)
        thread.progress.connect(self._update_import_progress)
        thread.completed.connect(completed)
        thread.failed.connect(
            failed or (lambda error: self._error("Operation failed", error))
        )

        def cleanup() -> None:
            self.import_progress.hide()
            self._threads.discard(thread)
            if self._progress_thread is thread:
                self._progress_thread = None

        thread.finished.connect(cleanup)
        thread.start()

    def _update_import_progress(self, percent: int, phase: str) -> None:
        value = max(0, min(100, percent))
        self.import_progress.setValue(value)
        self.import_progress.setFormat(f"{phase}: %p%")
        self.statusBar().showMessage(f"{phase}: {value}%")

    def _maybe_check_updates(self) -> None:
        settings = self.context.settings
        if not settings.auto_check_updates or not settings.update_channel_path:
            return
        cutoff = datetime.now(timezone.utc) - timedelta(days=1)
        last = settings.last_update_check_at
        if last is None or last.astimezone(timezone.utc) <= cutoff:
            self.check_for_updates(False)

    def check_for_updates(self, manual: bool = True) -> None:
        channel = self.context.settings.update_channel_path
        if channel is None:
            if manual:
                QMessageBox.information(
                    self,
                    "Update Channel Required",
                    "Set an Update Channel in Launcher Settings > Updates.",
                )
            return
        if self._update_check_running:
            if manual:
                self.statusBar().showMessage("An update check is already running", 4000)
            return
        self._update_check_running = True
        self._run_operation(
            "Checking for Launcher updates...",
            lambda: self.context.updates.check(channel),
            lambda result: self._update_check_completed(result, manual),
            failed=lambda error: self._update_check_failed(error, manual),
        )

    def _update_check_completed(self, result: object, manual: bool) -> None:
        self._update_check_running = False
        self.context.settings.last_update_check_at = datetime.now(timezone.utc)
        self.context.save_settings()
        if result is None:
            if manual:
                QMessageBox.information(
                    self,
                    "HouD2Launcher is Up to Date",
                    f"Installed Version: {__version__}",
                )
            else:
                self.statusBar().showMessage("HouD2Launcher is up to date", 4000)
            return
        if not isinstance(result, AvailableUpdate):
            self._error("Cannot Check for Updates", "Unexpected update response")
            return
        self._offer_update(result)

    def _update_check_failed(self, error: str, manual: bool) -> None:
        self._update_check_running = False
        if manual:
            self._error("Cannot Check for Updates", error)
        else:
            LOGGER.warning("Automatic update check failed: %s", error)
            self.statusBar().showMessage("Update Channel is unavailable", 5000)

    def _offer_update(self, update: AvailableUpdate) -> None:
        manifest = update.manifest
        dialog = QMessageBox(self)
        dialog.setWindowTitle("HouD2Launcher Update Available")
        dialog.setIcon(QMessageBox.Icon.Information)
        dialog.setText(
            f"HouD2Launcher {manifest.version} is available.\n"
            f"Installed: {__version__}\n"
            f"Size: {self.details_panel._format_size(manifest.size_bytes)}"
        )
        if manifest.release_notes.strip():
            dialog.setInformativeText(manifest.release_notes.strip())
        update_button = dialog.addButton("Update", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("Later", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        if dialog.clickedButton() != update_button:
            return
        self._run_progress_operation(
            "Preparing Launcher Update...",
            lambda progress: self.context.updates.stage(
                update, self.context.data_home, progress
            ),
            lambda path: self._update_staged(update, Path(path)),
            failed=lambda error: self._error("Cannot Prepare Update", error),
        )

    def _update_staged(self, update: AvailableUpdate, installer: Path) -> None:
        try:
            self.context.updates.backup_local_state(
                self.context.data_home,
                self.context.settings_path,
                self.context.database.path,
                __version__,
                update.manifest.version,
            )
        except Exception as exc:
            self._error("Cannot Back Up Launcher Data", exc)
            return

        def launch() -> None:
            try:
                self.context.updates.launch_installer(installer)
            except Exception as exc:
                self._error("Cannot Start Update Installer", exc)
                return
            QApplication.quit()

        QTimer.singleShot(350, launch)

    def _operation_refresh(self, message: str) -> None:
        self.statusBar().showMessage(message, 5000)
        if self.current_project:
            self._load_tasks(self.current_project)

    def _user_name(self) -> str:
        return (
            self.context.settings.initials.strip()
            or self.context.settings.display_name.strip()
            or "user"
        )

    def _require_project(self) -> bool:
        if self.current_project:
            return True
        QMessageBox.information(self, "Project Required", "Select or create a project first.")
        return False

    def _require_task(self) -> bool:
        if self.current_project and self.current_task:
            return True
        QMessageBox.information(self, "Task Required", "Select or create a task first.")
        return False

    def _reveal(self, path: Path) -> None:
        if not path.exists():
            QMessageBox.warning(self, "Open in Explorer", f"Path does not exist: {path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def open_logs(self) -> None:
        self._reveal(self.context.data_home / "logs")

    def open_handbook(self) -> None:
        path = self.context.root / "docs" / "houd2-handbook.html"
        if not path.is_file():
            self._error("Cannot Open Handbook", f"Handbook was not found: {path}")
            return
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(path)))

    def about(self) -> None:
        QMessageBox.about(
            self,
            "About HouD2Launcher",
            f"HouD2Launcher v{__version__}\n"
            "Local-first standalone project launcher for Houdini.",
        )

    def _error(self, title: str, error: object) -> None:
        LOGGER.error("%s: %s", title, error)
        self.statusBar().showMessage(title, 6000)
        QMessageBox.critical(self, title, str(error))

    def closeEvent(self, event: QCloseEvent) -> None:
        running = [thread for thread in self._threads if thread.isRunning()]
        if running:
            result = QMessageBox.question(
                self,
                "Operation Running",
                "A background operation is still running. Close after it completes?",
            )
            if result != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            for thread in running:
                thread.wait(5000)
            if any(thread.isRunning() for thread in running):
                event.ignore()
                return
        self.context.repository.set_ui_state(
            "main_window_geometry", bytes(self.saveGeometry().toBase64()).decode("ascii")
        )
        self.context.repository.set_ui_state(
            "main_splitter_state", bytes(self.splitter.saveState().toBase64()).decode("ascii")
        )
        super().closeEvent(event)

    def _restore_ui_state(self) -> None:
        geometry = self.context.repository.get_ui_state("main_window_geometry")
        splitter = self.context.repository.get_ui_state("main_splitter_state")
        if geometry:
            self.restoreGeometry(QByteArray.fromBase64(geometry.encode("ascii")))
        if splitter:
            self.splitter.restoreState(QByteArray.fromBase64(splitter.encode("ascii")))
