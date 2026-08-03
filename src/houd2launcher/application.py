from __future__ import annotations

import getpass
import logging
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from .core.config import atomic_write_model, launcher_home, load_model
from .core.cache_manager import CacheManager
from .core.cache_exchange import CacheExchangeService
from .core.cache_catalog import CacheCatalogService
from .core.environment import EnvironmentResolver
from .core.filesystem_reconciler import FilesystemReconciler
from .core.folder_migration import FolderStructureMigrator
from .core.hip_manager import HipManager
from .core.models import LauncherSettings
from .core.path_resolver import PathResolver
from .core.project_manager import ProjectManager
from .core.task_manager import TaskManager
from .core.task_package import TaskPackageService
from .core.sdm_package import SdmPackageService
from .database.connection import Database
from .database.migrations import migrate
from .database.repositories import LauncherRepository
from .houdini.launcher import HoudiniLauncher
from .houdini.cache_scanner import HoudiniCacheScanner
from .api.catalog_server import CatalogApiServer


@dataclass(slots=True)
class ApplicationContext:
    """Dependency container shared by the UI and background workers."""

    root: Path
    data_home: Path
    settings_path: Path
    settings: LauncherSettings
    database: Database
    repository: LauncherRepository
    resolver: PathResolver
    environment: EnvironmentResolver
    folder_migrator: FolderStructureMigrator
    filesystem: FilesystemReconciler
    projects: ProjectManager
    tasks: TaskManager
    hips: HipManager
    houdini: HoudiniLauncher
    caches: CacheManager
    cache_exchange: CacheExchangeService
    cache_scanner: HoudiniCacheScanner
    task_packages: TaskPackageService
    sdm_packages: SdmPackageService
    cache_catalog: CacheCatalogService
    catalog_api: CatalogApiServer

    @classmethod
    def create(cls, root: Path) -> "ApplicationContext":
        """Initialize settings, SQLite migrations, services, and logging."""
        data_home = launcher_home()
        data_home.mkdir(parents=True, exist_ok=True)
        settings_path = data_home / "settings.json"
        if settings_path.is_file():
            settings = load_model(settings_path, LauncherSettings)
            # Persist additive defaults such as machine_id after older settings load.
            atomic_write_model(settings_path, settings)
        else:
            username = getpass.getuser()
            initials = "".join(part[:1] for part in username.split()).upper()[:4]
            settings = LauncherSettings(display_name=username, initials=initials)
            atomic_write_model(settings_path, settings)
        _configure_logging(data_home, settings)
        database = Database(data_home / "houd2launcher.db")
        migrate(database)
        repository = LauncherRepository(database)
        resolver = PathResolver()
        hip_manager = HipManager(repository, resolver)
        environment = EnvironmentResolver(resolver)
        cache_manager = CacheManager(resolver)
        task_manager = TaskManager(repository, resolver)
        projects = ProjectManager(repository, resolver)
        folder_migrator = FolderStructureMigrator(resolver)
        filesystem = FilesystemReconciler(task_manager, hip_manager, resolver)
        cache_exchange = CacheExchangeService(resolver)
        catalog = CacheCatalogService(
            projects, task_manager, resolver, cache_exchange=cache_exchange,
            exchange_paths=lambda: settings.cache_exchange_paths,
        )
        catalog_api = CatalogApiServer(catalog)
        catalog_api.start()
        return cls(
            root=root.resolve(),
            data_home=data_home,
            settings_path=settings_path,
            settings=settings,
            database=database,
            repository=repository,
            resolver=resolver,
            environment=environment,
            folder_migrator=folder_migrator,
            filesystem=filesystem,
            projects=projects,
            tasks=task_manager,
            hips=hip_manager,
            houdini=HoudiniLauncher(
                environment,
                hip_manager,
                repository,
                root,
                api_url=catalog_api.url,
                api_token=catalog_api.token,
            ),
            caches=cache_manager,
            cache_exchange=cache_exchange,
            cache_scanner=HoudiniCacheScanner(
                environment,
                cache_manager,
                root,
                api_url=catalog_api.url,
                api_token=catalog_api.token,
            ),
            task_packages=TaskPackageService(resolver, task_manager),
            sdm_packages=SdmPackageService(resolver),
            cache_catalog=catalog,
            catalog_api=catalog_api,
        )

    def save_settings(self) -> Path:
        """Atomically persist launcher settings."""
        return atomic_write_model(self.settings_path, self.settings)

    def shutdown(self) -> None:
        """Stop background localhost services owned by the Launcher."""
        self.catalog_api.stop()


def _configure_logging(data_home: Path, settings: LauncherSettings) -> None:
    log_root = data_home / "logs"
    log_root.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(
        log_root / "houd2launcher.log",
        maxBytes=2 * 1024 * 1024,
        backupCount=settings.maximum_log_files,
        encoding="utf-8",
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    root_logger = logging.getLogger()
    root_logger.setLevel(getattr(logging, settings.log_level))
    if not any(isinstance(item, RotatingFileHandler) for item in root_logger.handlers):
        root_logger.addHandler(handler)
