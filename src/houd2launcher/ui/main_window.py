from __future__ import annotations

import logging
from collections.abc import Callable
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
    QSplitter,
)

from ..application import ApplicationContext
from ..core.config import atomic_write_model
from ..core.hip_manager import HipRecord
from ..core.models import HoudiniInstallation, ProjectSettings, TaskSettings
from ..houdini.editions import available_houdini_editions
from ..houdini.installation_manager import HoudiniInstallationManager
from ..houdini.open_policy import should_show_open_dialog
from ..settings.exporter import export_package
from ..settings.importer import apply_import, load_package, preview_import
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


class MainWindow(QMainWindow):
    """HouD2Launcher's resizable three-column main window."""

    def __init__(self, context: ApplicationContext) -> None:
        super().__init__()
        self.context = context
        self.current_project: ProjectSettings | None = None
        self.current_task: TaskSettings | None = None
        self._threads: set[OperationThread] = set()
        self._ignored_task_candidates: set[str] = set()
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
        self.statusBar().showMessage("Ready")
        self.refresh_projects()

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
        self.task_panel.export_requested.connect(self._export_task_from_context)
        self.task_panel.import_requested.connect(self._import_task_from_context)
        self.task_panel.package_export_requested.connect(self.export_task_package)
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

    def refresh_projects(self) -> None:
        """Reload registered projects from canonical JSON files."""
        selected = self.current_project.project_id if self.current_project else None
        try:
            projects = self.context.projects.registered()
        except Exception as exc:
            self._error("Cannot load projects", exc)
            projects = []
        project_records = {
            str(record["project_id"]): record
            for record in self.context.repository.list_projects(include_archived=False)
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
        self._ignored_task_candidates.clear()
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
                if name not in self._ignored_task_candidates
            ]
            if candidates:
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
                        self._ignored_task_candidates.add(name)
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
            )
            self.details_panel.set_task(
                self.current_project,
                task,
                hips,
                history,
                expression_environment,
            )
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
            self.current_project = project
            self.refresh_projects()
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
        self.refresh_projects()

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
        self._run_operation(
            "Creating HIP...",
            lambda: self.context.houdini.create_blank_hip(
                project,
                task,
                installation,
                self.context.settings,
                self._user_name(),
                dialog.comment.text().strip(),
            ),
            lambda _: self._hip_created(installation),
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
    ) -> None:
        if not self.current_project or not self.current_task:
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
            self._load_tasks(self.current_project)
        except Exception as exc:
            self._error("Cannot archive task", exc)

    def delete_task_permanently(self, task: TaskSettings) -> None:
        if not self.current_project:
            return
        answer = QMessageBox.warning(
            self,
            "Delete Task Permanently",
            f"Permanently delete {task.name}?\n\n"
            "All HIP files, caches, metadata, thumbnails, and other files in this "
            "Task will be deleted. This cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        confirmation, accepted = QInputDialog.getText(
            self,
            "Confirm Permanent Deletion",
            f'Type the Task name "{task.name}" to confirm:',
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
            f"Deleting {task.name} permanently...",
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
        self.statusBar().showMessage(f"Task deleted permanently: {task.name}", 8000)

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
            package = load_package(Path(path))
            differences = preview_import(self.current_project, package)
            dialog = SettingsImportDialog(package, differences, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            config_path = self.context.resolver.resolve_project_metadata_path(
                self.current_project
            )
            imported, backup = apply_import(
                self.current_project,
                package,
                config_path,
                dialog.mode.currentData(),
                dialog.selected_sections(),
            )
            self.current_project = imported
            self.context.projects.save(imported)
            self.context.repository.record_settings_import(
                "project", imported.project_id, Path(path), backup
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
                export_package(self.current_task, Path(path))
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
            package = load_package(Path(path))
            differences = preview_import(self.current_task, package)
            dialog = SettingsImportDialog(package, differences, self)
            if dialog.exec() != QDialog.DialogCode.Accepted:
                return
            config_path = self.context.resolver.resolve_task_metadata_path(
                self.current_project, self.current_task
            )
            imported, backup = apply_import(
                self.current_task,
                package,
                config_path,
                dialog.mode.currentData(),
                dialog.selected_sections(),
            )
            self.current_task = imported
            self.context.tasks.save(self.current_project, imported)
            self.context.repository.record_settings_import(
                "task", imported.task_id, Path(path), backup
            )
            self._load_tasks(self.current_project)
            self.statusBar().showMessage(f"Imported task settings. Backup: {backup}", 8000)
        except Exception as exc:
            self._error("Cannot import task settings", exc)

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

    def about(self) -> None:
        QMessageBox.about(
            self,
            "About HouD2Launcher",
            "HouD2Launcher v0.2\nLocal-first standalone project launcher for Houdini.",
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
