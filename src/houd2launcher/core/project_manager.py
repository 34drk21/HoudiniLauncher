from __future__ import annotations

from pathlib import Path

from .config import atomic_write_model, load_model
from .exceptions import DuplicateRegistrationError
from .models import ProjectSettings, utc_now
from .path_resolver import PathResolver
from ..database.repositories import LauncherRepository


class ProjectManager:
    """Create, register, load, and update canonical project settings."""

    def __init__(self, repository: LauncherRepository, resolver: PathResolver) -> None:
        self.repository = repository
        self.resolver = resolver

    def create(self, settings: ProjectSettings) -> ProjectSettings:
        """Create a project root and register its canonical JSON settings."""
        config_path = self.resolver.resolve_project_metadata_path(settings)
        if config_path.exists():
            raise FileExistsError(f"Project already exists: {config_path}")
        settings.project_root.mkdir(parents=True, exist_ok=True)
        atomic_write_model(config_path, settings)
        self.repository.upsert_project(
            settings.project_id, settings.name, settings.project_root, config_path
        )
        self.repository.record_activity(settings.project_id, "project_created")
        return settings

    def add_existing(self, project_root: Path) -> ProjectSettings:
        """Register an existing HouD2 project without modifying its files."""
        config_path = project_root.expanduser().resolve() / ".houd2" / "project.json"
        settings = load_model(config_path, ProjectSettings)
        existing = self.repository.list_projects(include_archived=True)
        if any(item["project_id"] == settings.project_id for item in existing):
            raise DuplicateRegistrationError(f"Project is already registered: {settings.name}")
        stale = self._stale_registration(existing, settings, config_path)
        if stale:
            self.repository.replace_project_registration(
                str(stale["project_id"]),
                settings.project_id,
                settings.name,
                settings.project_root,
                config_path,
            )
            return settings
        self.repository.upsert_project(
            settings.project_id, settings.name, settings.project_root, config_path
        )
        return settings

    def load(self, config_path: Path) -> ProjectSettings:
        """Load project JSON and refresh its SQLite index entry."""
        settings = load_model(config_path, ProjectSettings)
        self.repository.upsert_project(
            settings.project_id, settings.name, settings.project_root, config_path
        )
        return settings

    def save(self, settings: ProjectSettings) -> Path:
        """Atomically save canonical project settings and refresh the index."""
        settings.modified_at = utc_now()
        path = self.resolver.resolve_project_metadata_path(settings)
        atomic_write_model(path, settings)
        self.repository.upsert_project(
            settings.project_id, settings.name, settings.project_root, path
        )
        self.repository.record_activity(settings.project_id, "project_settings_changed")
        return path

    def unregister(self, project_id: str) -> None:
        """Remove only the launcher registration, preserving all project files."""
        self.repository.remove_project(project_id)

    def registered(self) -> list[ProjectSettings]:
        """Return valid registered projects, treating JSON as authoritative."""
        projects: list[ProjectSettings] = []
        for record in self.repository.list_projects():
            config_path = Path(record["config_path"])
            if not config_path.is_file():
                continue
            settings = load_model(config_path, ProjectSettings)
            if settings.project_id != record["project_id"]:
                stale = self._stale_registration([record], settings, config_path)
                if not stale:
                    raise DuplicateRegistrationError(
                        f"Project registration conflicts with its settings: {settings.name}"
                    )
                self.repository.replace_project_registration(
                    str(record["project_id"]),
                    settings.project_id,
                    settings.name,
                    settings.project_root,
                    config_path,
                )
            projects.append(settings)
        return projects

    @staticmethod
    def _stale_registration(
        records: list[dict[str, object]],
        settings: ProjectSettings,
        config_path: Path,
    ) -> dict[str, object] | None:
        """Find a different ID pointing at the same Root and canonical JSON file."""
        expected_root = settings.project_root.resolve()
        expected_config = config_path.resolve()
        for record in records:
            try:
                root_matches = Path(str(record["root"])).resolve() == expected_root
                config_matches = (
                    Path(str(record["config_path"])).resolve() == expected_config
                )
            except (KeyError, OSError):
                continue
            if root_matches and config_matches and record.get("project_id") != settings.project_id:
                return record
        return None
