from __future__ import annotations

import os
import re
import logging
from collections.abc import Mapping
from pathlib import Path

from .exceptions import EnvironmentResolutionError
from .models import HoudiniInstallation, ProjectSettings, TaskSettings
from .path_resolver import PathResolver
from .validation import validate_environment_name


TOKEN_PATTERN = re.compile(r"\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)(?::(?P<arg>[^{}]+))?\}")
SEARCH_PATH_VARIABLES = {
    "hda": "HOUDINI_OTLSCAN_PATH",
    "python": "PYTHONPATH",
    "scripts": "HOUDINI_PATH",
    "toolbar": "HOUDINI_TOOLBAR_PATH",
    "icons": "HOUDINI_ICON_PATH",
    "packages": "HOUDINI_PACKAGE_DIR",
}
HOUDINI_AMPERSAND_PATHS = {
    "HOUDINI_OTLSCAN_PATH",
    "HOUDINI_PATH",
    "HOUDINI_TOOLBAR_PATH",
    "HOUDINI_ICON_PATH",
}
PYTHON_ENVIRONMENT_BLOCKLIST = {"PYTHONHOME", "PYTHONUSERBASE", "PYTHONSTARTUP"}
HDA_LIBRARY_SUFFIXES = {".hda", ".otl", ".hdalc", ".hdanc", ".otllc", ".otlnc"}


LOGGER = logging.getLogger(__name__)


class EnvironmentResolver:
    """Build a deterministic Houdini subprocess environment from layered settings."""

    def __init__(self, path_resolver: PathResolver) -> None:
        self.path_resolver = path_resolver

    def build(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        installation: HoudiniInstallation,
        launcher_environment: Mapping[str, str] | None = None,
        open_overrides: Mapping[str, str] | None = None,
        base_environment: Mapping[str, str] | None = None,
        launcher_root: str = "",
        hip_path: str = "",
        user: str = "",
        user_id: str = "",
        machine_id: str = "",
        api_url: str = "",
        api_token: str = "",
        managed_hda_root: str = "",
        managed_hda_version: str = "",
    ) -> dict[str, str]:
        """Resolve environment layers and append protected HOUD2 variables last."""
        environment = dict(base_environment if base_environment is not None else os.environ)
        for name in PYTHON_ENVIRONMENT_BLOCKLIST:
            environment.pop(name, None)
        environment.update(
            self.expression_environment(
                project,
                task,
                installation,
                launcher_environment=launcher_environment,
                open_overrides=open_overrides,
                inherited_environment=environment,
                launcher_root=launcher_root,
                hip_path=hip_path,
                user=user,
                user_id=user_id,
                machine_id=machine_id,
                api_url=api_url,
                managed_hda_root=managed_hda_root,
                managed_hda_version=managed_hda_version,
            )
        )
        if api_token:
            environment["HOUD2_API_TOKEN"] = api_token
        return environment

    def expression_environment(
        self,
        project: ProjectSettings,
        task: TaskSettings,
        installation: HoudiniInstallation | None = None,
        launcher_environment: Mapping[str, str] | None = None,
        open_overrides: Mapping[str, str] | None = None,
        inherited_environment: Mapping[str, str] | None = None,
        launcher_root: str = "",
        hip_path: str = "",
        user: str = "",
        user_id: str = "",
        machine_id: str = "",
        api_url: str = "",
        managed_hda_root: str = "",
        managed_hda_version: str = "",
    ) -> dict[str, str]:
        """Return launcher-managed variables available to Houdini expressions."""
        environment = {
            name: str(inherited_environment[name])
            for name in SEARCH_PATH_VARIABLES.values()
            if inherited_environment and name in inherited_environment
        }
        user_layers = [
            launcher_environment or {},
            project.environment,
            task.environment,
            open_overrides or {},
        ]
        merged: dict[str, str] = {}
        for layer in user_layers:
            for name, value in layer.items():
                try:
                    safe_name = validate_environment_name(name)
                except ValueError as exc:
                    raise EnvironmentResolutionError(str(exc)) from exc
                merged[safe_name] = str(value)

        context = self._context(project, task, user)
        resolved = self._resolve_variables(merged, context, project, task)
        environment.update(resolved)
        self._apply_search_paths(environment, project, task, context)
        self._apply_houd2_paths(environment, launcher_root, managed_hda_root)
        if project.houdini.set_job_to_houdini_root:
            environment["JOB"] = str(self.path_resolver.resolve_houdini_root(project, task))
        environment.update(self._frame_variables(task))
        environment.update(
            {
                "HOUD2_PROJECT_ID": project.project_id,
                "HOUD2_PROJECT_ROOT": str(project.project_root),
                "HOUD2_TASK_ID": task.task_id,
                "HOUD2_TASK_NAME": task.name,
                "HOUD2_TASK_ROOT": str(
                    self.path_resolver.resolve_task_root(project, task.name)
                ),
                "HOUD2_HOUDINI_ROOT": str(
                    self.path_resolver.resolve_houdini_root(project, task)
                ),
                "HOUD2_GEO_ROOT": str(
                    self.path_resolver.resolve_role(project, task, "geo_cache")
                ),
                "HOUD2_HIP_PATH": hip_path,
                "HOUD2_USER": user,
                "HOUD2_USER_ID": user_id,
                "HOUD2_MACHINE_ID": machine_id,
                "HOUD2_API_URL": api_url,
                "HOUD2_LAUNCHER_ROOT": launcher_root,
                "HOUD2_HDA_ROOT": managed_hda_root,
                "HOUD2_HDA_VERSION": managed_hda_version,
                "HOUD2_HOUDINI_VERSION": (
                    f"{installation.major}.{installation.minor}" if installation else ""
                ),
                "HOUD2_HOUDINI_BUILD": str(installation.build) if installation else "",
                "HOUD2_APPLY_PROJECT_FPS": "1" if project.houdini.apply_project_fps else "0",
                "HOUD2_APPLY_TASK_FRAME_RANGE": (
                    "1" if project.houdini.apply_task_frame_range else "0"
                ),
            }
        )
        return environment

    @staticmethod
    def _apply_houd2_paths(
        environment: dict[str, str], launcher_root: str, managed_hda_root: str
    ) -> None:
        if not launcher_root and not managed_hda_root:
            return
        integrations: dict[str, list[str]] = {
            "HOUDINI_OTLSCAN_PATH": [],
            "PYTHONPATH": [],
        }
        if managed_hda_root:
            managed = os.path.abspath(managed_hda_root)
            integrations["HOUDINI_OTLSCAN_PATH"].extend(
                expand_hda_search_roots([os.path.join(managed, "otls")])
            )
            integrations["PYTHONPATH"].append(os.path.join(managed, "python"))
        if launcher_root:
            root = os.path.abspath(launcher_root)
            integrations["HOUDINI_OTLSCAN_PATH"].extend(
                expand_hda_search_roots([os.path.join(root, "houdini", "otls")])
            )
            integrations["PYTHONPATH"].append(os.path.join(root, "houdini", "python"))
        for variable, paths in integrations.items():
            values = list(paths)
            existing = environment.get(variable, "")
            if existing:
                values.append(existing)
            if variable in HOUDINI_AMPERSAND_PATHS and "&" not in values:
                values.append("&")
            environment[variable] = os.pathsep.join(values)

    def _context(
        self, project: ProjectSettings, task: TaskSettings, user: str
    ) -> dict[str, str]:
        return {
            "project": project.name,
            "project_name": project.name,
            "project_root": str(project.project_root),
            "task": task.name,
            "task_name": task.name,
            "task_root": str(self.path_resolver.resolve_task_root(project, task.name)),
            "houdini_root": str(self.path_resolver.resolve_houdini_root(project, task)),
            "user": user,
        }

    def _resolve_variables(
        self,
        values: Mapping[str, str],
        context: Mapping[str, str],
        project: ProjectSettings,
        task: TaskSettings,
    ) -> dict[str, str]:
        resolved: dict[str, str] = {}
        visiting: set[str] = set()

        def resolve_name(name: str) -> str:
            if name in resolved:
                return resolved[name]
            if name in visiting:
                chain = " -> ".join([*sorted(visiting), name])
                raise EnvironmentResolutionError(f"Environment variable cycle: {chain}")
            if name not in values:
                raise EnvironmentResolutionError(f"Unknown environment token: {name}")
            visiting.add(name)
            resolved[name] = expand(values[name])
            visiting.remove(name)
            return resolved[name]

        def replace(match: re.Match[str]) -> str:
            name = match.group("name")
            argument = match.group("arg")
            if name == "role":
                if not argument:
                    raise EnvironmentResolutionError("Role token requires a folder role")
                try:
                    return str(self.path_resolver.resolve_role(project, task, argument))
                except KeyError as exc:
                    raise EnvironmentResolutionError(str(exc)) from exc
            if argument is not None:
                raise EnvironmentResolutionError(f"Unsupported template token: {match.group(0)}")
            if name in context:
                return context[name]
            return resolve_name(name)

        def expand(value: str) -> str:
            previous = value
            for _ in range(100):
                current = TOKEN_PATTERN.sub(replace, previous)
                if current == previous:
                    return current
                previous = current
            raise EnvironmentResolutionError("Environment template expansion exceeded its limit")

        for variable_name in values:
            resolve_name(variable_name)
        return resolved

    def _apply_search_paths(
        self,
        environment: dict[str, str],
        project: ProjectSettings,
        task: TaskSettings,
        context: Mapping[str, str],
    ) -> None:
        for field_name, variable_name in SEARCH_PATH_VARIABLES.items():
            templates = getattr(project.search_paths, field_name)
            if not templates:
                continue
            paths = [self._expand_context(template, context, project, task) for template in templates]
            if field_name == "hda":
                paths = expand_hda_search_roots(paths)
            existing = environment.get(variable_name, "")
            if existing:
                paths.append(existing)
            if variable_name in HOUDINI_AMPERSAND_PATHS and "&" not in paths:
                paths.append("&")
            environment[variable_name] = os.pathsep.join(paths)

    def _expand_context(
        self,
        template: str,
        context: Mapping[str, str],
        project: ProjectSettings,
        task: TaskSettings,
    ) -> str:
        def replace(match: re.Match[str]) -> str:
            name = match.group("name")
            argument = match.group("arg")
            if name == "role" and argument:
                return str(self.path_resolver.resolve_role(project, task, argument))
            if name in context and argument is None:
                return context[name]
            raise EnvironmentResolutionError(f"Unknown search path token: {match.group(0)}")

        return TOKEN_PATTERN.sub(replace, template)

    @staticmethod
    def _frame_variables(task: TaskSettings) -> dict[str, str]:
        return {
            "TASK_NAME": task.name,
            "SHOT_FRAME_START": str(task.frames.start),
            "SHOT_FRAME_END": str(task.frames.end),
            "SHOT_FPS": str(task.frames.fps),
            "SIM_FRAME_START": str(task.frames.sim_start),
            "SHOTSTARTFRAME": str(task.frames.start),
            "SHOTENDFRAME": str(task.frames.end),
            "SHOTFPS": str(task.frames.fps),
            "SIMSTARTFRAME": str(task.frames.sim_start),
        }


def expand_hda_search_roots(roots: list[str]) -> list[str]:
    """Return directories containing HDA libraries below configured roots."""
    found: list[Path] = []
    seen: set[str] = set()
    for value in roots:
        if not value or value == "&":
            continue
        root = Path(value).expanduser()
        try:
            root = root.resolve()
        except OSError as exc:
            LOGGER.warning("Cannot resolve HDA search root %s: %s", value, exc)
            continue
        if not root.is_dir():
            LOGGER.warning("HDA search root is unavailable: %s", root)
            continue
        pending = [root]
        while pending:
            directory = pending.pop()
            if _is_linked_directory(directory):
                LOGGER.warning("Skipping linked HDA directory: %s", directory)
                continue
            try:
                entries = sorted(directory.iterdir(), key=lambda item: item.name.casefold())
            except OSError as exc:
                LOGGER.warning("Cannot scan HDA directory %s: %s", directory, exc)
                continue
            contains_library = False
            for entry in entries:
                try:
                    if (
                        entry.is_file()
                        and entry.suffix.casefold() in HDA_LIBRARY_SUFFIXES
                    ):
                        contains_library = True
                        break
                except OSError as exc:
                    LOGGER.warning("Cannot inspect HDA library %s: %s", entry, exc)
            if contains_library:
                key = os.path.normcase(os.path.normpath(str(directory)))
                if key not in seen:
                    seen.add(key)
                    found.append(directory)
            children: list[Path] = []
            for entry in entries:
                try:
                    if entry.is_dir() and not _is_linked_directory(entry):
                        children.append(entry)
                except OSError as exc:
                    LOGGER.warning("Cannot inspect HDA path %s: %s", entry, exc)
            pending.extend(reversed(children))
    found.sort(key=lambda path: (len(path.parts), str(path).casefold()))
    return [str(path) for path in found]


def _is_linked_directory(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if callable(is_junction) and is_junction():
        return True
    try:
        attributes = getattr(path.stat(follow_symlinks=False), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & 0x400)
