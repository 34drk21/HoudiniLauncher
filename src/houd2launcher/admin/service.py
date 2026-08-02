from __future__ import annotations

import csv
import io
import json
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any

from ..core.config import launcher_home
from ..core.hip_manager import HipManager
from ..core.path_resolver import PathResolver
from ..core.project_manager import ProjectManager
from ..core.task_manager import TaskManager
from ..database.connection import Database
from ..database.migrations import migrate
from ..database.repositories import LauncherRepository


_HISTORY_TABLES = {"activity_history", "open_history", "settings_import_history"}


class DatabaseAdminService:
    """Guarded administration operations for the local Launcher index."""

    def __init__(self, database_path: Path | None = None) -> None:
        self.database_path = (database_path or launcher_home() / "houd2launcher.db").resolve()
        if not self.database_path.is_file():
            raise FileNotFoundError(f"HouD2Launcher database was not found: {self.database_path}")

    def tables(self) -> list[dict[str, object]]:
        with self._connect(readonly=True) as connection:
            names = [
                str(row["name"])
                for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
                )
            ]
            return [
                {
                    "name": name,
                    "rows": int(connection.execute(f'SELECT COUNT(*) FROM "{name}"').fetchone()[0]),
                    "columns": [dict(row) for row in connection.execute(f'PRAGMA table_info("{name}")')],
                }
                for name in names
            ]

    def rows(
        self, table: str, *, search: str = "", sort: str = "", descending: bool = False,
        page: int = 1, page_size: int = 100,
    ) -> dict[str, object]:
        columns = self._columns(table)
        if sort not in columns:
            sort = columns[0]
        page = max(1, page)
        page_size = min(500, max(10, page_size))
        where = ""
        parameters: list[object] = []
        if search:
            where = " WHERE " + " OR ".join(f'CAST("{name}" AS TEXT) LIKE ?' for name in columns)
            parameters.extend([f"%{search}%"] * len(columns))
        direction = "DESC" if descending else "ASC"
        with self._connect(readonly=True) as connection:
            total = int(connection.execute(f'SELECT COUNT(*) FROM "{table}"{where}', parameters).fetchone()[0])
            query = f'SELECT * FROM "{table}"{where} ORDER BY "{sort}" {direction} LIMIT ? OFFSET ?'
            data = [
                {key: row[key] for key in row.keys()}
                for row in connection.execute(query, [*parameters, page_size, (page - 1) * page_size])
            ]
        return {"table": table, "columns": columns, "rows": data, "total": total, "page": page, "page_size": page_size}

    def export(self, table: str, file_format: str) -> tuple[str, bytes]:
        columns = self._columns(table)
        with self._connect(readonly=True) as connection:
            rows = [dict(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        if file_format == "json":
            return f"{table}_{timestamp}.json", json.dumps(rows, indent=2, ensure_ascii=False).encode("utf-8")
        output = io.StringIO(newline="")
        writer = csv.DictWriter(output, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)
        return f"{table}_{timestamp}.csv", output.getvalue().encode("utf-8-sig")

    def backup(self) -> Path:
        root = self.database_path.parent / "admin_backups"
        root.mkdir(parents=True, exist_ok=True)
        destination = root / f"houd2launcher_{datetime.now().strftime('%Y%m%d_%H%M%S_%f')}.db"
        with self._connect(readonly=False) as source, sqlite3.connect(destination) as target:
            source.backup(target)
        return destination

    def integrity_check(self) -> list[str]:
        with self._connect(readonly=True) as connection:
            return [str(row[0]) for row in connection.execute("PRAGMA integrity_check")]

    def clear_history(self, table: str, row_id: int | None = None) -> int:
        if table not in _HISTORY_TABLES:
            raise ValueError("Only history tables can be cleared")
        self.backup()
        with self._connect(readonly=False) as connection:
            if row_id is None:
                cursor = connection.execute(f'DELETE FROM "{table}"')
            else:
                cursor = connection.execute(f'DELETE FROM "{table}" WHERE id = ?', (row_id,))
            connection.commit()
            return int(cursor.rowcount)

    def reset_ui_state(self) -> int:
        self.backup()
        with self._connect(readonly=False) as connection:
            cursor = connection.execute("DELETE FROM ui_state")
            connection.commit()
            return int(cursor.rowcount)

    def repair_indexes(self) -> dict[str, int]:
        self.backup()
        database = Database(self.database_path)
        migrate(database)
        repository = LauncherRepository(database)
        resolver = PathResolver()
        projects = ProjectManager(repository, resolver)
        tasks = TaskManager(repository, resolver)
        hips = HipManager(repository, resolver)
        project_count = task_count = hip_count = 0
        for project in projects.registered():
            project_count += 1
            discovered = tasks.discover(project)
            task_count += len(discovered)
            valid_ids = {task.task_id for task in discovered}
            for row in repository.list_tasks(project.project_id):
                if str(row["task_id"]) not in valid_ids:
                    repository.remove_task(str(row["task_id"]))
            for task in discovered:
                hip_count += len(hips.list_hips(project, task))
        return {"projects": project_count, "tasks": task_count, "hips": hip_count}

    def _columns(self, table: str) -> list[str]:
        available = {str(item["name"]) for item in self.tables()}
        if table not in available:
            raise ValueError(f"Unknown table: {table}")
        with self._connect(readonly=True) as connection:
            columns = [str(row["name"]) for row in connection.execute(f'PRAGMA table_info("{table}")')]
        if not columns:
            raise ValueError(f"Table has no columns: {table}")
        return columns

    def _connect(self, *, readonly: bool) -> sqlite3.Connection:
        if readonly:
            uri = f"file:///{self.database_path.as_posix()}?mode=ro"
            connection = sqlite3.connect(uri, uri=True, timeout=5)
        else:
            connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA busy_timeout = 5000")
        connection.execute("PRAGMA foreign_keys = ON")
        return connection
