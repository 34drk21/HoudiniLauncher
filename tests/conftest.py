from __future__ import annotations

from pathlib import Path

import pytest

from houd2launcher.core.models import ProjectSettings
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.database.connection import Database
from houd2launcher.database.migrations import migrate
from houd2launcher.database.repositories import LauncherRepository


@pytest.fixture
def resolver() -> PathResolver:
    return PathResolver()


@pytest.fixture
def repository(tmp_path: Path) -> LauncherRepository:
    database = Database(tmp_path / "index.db")
    migrate(database)
    return LauncherRepository(database)


@pytest.fixture
def project(tmp_path: Path) -> ProjectSettings:
    return ProjectSettings(name="DemoProject", project_root=tmp_path / "DemoProject")

