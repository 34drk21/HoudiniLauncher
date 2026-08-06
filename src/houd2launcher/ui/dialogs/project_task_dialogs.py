from __future__ import annotations

import getpass
from pathlib import Path

from pydantic import ValidationError
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ...core.models import (
    FolderDefinition,
    FrameSettings,
    HoudiniInstallation,
    HoudiniPolicy,
    NamingSettings,
    ProjectSettings,
    SearchPathSettings,
    TaskSettings,
)
from ..widgets import add_helped_row


class NewProjectDialog(QDialog):
    """Collect the minimal fields required to create a project."""

    def __init__(self, default_root: Path | None = None, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("New Project")
        self.setMinimumWidth(560)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("例: MyGame_FX")
        self.description = QTextEdit()
        self.description.setPlaceholderText("例: MyGame用のHoudini FXプロジェクト")
        self.description.setMaximumHeight(90)
        root_row = QHBoxLayout()
        self.root = QLineEdit(str(default_root or ""))
        self.root.setPlaceholderText(r"例: D:\Projects\MyGame")
        browse = QPushButton("Browse")
        browse.clicked.connect(self._browse)
        root_row.addWidget(self.root, 1)
        root_row.addWidget(browse)
        add_helped_row(form, "Project name", self.name, "Launcherに表示するProject名です。Windowsで使用できない文字は使えません。")
        add_helped_row(form, "Description", self.description, "目的や案件名など、Projectを識別するための説明です。")
        form.addRow("Project root", root_row)
        root_help = QLabel("Taskフォルダを作成するローカルの保存先です。例: D:\\Projects\\MyGame")
        root_help.setObjectName("FieldHelp")
        root_help.setWordWrap(True)
        form.addRow("", root_help)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> ProjectSettings:
        """Build validated project settings from the dialog fields."""
        name = self.name.text().strip()
        root_text = self.root.text().strip()
        root_path = Path(root_text) if root_text else Path(".")
        if name and root_path.name.casefold() != name.casefold():
            root_path = root_path / name
        return ProjectSettings(
            name=name,
            description=self.description.toPlainText().strip(),
            project_root=root_path,
        )

    def accept(self) -> None:
        try:
            self.settings()
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid project", str(exc))
            return
        super().accept()

    def _browse(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Choose Project Root", self.root.text())
        if path:
            self.root.setText(path)


class NewTaskDialog(QDialog):
    """Collect and validate task metadata."""

    def __init__(self, project: ProjectSettings, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.project = project
        self.setWindowTitle("New Task")
        self.setMinimumWidth(480)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.name = QLineEdit()
        self.name.setPlaceholderText("例: wall_destruction_010")
        self.description = QTextEdit()
        self.description.setPlaceholderText("例: Wall fracture and dust simulation")
        self.description.setMaximumHeight(90)
        self.owner = QLineEdit(getpass.getuser())
        self.start = QSpinBox()
        self.start.setRange(-1_000_000, 1_000_000)
        self.start.setValue(project.default_frames.start)
        self.end = QSpinBox()
        self.end.setRange(-1_000_000, 1_000_000)
        self.end.setValue(project.default_frames.end)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(0.001, 1000)
        self.fps.setValue(project.default_frames.fps)
        add_helped_row(form, "Task name", self.name, "Project Root直下のフォルダ名になります。例: wall_destruction_010")
        add_helped_row(form, "Description", self.description, "作業内容やショット用途を記録します。")
        add_helped_row(form, "Owner", self.owner, "Taskの主担当者名です。")
        add_helped_row(form, "Start frame", self.start, "Houdiniへ渡すSHOTSTARTFRAMEの初期値です。")
        add_helped_row(form, "End frame", self.end, "Houdiniへ渡すSHOTENDFRAMEの初期値です。")
        add_helped_row(form, "FPS", self.fps, "Project既定のフレームレートです。例: 24")
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Ok
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def settings(self) -> TaskSettings:
        """Build validated task settings from dialog fields."""
        return TaskSettings(
            project_id=self.project.project_id,
            name=self.name.text(),
            description=self.description.toPlainText().strip(),
            owner=self.owner.text().strip(),
            frames=FrameSettings(
                start=self.start.value(),
                end=self.end.value(),
                fps=self.fps.value(),
                sim_start=self.start.value(),
            ),
        )

    def accept(self) -> None:
        try:
            self.settings()
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid task", str(exc))
            return
        super().accept()


class KeyValueTable(QWidget):
    """Reusable environment-variable editor."""

    def __init__(self, values: dict[str, str], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        help_label = QLabel("環境変数名は大文字・数字・アンダースコアを使用します。値には {project_root}、{task_name}、{role:geo_cache} などのTokenを指定できます。")
        help_label.setObjectName("FieldHelp")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        controls = QHBoxLayout()
        add = QPushButton("Add")
        remove = QPushButton("Remove")
        add.clicked.connect(self._add)
        remove.clicked.connect(self._remove)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch()
        layout.addLayout(controls)
        self.table = QTableWidget(0, 2)
        self.table.setHorizontalHeaderLabels(["Variable", "Value / Template"])
        self.table.horizontalHeader().setStretchLastSection(True)
        self.table.setWordWrap(False)
        self.table.verticalHeader().setVisible(False)
        self.table.verticalHeader().setDefaultSectionSize(34)
        layout.addWidget(self.table)
        for name, value in values.items():
            self._add(name, value)

    def values(self) -> dict[str, str]:
        """Return non-empty key/value rows."""
        result: dict[str, str] = {}
        for row in range(self.table.rowCount()):
            name_item = self.table.item(row, 0)
            value_item = self.table.item(row, 1)
            if name_item and name_item.text().strip():
                result[name_item.text().strip()] = value_item.text() if value_item else ""
        return result

    def _add(self, name: str = "", value: str = "") -> None:
        row = self.table.rowCount()
        self.table.insertRow(row)
        self.table.setItem(row, 0, QTableWidgetItem(name))
        self.table.setItem(row, 1, QTableWidgetItem(value))

    def _remove(self) -> None:
        rows = sorted({item.row() for item in self.table.selectedItems()}, reverse=True)
        for row in rows:
            self.table.removeRow(row)


class ProjectSettingsDialog(QDialog):
    """Edit project settings in General, Folders, Environment, Houdini, Paths, and Naming tabs."""

    def __init__(
        self,
        project: ProjectSettings,
        installations: list[HoudiniInstallation],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.original = project
        self.installations = installations
        self._result: ProjectSettings | None = None
        self.setWindowTitle(f"Project Settings - {project.name}")
        self.resize(820, 640)
        layout = QVBoxLayout(self)
        self.tabs = QTabWidget()
        layout.addWidget(self.tabs)
        self._general_tab(project)
        self._folders_tab(project)
        self._sdm_tab(project)
        self._environment_tab(project)
        self._houdini_tab(project)
        self._paths_tab(project)
        self._naming_tab(project)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _general_tab(self, project: ProjectSettings) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.project_name = QLineEdit(project.name)
        self.project_id = QLineEdit(project.project_id)
        self.project_id.setReadOnly(True)
        self.project_root = QLineEdit(str(project.project_root))
        self.project_root.setReadOnly(True)
        self.project_description = QTextEdit(project.description)
        self.default_start = QSpinBox()
        self.default_start.setRange(-1_000_000, 1_000_000)
        self.default_start.setValue(project.default_frames.start)
        self.default_end = QSpinBox()
        self.default_end.setRange(-1_000_000, 1_000_000)
        self.default_end.setValue(project.default_frames.end)
        self.default_fps = QDoubleSpinBox()
        self.default_fps.setRange(0.001, 1000)
        self.default_fps.setValue(
            60.0 if project.default_frames.fps == 24.0 else project.default_frames.fps
        )
        self.project_name.setPlaceholderText("例: MyGame_FX")
        self.project_description.setPlaceholderText("例: Project共有ルールや目的")
        add_helped_row(form, "Project name", self.project_name, "表示名です。Project IDと保存先は変更されません。")
        add_helped_row(form, "Project ID", self.project_id, "Importや履歴で使用する固定IDです。")
        add_helped_row(form, "Project root", self.project_root, "Taskを格納するローカルルートです。")
        add_helped_row(form, "Description", self.project_description, "Projectの目的や運用メモです。")
        add_helped_row(form, "Default start", self.default_start, "新規Taskに設定する開始フレームです。")
        add_helped_row(form, "Default end", self.default_end, "新規Taskに設定する終了フレームです。")
        add_helped_row(form, "Default FPS", self.default_fps, "新規TaskとHoudini起動環境へ適用するFPSです。")
        self.tabs.addTab(page, "General")

    def _folders_tab(self, project: ProjectSettings) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        help_label = QLabel("Relative Pathはhoudiniフォルダからの相対パスです。絶対パスや .. は使用できません。例: cache/geo")
        help_label.setObjectName("FieldHelp")
        help_label.setWordWrap(True)
        layout.addWidget(help_label)
        controls = QHBoxLayout()
        add = QPushButton("Add Folder")
        remove = QPushButton("Remove")
        add.clicked.connect(lambda: self._add_folder())
        remove.clicked.connect(self._remove_folder)
        controls.addWidget(add)
        controls.addWidget(remove)
        controls.addStretch()
        layout.addLayout(controls)
        self.folder_table = QTableWidget(0, 6)
        self.folder_table.setHorizontalHeaderLabels(
            ["Key", "Display Name", "Role", "Relative Path", "Auto Create", "Enabled"]
        )
        self.folder_table.horizontalHeader().setStretchLastSection(True)
        self.folder_table.setWordWrap(False)
        self.folder_table.verticalHeader().setVisible(False)
        self.folder_table.verticalHeader().setDefaultSectionSize(34)
        layout.addWidget(self.folder_table)
        for folder in project.folders:
            self._add_folder(folder)
        preview_label = QLabel("Task folders are always created under: {project_root}/{task}/houdini/")
        preview_label.setWordWrap(True)
        layout.addWidget(preview_label)
        self.tabs.addTab(page, "Folder Structure")

    def _environment_tab(self, project: ProjectSettings) -> None:
        self.environment_editor = KeyValueTable(project.environment)
        self.tabs.addTab(self.environment_editor, "Environment")

    def _sdm_tab(self, project: ProjectSettings) -> None:
        page = QWidget()
        layout = QVBoxLayout(page)
        help_label = QLabel(
            "Choose the Houdini folder roles included by default in to SDM2.0. "
            "HIP files are always included, and Geo Cache Versions are selected for each export."
        )
        help_label.setWordWrap(True)
        help_label.setObjectName("FieldHelp")
        layout.addWidget(help_label)
        defaults = project.sdm_default_folder_roles
        enabled = set(defaults if defaults is not None else [item.role for item in project.folders if item.enabled])
        self.sdm_role_checks: dict[str, QCheckBox] = {}
        for folder in project.folders:
            if not folder.enabled or folder.role == "geo_cache":
                continue
            checkbox = QCheckBox(f"{folder.display_name}  ({folder.relative_path})")
            checkbox.setChecked(folder.role in enabled)
            self.sdm_role_checks[folder.role] = checkbox
            layout.addWidget(checkbox)
        layout.addStretch()
        self.tabs.addTab(page, "to SDM2.0")

    def _houdini_tab(self, project: ProjectSettings) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.default_houdini = QComboBox()
        self.default_houdini.addItem("Launcher default", None)
        for installation in self.installations:
            self.default_houdini.addItem(installation.display_name, installation.installation_id)
        index = self.default_houdini.findData(project.houdini.default_installation_id)
        self.default_houdini.setCurrentIndex(max(0, index))
        self.allow_override = QCheckBox()
        self.allow_override.setChecked(project.houdini.allow_version_override)
        self.fallback = QComboBox()
        policies = [
            ("Require Exact Build", "require_exact"),
            ("Allow Same Major.Minor", "same_major_minor"),
            ("Allow Newer Compatible", "newer_compatible"),
            ("Always Ask", "always_ask"),
        ]
        for label, value in policies:
            self.fallback.addItem(label, value)
        self.fallback.setCurrentIndex(self.fallback.findData(project.houdini.fallback_policy))
        self.set_job = QCheckBox()
        self.set_job.setChecked(project.houdini.set_job_to_houdini_root)
        self.apply_fps = QCheckBox()
        self.apply_fps.setChecked(project.houdini.apply_project_fps)
        self.apply_frames = QCheckBox()
        self.apply_frames.setChecked(project.houdini.apply_task_frame_range)
        add_helped_row(form, "Default Houdini", self.default_houdini, "このProjectで優先するHoudiniです。未指定時はLauncher既定を使います。")
        add_helped_row(form, "Version override", self.allow_override, "HIPを開く際に別バージョンを選択できるようにします。")
        add_helped_row(form, "Fallback policy", self.fallback, "指定Buildがない場合に許可する代替バージョンの範囲です。")
        add_helped_row(form, "Set $JOB", self.set_job, "$JOBを選択Taskのhoudiniフォルダへ設定します。")
        add_helped_row(form, "Apply project FPS", self.apply_fps, "Houdini起動時にProject FPSを環境へ渡します。")
        add_helped_row(form, "Apply frame range", self.apply_frames, "Taskの開始・終了フレームを環境へ渡します。")
        self.tabs.addTab(page, "Houdini")

    def _paths_tab(self, project: ProjectSettings) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.path_edits: dict[str, QTextEdit] = {}
        for name, label in (
            ("hda", "HDA"),
            ("python", "Python"),
            ("scripts", "Scripts"),
            ("toolbar", "Toolbar"),
            ("icons", "Icons"),
            ("packages", "Packages"),
        ):
            editor = QTextEdit("\n".join(getattr(project.search_paths, name)))
            editor.setMaximumHeight(72)
            editor.setPlaceholderText("例: {project_root}/pipeline/houdini/hda")
            self.path_edits[name] = editor
            add_helped_row(form, label, editor, "1行に1パスを指定できます。Token展開後、Houdiniの検索パスへ追加されます。")
        self.tabs.addTab(page, "Search Paths")

    def _naming_tab(self, project: ProjectSettings) -> None:
        page = QWidget()
        form = QFormLayout(page)
        self.hip_template = QLineEdit(project.naming.hip_template)
        self.version_padding = QSpinBox()
        self.version_padding.setRange(2, 8)
        self.version_padding.setValue(project.naming.version_padding)
        self.extension = QComboBox()
        self.extension.addItems(["hip", "hiplc", "hipnc"])
        self.extension.setCurrentText(project.naming.default_extension)
        self.hip_template.setPlaceholderText("例: {task}_v{version:03d}_{user}.{extension}")
        add_helped_row(form, "HIP template", self.hip_template, "HIP名の規則です。Tokenは下記一覧から使用します。")
        add_helped_row(form, "Version padding", self.version_padding, "Version番号の桁数です。3ならv001になります。")
        add_helped_row(form, "Default extension", self.extension, "ライセンスが未判定の場合の候補です。通常はライセンスに合わせて自動決定します。")
        tokens = QLabel(
            "Tokens: {project}, {task}, {version}, {user}, {date}, "
            "{houdini_version}, {extension}"
        )
        tokens.setWordWrap(True)
        form.addRow("", tokens)
        self.tabs.addTab(page, "Naming")

    def settings(self) -> ProjectSettings:
        """Build a validated updated project model."""
        data = self.original.model_dump(mode="python")
        data.update(
            {
                "name": self.project_name.text(),
                "description": self.project_description.toPlainText().strip(),
                "default_frames": FrameSettings(
                    start=self.default_start.value(),
                    end=self.default_end.value(),
                    fps=self.default_fps.value(),
                    sim_start=self.default_start.value(),
                ),
                "folders": self._folders(),
                "sdm_default_folder_roles": [
                    role for role, checkbox in self.sdm_role_checks.items() if checkbox.isChecked()
                ],
                "environment": self.environment_editor.values(),
                "search_paths": SearchPathSettings(
                    **{
                        name: [
                            line.strip()
                            for line in editor.toPlainText().splitlines()
                            if line.strip()
                        ]
                        for name, editor in self.path_edits.items()
                    }
                ),
                "naming": NamingSettings(
                    hip_template=self.hip_template.text(),
                    version_padding=self.version_padding.value(),
                    default_extension=self.extension.currentText(),
                ),
                "houdini": HoudiniPolicy(
                    default_installation_id=self.default_houdini.currentData(),
                    allow_version_override=self.allow_override.isChecked(),
                    fallback_policy=self.fallback.currentData(),
                    set_job_to_houdini_root=self.set_job.isChecked(),
                    apply_project_fps=self.apply_fps.isChecked(),
                    apply_task_frame_range=self.apply_frames.isChecked(),
                    thumbnail_capture_policy=self.original.houdini.thumbnail_capture_policy,
                ),
            }
        )
        return ProjectSettings.model_validate(data)

    def result_settings(self) -> ProjectSettings:
        """Return settings captured at successful acceptance."""
        if self._result is None:
            raise RuntimeError("Dialog was not accepted")
        return self._result

    def accept(self) -> None:
        try:
            self._result = self.settings()
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid project settings", str(exc))
            return
        super().accept()

    def _add_folder(self, folder: FolderDefinition | None = None) -> None:
        row = self.folder_table.rowCount()
        self.folder_table.insertRow(row)
        folder = folder or FolderDefinition(
            key=f"folder_{row + 1}",
            display_name="New Folder",
            role=f"role_{row + 1}",
            relative_path=f"folder_{row + 1}",
        )
        values = [folder.key, folder.display_name, folder.role, folder.relative_path]
        for column, value in enumerate(values):
            self.folder_table.setItem(row, column, QTableWidgetItem(value))
        for column, checked in ((4, folder.auto_create), (5, folder.enabled)):
            item = QTableWidgetItem()
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Checked if checked else Qt.CheckState.Unchecked)
            self.folder_table.setItem(row, column, item)

    def _remove_folder(self) -> None:
        rows = sorted({item.row() for item in self.folder_table.selectedItems()}, reverse=True)
        for row in rows:
            self.folder_table.removeRow(row)

    def _folders(self) -> list[FolderDefinition]:
        result = []
        for row in range(self.folder_table.rowCount()):
            result.append(
                FolderDefinition(
                    key=self.folder_table.item(row, 0).text(),
                    display_name=self.folder_table.item(row, 1).text(),
                    role=self.folder_table.item(row, 2).text(),
                    relative_path=self.folder_table.item(row, 3).text(),
                    auto_create=self.folder_table.item(row, 4).checkState()
                    == Qt.CheckState.Checked,
                    enabled=self.folder_table.item(row, 5).checkState()
                    == Qt.CheckState.Checked,
                )
            )
        return result


class TaskSettingsDialog(QDialog):
    """Edit task general, frame, environment, and Houdini override settings."""

    def __init__(
        self,
        task: TaskSettings,
        installations: list[HoudiniInstallation],
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.original = task
        self._result: TaskSettings | None = None
        self.setWindowTitle(f"Task Settings - {task.name}")
        self.resize(680, 520)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        general = QWidget()
        form = QFormLayout(general)
        self.name = QLineEdit(task.name)
        self.name.setReadOnly(True)
        self.task_id = QLineEdit(task.task_id)
        self.task_id.setReadOnly(True)
        self.description = QTextEdit(task.description)
        self.status = QComboBox()
        self.status.addItems(["active", "on_hold", "complete", "archived"])
        self.status.setCurrentText(task.status)
        self.owner = QLineEdit(task.owner)
        self.description.setPlaceholderText("例: Dust simulation and debris pass")
        add_helped_row(form, "Task name", self.name, "フォルダ名とHIP命名に使う固定名です。Rename操作から変更します。")
        add_helped_row(form, "Task ID", self.task_id, "履歴やImportで使用する内部IDです。")
        add_helped_row(form, "Description", self.description, "Taskの作業内容や引き継ぎ情報です。")
        add_helped_row(form, "Status", self.status, "active、on hold、complete、archivedから状態を選びます。")
        add_helped_row(form, "Owner", self.owner, "Taskの主担当者名です。")
        tabs.addTab(general, "General")
        frames = QWidget()
        frame_form = QFormLayout(frames)
        self.start = QSpinBox()
        self.end = QSpinBox()
        self.sim_start = QSpinBox()
        for widget, value in (
            (self.start, task.frames.start),
            (self.end, task.frames.end),
            (self.sim_start, task.frames.sim_start),
        ):
            widget.setRange(-1_000_000, 1_000_000)
            widget.setValue(value)
        self.fps = QDoubleSpinBox()
        self.fps.setRange(0.001, 1000)
        self.fps.setValue(task.frames.fps)
        add_helped_row(frame_form, "SHOTSTARTFRAME", self.start, "ショットの開始フレームです。")
        add_helped_row(frame_form, "SHOTENDFRAME", self.end, "ショットの終了フレームです。")
        add_helped_row(frame_form, "SHOTFPS", self.fps, "このTaskで使用するフレームレートです。")
        add_helped_row(frame_form, "SIMSTARTFRAME", self.sim_start, "プリロールを含むSimulation開始フレームです。")
        tabs.addTab(frames, "Frame Settings")
        self.environment_editor = KeyValueTable(task.environment)
        tabs.addTab(self.environment_editor, "Environment")
        houdini = QWidget()
        houdini_form = QFormLayout(houdini)
        self.recommended = QComboBox()
        self.recommended.addItem("Use Project Default", None)
        for installation in installations:
            self.recommended.addItem(installation.display_name, installation.installation_id)
        index = self.recommended.findData(task.recommended_installation_id)
        self.recommended.setCurrentIndex(max(0, index))
        add_helped_row(houdini_form, "Recommended Houdini", self.recommended, "このTaskだけProject既定を上書きできます。")
        tabs.addTab(houdini, "Houdini")
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Cancel | QDialogButtonBox.StandardButton.Save
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def result_settings(self) -> TaskSettings:
        """Return validated task settings captured on acceptance."""
        if self._result is None:
            raise RuntimeError("Dialog was not accepted")
        return self._result

    def accept(self) -> None:
        data = self.original.model_dump(mode="python")
        data.update(
            {
                "description": self.description.toPlainText().strip(),
                "status": self.status.currentText(),
                "owner": self.owner.text().strip(),
                "frames": FrameSettings(
                    start=self.start.value(),
                    end=self.end.value(),
                    fps=self.fps.value(),
                    sim_start=self.sim_start.value(),
                ),
                "environment": self.environment_editor.values(),
                "recommended_installation_id": self.recommended.currentData(),
            }
        )
        try:
            self._result = TaskSettings.model_validate(data)
        except (ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "Invalid task settings", str(exc))
            return
        super().accept()
