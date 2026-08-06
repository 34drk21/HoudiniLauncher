from __future__ import annotations

from houd2launcher.core.config import atomic_write_model, load_model
from houd2launcher.core.filesystem_reconciler import FilesystemReconciler
from houd2launcher.core.hip_manager import HipManager
from houd2launcher.core.models import HipMetadata, ProjectSettings
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.core.project_manager import ProjectManager
from houd2launcher.core.task_manager import TaskManager
from houd2launcher.database.repositories import LauncherRepository


def _reconciler(
    repository: LauncherRepository, resolver: PathResolver
) -> FilesystemReconciler:
    tasks = TaskManager(repository, resolver)
    return FilesystemReconciler(tasks, HipManager(repository, resolver), resolver)


def test_external_task_folder_is_detected_then_adopted(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    external = project.project_root / "fire"
    external.mkdir()
    (external / "artist_note.txt").write_text("keep", encoding="utf-8")
    reconciler = _reconciler(repository, resolver)

    report = reconciler.reconcile(project)
    assert report.task_candidates == ("fire",)

    task = reconciler.adopt_task(project, "fire", "QA Artist")
    report = reconciler.reconcile(project)
    assert [item.name for item in report.tasks] == ["fire"]
    assert task.owner == "QA Artist"
    assert task.frames == project.default_frames
    assert (external / "artist_note.txt").read_text(encoding="utf-8") == "keep"
    assert resolver.resolve_task_metadata_path(project, task).is_file()


def test_external_hip_creates_and_repairs_metadata(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    reconciler = _reconciler(repository, resolver)
    (project.project_root / "fire").mkdir()
    task = reconciler.adopt_task(project, "fire", "QA")
    hip = resolver.resolve_houdini_root(project, task) / "fire_v001_QA.hip"
    hip.write_bytes(b"hip")

    report = reconciler.reconcile(project)
    metadata_path = resolver.resolve_hip_metadata_path(project, task, hip)
    metadata = load_model(metadata_path, HipMetadata)
    assert report.hip_count == 1
    assert metadata.task_id == task.task_id
    assert metadata.hip_file == hip.name

    metadata.task_id = "copied-task-id"
    metadata.hip_file = "old_name.hip"
    metadata.hip_version = 99
    atomic_write_model(metadata_path, metadata)
    reconciler.reconcile(project)
    repaired = load_model(metadata_path, HipMetadata)
    assert repaired.task_id == task.task_id
    assert repaired.hip_file == hip.name
    assert repaired.hip_version == 1


def test_malformed_task_json_is_reported_without_overwrite(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    config = project.project_root / "broken" / ".houd2" / "task.json"
    config.parent.mkdir(parents=True)
    config.write_text("not-json", encoding="utf-8")

    report = _reconciler(repository, resolver).reconcile(project)

    assert report.tasks == ()
    assert len(report.errors) == 1
    assert config.read_text(encoding="utf-8") == "not-json"


def test_reconcile_repairs_task_project_id(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    reconciler = _reconciler(repository, resolver)
    (project.project_root / "smoke").mkdir()
    task = reconciler.adopt_task(project, "smoke", "QA")

    # Change task project_id in task.json to simulate an imported/old project ID
    config_path = resolver.resolve_task_metadata_path(project, task)
    task.project_id = "old-project-id"
    atomic_write_model(config_path, task)

    # Reconciling should repair project_id and load the task cleanly
    report = reconciler.reconcile(project)
    assert len(report.tasks) == 1
    assert report.tasks[0].name == "smoke"
    assert report.tasks[0].project_id == project.project_id


def test_reconcile_autoadopts_folders_with_houdini_or_hip(
    project: ProjectSettings,
    repository: LauncherRepository,
    resolver: PathResolver,
) -> None:
    ProjectManager(repository, resolver).create(project)
    reconciler = _reconciler(repository, resolver)

    # Folder with houdini subdirectory
    existing_folder = project.project_root / "existing_shot"
    (existing_folder / "houdini").mkdir(parents=True)
    (existing_folder / "houdini" / "existing_v001.hip").write_bytes(b"hip")

    report = reconciler.reconcile(project)
    assert any(task.name == "existing_shot" for task in report.tasks)

