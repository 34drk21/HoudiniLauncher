from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .validation import (
    validate_environment_name,
    validate_filename_component,
    validate_relative_path,
)


def utc_now() -> datetime:
    """Return the current timezone-aware UTC time."""
    return datetime.now(timezone.utc)


class StrictModel(BaseModel):
    """Base model shared by persisted HouD2 settings."""

    model_config = ConfigDict(extra="forbid", validate_assignment=True)


class FolderDefinition(StrictModel):
    """A role-based folder below a task's Houdini directory."""

    key: str
    display_name: str
    role: str
    relative_path: str
    auto_create: bool = True
    enabled: bool = True

    @field_validator("key", "role")
    @classmethod
    def validate_identifier(cls, value: str) -> str:
        return validate_filename_component(value, "Folder key or role")

    @field_validator("relative_path")
    @classmethod
    def validate_path(cls, value: str) -> str:
        return validate_relative_path(value, "Folder relative path")


class FrameSettings(StrictModel):
    """Task frame variables exposed to Houdini."""

    start: int = 1001
    end: int = 1100
    fps: float = Field(default=60.0, gt=0)
    sim_start: int = 1001

    @model_validator(mode="after")
    def validate_range(self) -> "FrameSettings":
        if self.end < self.start:
            raise ValueError("End frame must be greater than or equal to start frame")
        if self.sim_start > self.end:
            raise ValueError("Simulation start frame cannot be after the end frame")
        return self


class NamingSettings(StrictModel):
    """HIP filename generation rules."""

    hip_template: str = "{task}_v{version:03d}_{user}.{extension}"
    version_padding: int = Field(default=3, ge=2, le=8)
    default_extension: Literal["hip", "hiplc", "hipnc"] = "hip"

    @field_validator("hip_template")
    @classmethod
    def validate_template(cls, value: str) -> str:
        required = {"{task}", "{version"}
        if "{task}" not in value or "{version" not in value:
            raise ValueError("HIP template must contain {task} and {version}")
        if "/" in value or "\\" in value:
            raise ValueError("HIP template cannot contain path separators")
        return value


class SearchPathSettings(StrictModel):
    """Project-level Houdini search path templates."""

    hda: list[str] = Field(default_factory=list)
    python: list[str] = Field(default_factory=list)
    scripts: list[str] = Field(default_factory=list)
    toolbar: list[str] = Field(default_factory=list)
    icons: list[str] = Field(default_factory=list)
    packages: list[str] = Field(default_factory=list)


class HoudiniPolicy(StrictModel):
    """Project Houdini selection and startup policy."""

    default_installation_id: str | None = None
    allow_version_override: bool = True
    fallback_policy: Literal[
        "require_exact",
        "same_major_minor",
        "newer_compatible",
        "always_ask",
    ] = "always_ask"
    set_job_to_houdini_root: bool = True
    apply_project_fps: bool = True
    apply_task_frame_range: bool = True
    thumbnail_capture_policy: Literal["manual", "latest", "placeholder"] = "manual"


class ProjectSettings(StrictModel):
    """Canonical JSON settings for one HouD2 project."""

    format: Literal["houd2.project_settings"] = "houd2.project_settings"
    schema_version: Literal[1] = 1
    project_id: str = Field(default_factory=lambda: str(uuid4()))
    name: str
    description: str = ""
    project_root: Path
    default_frames: FrameSettings = Field(default_factory=FrameSettings)
    folders: list[FolderDefinition] = Field(
        default_factory=lambda: [
            FolderDefinition(
                key="geo", display_name="Geometry", role="geo_cache", relative_path="geo"
            ),
            FolderDefinition(
                key="abc", display_name="Alembic", role="alembic", relative_path="abc"
            ),
            FolderDefinition(
                key="export", display_name="Export", role="export", relative_path="export"
            ),
        ]
    )
    environment: dict[str, str] = Field(default_factory=dict)
    search_paths: SearchPathSettings = Field(default_factory=SearchPathSettings)
    naming: NamingSettings = Field(default_factory=NamingSettings)
    houdini: HoudiniPolicy = Field(default_factory=HoudiniPolicy)
    sdm_default_folder_roles: list[str] | None = None
    created_at: datetime = Field(default_factory=utc_now)
    modified_at: datetime = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_filename_component(value, "Project name")

    @field_validator("project_root")
    @classmethod
    def validate_root(cls, value: Path) -> Path:
        expanded = value.expanduser()
        if not expanded.is_absolute():
            raise ValueError("Project root must be absolute")
        return expanded.resolve()

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: dict[str, str]) -> dict[str, str]:
        return {validate_environment_name(name): str(item) for name, item in value.items()}

    @model_validator(mode="after")
    def validate_folders(self) -> "ProjectSettings":
        roles = [folder.role.casefold() for folder in self.folders if folder.enabled]
        paths = [folder.relative_path.casefold() for folder in self.folders if folder.enabled]
        if len(roles) != len(set(roles)):
            raise ValueError("Folder roles must be unique")
        if len(paths) != len(set(paths)):
            raise ValueError("Folder relative paths must be unique")
        return self


class TaskSettings(StrictModel):
    """Canonical JSON settings for one task."""

    format: Literal["houd2.task_settings"] = "houd2.task_settings"
    schema_version: Literal[1] = 1
    task_id: str = Field(default_factory=lambda: str(uuid4()))
    project_id: str
    name: str
    description: str = ""
    status: Literal["active", "on_hold", "complete", "archived"] = "active"
    owner: str = ""
    frames: FrameSettings = Field(default_factory=FrameSettings)
    environment: dict[str, str] = Field(default_factory=dict)
    recommended_installation_id: str | None = None
    created_at: datetime = Field(default_factory=utc_now)
    modified_at: datetime = Field(default_factory=utc_now)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        return validate_filename_component(value, "Task name")

    @field_validator("environment")
    @classmethod
    def validate_environment(cls, value: dict[str, str]) -> dict[str, str]:
        return {validate_environment_name(name): str(item) for name, item in value.items()}


class HipMetadata(StrictModel):
    """Launcher-managed metadata associated with one HIP file."""

    format: Literal["houd2.hip_metadata"] = "houd2.hip_metadata"
    schema_version: Literal[1] = 1
    task_id: str
    hip_file: str
    hip_version: int = Field(ge=1)
    created_by: str
    created_at: datetime = Field(default_factory=utc_now)
    last_opened_with: str | None = None
    last_saved_with: str | None = None
    recommended_installation_id: str | None = None
    comment: str = ""
    thumbnail: str | None = None
    read_only_copy: bool = False

    @field_validator("hip_file")
    @classmethod
    def validate_hip_file(cls, value: str) -> str:
        filename = validate_filename_component(value, "HIP filename")
        if Path(filename).suffix.lower() not in {".hip", ".hiplc", ".hipnc"}:
            raise ValueError("Unsupported HIP extension")
        return filename


class HoudiniInstallation(StrictModel):
    """A detected or manually registered Houdini installation."""

    installation_id: str = Field(default_factory=lambda: str(uuid4()))
    display_name: str
    major: int = Field(ge=0)
    minor: int = Field(ge=0)
    build: int = Field(ge=0)
    version_string: str
    install_root: Path
    houdini_executable: Path
    hython_executable: Path | None = None
    hbatch_executable: Path | None = None
    license_type: str = "Unknown"
    source: Literal["auto", "registry", "manual"] = "auto"
    enabled: bool = True
    is_valid: bool = True
    last_checked: datetime = Field(default_factory=utc_now)

    @property
    def version_tuple(self) -> tuple[int, int, int]:
        """Return a sortable semantic Houdini build tuple."""
        return self.major, self.minor, self.build


class LauncherSettings(StrictModel):
    """Per-user launcher settings stored outside projects."""

    format: Literal["houd2.launcher_settings"] = "houd2.launcher_settings"
    schema_version: Literal[1] = 1
    user_id: str = Field(default_factory=lambda: str(uuid4()))
    machine_id: str = Field(default_factory=lambda: str(uuid4()))
    onboarding_completed: bool = False
    display_name: str = ""
    initials: str = ""
    remember_last_project: bool = True
    remember_last_task: bool = True
    open_latest_on_double_click: bool = True
    show_open_dialog: bool = True
    auto_refresh: bool = True
    language: str = "ja"
    default_project_root: Path | None = None
    launcher_environment: dict[str, str] = Field(default_factory=dict)
    installations: list[HoudiniInstallation] = Field(default_factory=list)
    default_installation_id: str | None = None
    recent_project_limit: int = Field(default=20, ge=1, le=100)
    task_view_mode: Literal["cards", "compact", "detailed"] = "cards"
    theme: Literal["system", "light", "dark"] = "dark"
    thumbnail_size: int = Field(default=220, ge=96, le=512)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    maximum_log_files: int = Field(default=10, ge=1, le=100)
    last_project_id: str | None = None
    last_task_id: str | None = None
    cache_exchange_paths: dict[str, str] = Field(default_factory=dict)
    update_channel_path: Path | None = None
    auto_check_updates: bool = True
    last_update_check_at: datetime | None = None

    @field_validator("launcher_environment")
    @classmethod
    def validate_environment(cls, value: dict[str, str]) -> dict[str, str]:
        return {validate_environment_name(name): str(item) for name, item in value.items()}

    @field_validator("default_project_root", "update_channel_path")
    @classmethod
    def validate_optional_absolute_path(cls, value: Path | None) -> Path | None:
        if value is None:
            return None
        expanded = value.expanduser()
        if not expanded.is_absolute():
            raise ValueError("Launcher paths must be absolute")
        return expanded


class SettingsPackage(StrictModel):
    """Portable settings package for project or task import/export."""

    format: Literal["houd2.settings_package"] = "houd2.settings_package"
    schema_version: Literal[1, 2] = 2
    scope: Literal["project", "task"]
    source_id: str | None = None
    source_name: str | None = None
    source_project_id: str | None = None
    source_project_name: str | None = None
    exported_at: datetime = Field(default_factory=utc_now)
    sections: dict[str, object]

    @model_validator(mode="after")
    def validate_source_identity(self) -> "SettingsPackage":
        if self.schema_version == 2:
            if not self.source_id or not self.source_name:
                raise ValueError("Settings package v2 requires source ID and name")
            if self.scope == "task" and not self.source_project_id:
                raise ValueError("Task settings package v2 requires source Project ID")
        return self
