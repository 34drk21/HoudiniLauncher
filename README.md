# HouD2Launcher

HouD2Launcher is a local-first standalone desktop launcher for SideFX Houdini.
It manages projects, tasks, HIP versions, Houdini installations, launch
environments, thumbnails, and portable JSON settings without requiring Houdini
to be running.

This repository implements Product Requirements Document v0.2. It is an
independent implementation and does not use Prism APIs or Prism source code.

## Handbook

Open the searchable Japanese handbook for artists, supervisors, and developers:

- [HouD2Launcher Handbook](docs/houd2-handbook.html)
- Or double-click `open_houd2_handbook.bat` on Windows.

## Scope

Included:

- Multiple local projects and task folders
- Configurable role-based folders below each task's `houdini` directory
- `.hip`, `.hiplc`, and `.hipnc` discovery and versioning
- Launcher-managed HIP metadata and read-only opening
- Houdini installation detection and manual registration
- Explicit Houdini version selection and compatibility warnings
- Layered environment variables and Houdini search paths
- Project and task settings import/export with preview and backup
- SQLite indexes, activity history, open history, and UI state
- Task thumbnails from JPG or PNG images
- Selected-HIP cache reference scanning through `hython`
- Full `geo_cache` inventory grouped by Cache and Version, with HIP usage colors
- Cache search, filters, size sorting, and guarded permanent Version deletion
- Checksum-verified, cache-free Task Package folder export/import with Preview
- Launcher-managed expression variables shown in each Task Overview
- FPS and global/playback frame ranges applied after a HIP opens
- `houd2::cache_out::1.0` HDA with atomic Version publishing and metadata Marker
- `houd2::cache_in::1.0` HDA with Project, Task, Cache, and Version menus
- Localhost Cache Catalog API with creator and storage metadata
- Independent administrator database browser with guarded maintenance actions

Not included in this project:

- SFTP/FTPS integration
- Houdini shelf tools or Python panels
- Render farm integration

Network cache synchronization remains a future provider. Cache In never performs
network transfers during a SOP cook.

## Houdini Cache HDAs

Houdini launched through HouD2Launcher automatically receives the bundled HDA
and Python search paths. Create `HouD2 Cache Out` after the geometry to publish:

```text
{geo_cache}/{cache_name}/v003/
|-- geo/{cache_name}.$F4.bgeo.sc
|-- cache_manifest.json
`-- cache_marker.bgeo.sc
```

`HouD2 Cache In` has no input. Choose Project, Task, and Cache from the Catalog.
Version defaults to `Latest`; switch it to `Specific` to choose an older
Version. The Cache Information tab shows its creator, creation time, frame
range, size, source Task, and resolved local path. Another Project or Task is
read directly from its registered local Geo Root.

Rebuild and test the HDAs with a registered Houdini installation:

```powershell
& "C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe" .\houdini\scripts\build_cache_hdas.py
& "C:\Program Files\Side Effects Software\Houdini 22.0.368\bin\hython.exe" .\houdini\scripts\test_cache_hdas.py
```

## Database Administration

Double-click `start_houd2_db_admin.bat` to open the independent localhost admin
screen. It supports table search, sorting, CSV/JSON export, consistent backup,
integrity checks, history cleanup, UI state reset, and JSON-based index repair.
It intentionally does not provide raw SQL or direct Project/Task cell editing.

## Cache Management

Select a HIP and open its `Caches` tab. The launcher inventories all supported
BGEO, VDB, Alembic, SIM, and USD files below the Project's `geo_cache` Role.
Versions actively loaded by the selected HIP are green; every other on-disk
Version is red. Deletion is permanent, requires confirmation, and is refused
for paths outside `geo_cache`.

## Task Packages

Use `Export Task Package...` from a Task's context menu. The resulting
`{task}_houd2package` folder contains HIPs, HouD2 metadata, thumbnails, and
non-cache Task files. Cache Roles and legacy `.houd2/trash/caches` content are
excluded. `manifest.json` records every packaged file's SHA-256 checksum.

Use `Import Task Package...` from a target Project's context menu. Import first
validates paths and checksums, then previews size, excluded Roles, and portable
Project setting differences. Existing Project settings are never overwritten.
Name collisions create `{task}_copy`, assign a new Task ID, and rename managed
HIP files and metadata to the imported Task name.

## Requirements

- Windows 10 or later
- Python 3.11 or later
- PySide6
- Pydantic v2
- pytest for development

## Setup

From PowerShell:

```powershell
.\scripts\setup.ps1
.\start_houd2launcher.bat
```

Alternatively:

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe .\run_houd2launcher.py
```

Launcher data is stored under `%LOCALAPPDATA%\HouD2Launcher` by default. Set
`HOUD2_HOME` to use a different per-user data directory.

## First Run

1. Open `Launcher Settings > Houdini Installations` and run `Auto Detect`.
2. Create a project or register an existing HouD2 project.
3. Create a task. HouD2Launcher creates `{project_root}/{task}/houdini` and the
   configured auto-create folders.
4. Create a HIP. The selected installation's `hython.exe` creates a valid blank
   HIP and HouD2Launcher writes its metadata.
5. Open a HIP and choose the required Houdini build and mode.

Every Houdini launch includes `TASK_NAME`, `SHOT_FRAME_START`,
`SHOT_FRAME_END`, `SHOT_FPS`, and the legacy `SHOTSTARTFRAME`/
`SHOTENDFRAME` aliases. The selected Task Overview lists all variables managed
by the Launcher.

HDA integration also receives `HOUD2_GEO_ROOT`, `HOUD2_USER_ID`,
`HOUD2_MACHINE_ID`, and the temporary localhost Catalog endpoint. The Catalog
token is process-only and is not shown in Overview or written to HIP/Manifest.

## Data Layout

```text
{project_root}/
|-- .houd2/
|   `-- project.json
`-- {task_name}/
    |-- .houd2/
    |   |-- task.json
    |   |-- thumbnail.jpg
    |   |-- hips/
    |   |-- thumbnails/
    |   `-- trash/caches/
    `-- houdini/
        |-- {task}_v001_{user}.hip
        |-- geo/
        |-- abc/
        `-- export/
```

Project and task JSON files are authoritative. SQLite is a rebuildable local
index used for fast display and history; JSON wins if the two disagree.

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

## Windows Build

```powershell
.\scripts\build_windows.ps1
```

The build output is created under `dist\HouD2Launcher`.
