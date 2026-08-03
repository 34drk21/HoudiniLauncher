from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QIcon, QImage
from PySide6.QtWidgets import QApplication, QToolButton, QTreeWidget

from houd2launcher.app import application_icon_path
from houd2launcher.core.cache_manager import CacheRecord, CacheScanResult
from houd2launcher.core.hip_manager import HipRecord
from houd2launcher.core.models import (
    HipMetadata,
    HoudiniInstallation,
    LauncherSettings,
    ProjectSettings,
    TaskSettings,
)
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.settings.exporter import build_package
from houd2launcher.settings.importer import identify_import, preview_import
from houd2launcher.ui.dialogs.hip_open_dialog import HipOpenDialog
from houd2launcher.ui.dialogs.first_run_dialog import FirstRunDialog
from houd2launcher.ui.dialogs.settings_import_dialog import SettingsImportDialog
from houd2launcher.ui.panels.project_panel import ProjectPanel
from houd2launcher.ui.panels.task_details_panel import TaskDetailsPanel
from houd2launcher.ui.panels.task_panel import TaskPanel, default_task_thumbnail_path


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_launcher_brand_icon_is_packaged_and_readable() -> None:
    _app()
    path = application_icon_path()
    assert path.is_file()
    assert not QIcon(str(path)).isNull()


def test_default_task_thumbnail_is_wide_and_readable() -> None:
    path = default_task_thumbnail_path()
    image = QImage(str(path))
    assert path.is_file()
    assert not image.isNull()
    assert image.width() > image.height()


def test_dark_is_the_launcher_default() -> None:
    assert LauncherSettings().theme == "dark"


def test_first_run_scan_populates_versions_before_finish(
    tmp_path: Path, monkeypatch
) -> None:
    app = _app()
    monkeypatch.setattr(FirstRunDialog, "_detect_houdini", lambda _self: None)
    dialog = FirstRunDialog(LauncherSettings())
    assert not dialog.finish_button.isEnabled()
    root = tmp_path / "Houdini 21.0.700"
    root.mkdir()
    houdini = root / "houdini.exe"
    hython = root / "hython.exe"
    houdini.write_bytes(b"")
    hython.write_bytes(b"")
    installation = HoudiniInstallation(
        display_name="Houdini 21.0.700",
        major=21,
        minor=0,
        build=700,
        version_string="21.0.700",
        install_root=root,
        houdini_executable=houdini,
        hython_executable=hython,
    )
    dialog._houdini_detected([installation])
    assert dialog.finish_button.isEnabled()
    assert dialog.houdini.currentData() == installation.installation_id
    assert dialog.working.installations[0].version_string == "21.0.700"
    dialog.deleteLater()
    app.processEvents()


def test_hip_open_dialog_prefers_fx_and_offers_core(tmp_path: Path) -> None:
    app = _app()
    root = tmp_path / "Houdini 21.0.487"
    root.mkdir()
    for name in ("houdini.exe", "houdinifx.exe", "houdinicore.exe"):
        (root / name).write_bytes(b"")
    installation = HoudiniInstallation(
        display_name="Houdini 21.0.487",
        major=21,
        minor=0,
        build=487,
        version_string="21.0.487",
        install_root=root,
        houdini_executable=root / "houdini.exe",
    )
    hip_path = tmp_path / "fx_v001_QA.hip"
    hip_path.write_bytes(b"hip")
    hip = HipRecord(
        hip_path,
        1,
        "QA",
        datetime.now(timezone.utc),
        3,
        HipMetadata(
            task_id="task-fx",
            hip_file=hip_path.name,
            hip_version=1,
            created_by="QA",
        ),
    )
    dialog = HipOpenDialog(hip, [installation], installation)
    assert dialog.edition.count() == 2
    assert dialog.edition.itemData(0) == "fx"
    assert dialog.edition.itemText(0) == "Houdini FX"
    assert dialog.edition.itemData(1) == "core"
    dialog.edition.setCurrentIndex(1)
    assert dialog.selected_edition() == "core"
    dialog.deleteLater()
    app.processEvents()


def test_project_and_task_panels_own_their_add_actions() -> None:
    app = _app()
    project_panel = ProjectPanel()
    task_panel = TaskPanel(PathResolver())
    assert any(button.text() == "+" for button in project_panel.findChildren(QToolButton))
    assert any(button.text() == "+" for button in task_panel.findChildren(QToolButton))
    project_panel.deleteLater()
    task_panel.deleteLater()
    app.processEvents()


def test_task_panel_hides_archived_tasks_until_requested(tmp_path: Path) -> None:
    app = _app()
    resolver = PathResolver()
    project = ProjectSettings(name="Demo", project_root=tmp_path / "Demo")
    archived = TaskSettings(
        project_id=project.project_id, name="old_shot", status="archived"
    )
    panel = TaskPanel(resolver)
    panel.set_tasks(project, [archived], {})
    assert panel.list.count() == 0

    panel.show_archived.setChecked(True)
    assert panel.list.count() == 1
    panel.deleteLater()
    app.processEvents()


def test_cache_view_is_parent_child_tree_and_search_keeps_hierarchy(tmp_path: Path) -> None:
    app = _app()
    resolver = PathResolver()
    project = ProjectSettings(name="Demo", project_root=tmp_path / "Demo")
    task = TaskSettings(project_id=project.project_id, name="fire")
    hip_path = tmp_path / "fire_v001_QA.hip"
    hip_path.write_bytes(b"hip")
    hip = HipRecord(
        hip_path,
        1,
        "QA",
        datetime.now(timezone.utc),
        3,
        HipMetadata(task_id=task.task_id, hip_file=hip_path.name, hip_version=1, created_by="QA"),
    )
    cache_root = tmp_path / "geo" / "smoke"
    records = tuple(
        CacheRecord(
            name="smoke",
            version=version,
            kind="BGEO.SC",
            path=cache_root / f"v{version}",
            size=version * 10,
            file_count=1,
            modified_at=datetime.now(timezone.utc),
            is_used=version == 2,
            exists=True,
            managed=True,
            node_paths=("/obj/filecache1",) if version == 2 else (),
            targets=(cache_root / f"v{version}",),
        )
        for version in (1, 2)
    )
    panel = TaskDetailsPanel(resolver)
    panel.set_task(project, task, [hip], [])
    panel.set_cache_result(CacheScanResult(hip_path, records))
    tree = panel.findChild(QTreeWidget)
    assert tree is not None
    assert tree.topLevelItemCount() == 1
    assert tree.topLevelItem(0).childCount() == 2
    assert tree.topLevelItem(0).text(4) == "30.0 B"
    panel.cache_search.setText("v002")
    assert tree.topLevelItemCount() == 1
    assert tree.topLevelItem(0).childCount() == 1
    assert tree.topLevelItem(0).child(0).text(1) == "v002"
    panel.deleteLater()
    app.processEvents()


def test_task_overview_populates_expression_environment(tmp_path: Path) -> None:
    app = _app()
    resolver = PathResolver()
    project = ProjectSettings(name="Demo", project_root=tmp_path / "Demo")
    task = TaskSettings(project_id=project.project_id, name="fire")
    panel = TaskDetailsPanel(resolver)

    panel.set_task(
        project,
        task,
        [],
        [{"created_at": "2026-08-03", "event_type": "test", "details": {}}],
        {"TASK_NAME": "fire", "SHOT_FRAME_START": "1001"},
    )

    assert panel.expression_table.rowCount() == 2
    values = {
        panel.expression_table.item(row, 0).text(): panel.expression_table.item(row, 1).text()
        for row in range(panel.expression_table.rowCount())
    }
    assert values == {"SHOT_FRAME_START": "1001", "TASK_NAME": "fire"}
    assert "Frame:" in panel.settings_summary.text()
    panel.deleteLater()
    app.processEvents()


def test_settings_update_dialog_defaults_to_replace_section(tmp_path: Path) -> None:
    app = _app()
    project = ProjectSettings(name="Demo", project_root=tmp_path / "Demo")
    incoming = project.model_copy(deep=True)
    incoming.description = "Updated settings"
    package = build_package(incoming)
    identity = identify_import(project, package)
    dialog = SettingsImportDialog(
        package, preview_import(project, package), identity
    )

    assert identity.status == "exact"
    assert dialog.mode.currentData() == "replace_section"
    assert dialog.selected_sections() == {"description"}
    dialog.deleteLater()
    app.processEvents()
