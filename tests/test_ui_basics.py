from __future__ import annotations

import os
from datetime import datetime, timezone
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QToolButton, QTreeWidget

from houd2launcher.core.cache_manager import CacheRecord, CacheScanResult
from houd2launcher.core.hip_manager import HipRecord
from houd2launcher.core.models import HipMetadata, LauncherSettings, ProjectSettings, TaskSettings
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.ui.panels.project_panel import ProjectPanel
from houd2launcher.ui.panels.task_details_panel import TaskDetailsPanel
from houd2launcher.ui.panels.task_panel import TaskPanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_dark_is_the_launcher_default() -> None:
    assert LauncherSettings().theme == "dark"


def test_project_and_task_panels_own_their_add_actions() -> None:
    app = _app()
    project_panel = ProjectPanel()
    task_panel = TaskPanel(PathResolver())
    assert any(button.text() == "+" for button in project_panel.findChildren(QToolButton))
    assert any(button.text() == "+" for button in task_panel.findChildren(QToolButton))
    project_panel.deleteLater()
    task_panel.deleteLater()
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
