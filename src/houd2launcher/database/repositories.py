from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .connection import Database


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class LauncherRepository:
    """Store launcher indexes and histories while JSON remains authoritative."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def upsert_project(
        self, project_id: str, name: str, root: Path, config_path: Path
    ) -> None:
        """Insert or refresh a registered project index record."""
        with self.database.connect() as connection:
            stale = self._project_at_root(connection, root, exclude_id=project_id)
            if stale is not None:
                self._replace_project_registration(
                    connection,
                    str(stale["project_id"]),
                    project_id,
                    name,
                    root,
                    config_path,
                )
                return

            connection.execute(
                """
                INSERT INTO projects(project_id, name, root, config_path, last_accessed, missing)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id) DO UPDATE SET
                    name=excluded.name,
                    root=excluded.root,
                    config_path=excluded.config_path,
                    last_accessed=excluded.last_accessed,
                    missing=excluded.missing
                """,
                (
                    project_id,
                    name,
                    str(root),
                    str(config_path),
                    _now(),
                    int(not root.exists()),
                ),
            )

    def remove_project(self, project_id: str) -> None:
        """Remove a launcher registration without touching project files."""
        with self.database.connect() as connection:
            connection.execute("DELETE FROM projects WHERE project_id = ?", (project_id,))

    def replace_project_registration(
        self,
        stale_project_id: str,
        project_id: str,
        name: str,
        root: Path,
        config_path: Path,
    ) -> None:
        """Replace a stale ID for the same canonical project registration."""
        with self.database.connect() as connection:
            self._replace_project_registration(
                connection,
                stale_project_id,
                project_id,
                name,
                root,
                config_path,
            )

    @staticmethod
    def _replace_project_registration(
        connection: Any,
        stale_project_id: str,
        project_id: str,
        name: str,
        root: Path,
        config_path: Path,
    ) -> None:
        stale = connection.execute(
            "SELECT * FROM projects WHERE project_id = ?", (stale_project_id,)
        ).fetchone()
        if stale is None:
            raise LookupError(f"Stale project registration not found: {stale_project_id}")
        if connection.execute(
            "SELECT 1 FROM projects WHERE project_id = ?", (project_id,)
        ).fetchone():
            raise ValueError(f"Project ID is already registered: {project_id}")

        connection.execute(
            "UPDATE activity_history SET project_id = ? WHERE project_id = ?",
            (project_id, stale_project_id),
        )
        connection.execute(
            "UPDATE open_history SET project_id = ? WHERE project_id = ?",
            (project_id, stale_project_id),
        )
        connection.execute(
            "UPDATE settings_import_history SET target_id = ? WHERE target_id = ?",
            (project_id, stale_project_id),
        )
        connection.execute(
            "DELETE FROM projects WHERE project_id = ?", (stale_project_id,)
        )
        connection.execute(
            """
            INSERT INTO projects(
                project_id, name, root, config_path, favorite, archived,
                last_accessed, missing
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                project_id,
                name,
                str(root),
                str(config_path),
                stale["favorite"],
                stale["archived"],
                _now(),
                int(not root.exists()),
            ),
        )

    @staticmethod
    def _project_at_root(
        connection: Any, root: Path, *, exclude_id: str
    ) -> Any | None:
        target = root.expanduser().resolve()
        rows = connection.execute(
            "SELECT * FROM projects WHERE project_id != ?", (exclude_id,)
        ).fetchall()
        for row in rows:
            if Path(str(row["root"])).expanduser().resolve() == target:
                return row
        return None

    def set_project_favorite(self, project_id: str, favorite: bool) -> None:
        """Set the per-user favorite state for one project."""
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE projects SET favorite = ? WHERE project_id = ?",
                (int(favorite), project_id),
            )

    def set_project_archived(self, project_id: str, archived: bool) -> None:
        """Set the launcher-only archived state for one project."""
        with self.database.connect() as connection:
            connection.execute(
                "UPDATE projects SET archived = ? WHERE project_id = ?",
                (int(archived), project_id),
            )

    def list_projects(self, include_archived: bool = False) -> list[dict[str, Any]]:
        """Return registered projects ordered by favorite and recent access."""
        query = "SELECT * FROM projects"
        parameters: tuple[object, ...] = ()
        if not include_archived:
            query += " WHERE archived = 0"
        query += " ORDER BY favorite DESC, last_accessed DESC, name COLLATE NOCASE"
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute(query, parameters).fetchall()]

    def upsert_task(
        self,
        task_id: str,
        project_id: str,
        name: str,
        config_path: Path,
        status: str,
        modified_at: str,
    ) -> None:
        """Insert or refresh one task index record."""
        with self.database.connect() as connection:
            stale = connection.execute(
                "SELECT * FROM tasks WHERE project_id = ? AND name = ? AND task_id != ?",
                (project_id, name, task_id),
            ).fetchone()
            if stale is not None:
                if connection.execute(
                    "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
                ).fetchone():
                    raise ValueError(f"Task ID is already registered: {task_id}")
                stale_id = str(stale["task_id"])
                connection.execute(
                    "UPDATE activity_history SET task_id = ? WHERE task_id = ?",
                    (task_id, stale_id),
                )
                connection.execute(
                    "UPDATE open_history SET task_id = ? WHERE task_id = ?",
                    (task_id, stale_id),
                )
                connection.execute(
                    "UPDATE settings_import_history SET target_id = ? WHERE target_id = ?",
                    (task_id, stale_id),
                )
                connection.execute("DELETE FROM tasks WHERE task_id = ?", (stale_id,))
            connection.execute(
                """
                INSERT INTO tasks(task_id, project_id, name, config_path, status, modified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(task_id) DO UPDATE SET
                    project_id=excluded.project_id,
                    name=excluded.name,
                    config_path=excluded.config_path,
                    status=excluded.status,
                    modified_at=excluded.modified_at
                """,
                (task_id, project_id, name, str(config_path), status, modified_at),
            )

    def list_tasks(self, project_id: str) -> list[dict[str, Any]]:
        """Return tasks for a project ordered by recent changes."""
        with self.database.connect() as connection:
            rows = connection.execute(
                "SELECT * FROM tasks WHERE project_id = ? ORDER BY modified_at DESC",
                (project_id,),
            ).fetchall()
        return [dict(row) for row in rows]

    def task_id_exists(self, task_id: str) -> bool:
        """Return whether a Task ID is already indexed anywhere locally."""
        with self.database.connect() as connection:
            return connection.execute(
                "SELECT 1 FROM tasks WHERE task_id = ?", (task_id,)
            ).fetchone() is not None

    def remove_task(self, task_id: str) -> None:
        """Remove a Task and its rebuildable HIP index rows."""
        with self.database.connect() as connection:
            connection.execute("DELETE FROM tasks WHERE task_id = ?", (task_id,))

    def upsert_hip(
        self,
        hip_path: Path,
        task_id: str,
        version: int,
        user_name: str,
        metadata_path: Path,
    ) -> None:
        """Insert or refresh one HIP index record."""
        modified = datetime.fromtimestamp(
            hip_path.stat().st_mtime, tz=timezone.utc
        ).isoformat() if hip_path.exists() else _now()
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO hips(hip_path, task_id, version, user_name, metadata_path, modified_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT(hip_path) DO UPDATE SET
                    task_id=excluded.task_id,
                    version=excluded.version,
                    user_name=excluded.user_name,
                    metadata_path=excluded.metadata_path,
                    modified_at=excluded.modified_at
                """,
                (str(hip_path), task_id, version, user_name, str(metadata_path), modified),
            )

    def record_activity(
        self,
        project_id: str,
        event_type: str,
        details: dict[str, object] | None = None,
        task_id: str | None = None,
    ) -> None:
        """Append an immutable project or task activity entry."""
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO activity_history(project_id, task_id, event_type, details, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (project_id, task_id, event_type, json.dumps(details or {}), _now()),
            )

    def record_open(
        self,
        project_id: str,
        task_id: str,
        hip_path: Path,
        installation_id: str,
        mode: str,
    ) -> None:
        """Record a HIP open event."""
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO open_history(
                    project_id, task_id, hip_path, installation_id, mode, opened_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (project_id, task_id, str(hip_path), installation_id, mode, _now()),
            )

    def record_settings_import(
        self,
        scope: str,
        target_id: str,
        source_path: Path,
        backup_path: Path | None,
    ) -> None:
        """Record a validated settings import and its backup location."""
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO settings_import_history(
                    scope, target_id, source_path, backup_path, imported_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (
                    scope,
                    target_id,
                    str(source_path),
                    str(backup_path) if backup_path else None,
                    _now(),
                ),
            )

    def history(self, project_id: str, task_id: str | None = None) -> list[dict[str, Any]]:
        """Return recent activity for a project or one task."""
        query = "SELECT * FROM activity_history WHERE project_id = ?"
        parameters: list[object] = [project_id]
        if task_id:
            query += " AND task_id = ?"
            parameters.append(task_id)
        query += " ORDER BY created_at DESC LIMIT 250"
        with self.database.connect() as connection:
            return [dict(row) for row in connection.execute(query, parameters).fetchall()]

    def set_ui_state(self, key: str, value: str) -> None:
        """Persist one opaque UI state value."""
        with self.database.connect() as connection:
            connection.execute(
                """
                INSERT INTO ui_state(key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value=excluded.value
                """,
                (key, value),
            )

    def get_ui_state(self, key: str) -> str | None:
        """Return one persisted UI state value."""
        with self.database.connect() as connection:
            row = connection.execute(
                "SELECT value FROM ui_state WHERE key = ?", (key,)
            ).fetchone()
        return str(row["value"]) if row else None
