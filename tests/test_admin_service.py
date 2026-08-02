from __future__ import annotations

from houd2launcher.admin.service import DatabaseAdminService


def test_admin_browse_export_backup_and_integrity(repository) -> None:
    service = DatabaseAdminService(repository.database.path)
    tables = {item["name"] for item in service.tables()}
    assert {"projects", "tasks", "hips", "ui_state"} <= tables
    page = service.rows("projects", search="missing")
    assert page["columns"][0] == "project_id"
    filename, payload = service.export("projects", "json")
    assert filename.endswith(".json")
    assert payload.startswith(b"[")
    backup = service.backup()
    assert backup.is_file()
    assert service.integrity_check() == ["ok"]


def test_admin_only_clears_allowed_tables(repository) -> None:
    service = DatabaseAdminService(repository.database.path)
    repository.record_activity("project", "test")
    assert service.clear_history("activity_history") == 1
    try:
        service.clear_history("projects")
    except ValueError as exc:
        assert "history" in str(exc)
    else:
        raise AssertionError("Canonical index table deletion must be rejected")
