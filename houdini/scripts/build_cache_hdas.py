from __future__ import annotations

import sys
from pathlib import Path

import hou


ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))


CACHE_OUT_MODULE = """from houd2_cache import cache_out as _impl

def save_to_disk(kwargs):
    return _impl.save_to_disk(kwargs)

def save_current_frame(kwargs):
    return _impl.save_current_frame(kwargs)

def update_preview(kwargs):
    return _impl.update_preview(kwargs)

def open_cache_folder(kwargs):
    return _impl.open_cache_folder(kwargs)
"""

CACHE_IN_MODULE = """from houd2_cache import cache_in as _impl

def project_menu(kwargs):
    return _impl.project_menu(kwargs)

def task_menu(kwargs):
    return _impl.task_menu(kwargs)

def cache_menu(kwargs):
    return _impl.cache_menu(kwargs)

def version_menu(kwargs):
    return _impl.version_menu(kwargs)

def selection_changed(kwargs):
    return _impl.selection_changed(kwargs)

def refresh_catalog(kwargs):
    return _impl.refresh_catalog(kwargs)

def reload_cache(kwargs):
    return _impl.reload_cache(kwargs)

def sync_to_local(kwargs):
    return _impl.sync_to_local(kwargs)

def open_cache_folder(kwargs):
    return _impl.open_cache_folder(kwargs)

def resolved_file(node):
    return _impl.resolved_file(node)
"""


def _button(name: str, label: str, callback: str, help_text: str = "") -> hou.ButtonParmTemplate:
    parm = hou.ButtonParmTemplate(name, label)
    parm.setScriptCallback(callback)
    parm.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    if help_text:
        parm.setHelp(help_text)
    return parm


def _menu(
    name: str,
    label: str,
    items: tuple[str, ...],
    labels: tuple[str, ...],
    default: int = 0,
    callback: str = "",
) -> hou.MenuParmTemplate:
    parm = hou.MenuParmTemplate(name, label, items, menu_labels=labels, default_value=default)
    if callback:
        parm.setScriptCallback(callback)
        parm.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    return parm


def _dynamic_menu(name: str, label: str, generator: str, callback: str = "") -> hou.StringParmTemplate:
    parm = hou.StringParmTemplate(name, label, 1, string_type=hou.stringParmType.Regular)
    parm.setItemGeneratorScript(generator)
    parm.setItemGeneratorScriptLanguage(hou.scriptLanguage.Python)
    if callback:
        parm.setScriptCallback(callback)
        parm.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    return parm


def _readonly(name: str, label: str, default: str = "") -> hou.StringParmTemplate:
    parm = hou.StringParmTemplate(name, label, 1, default_value=(default,))
    parm.setConditional(hou.parmCondType.DisableWhen, "{ lock_info == 1 }")
    return parm


def _collapsible(
    name: str, label: str, *, expanded: bool = False
) -> hou.FolderParmTemplate:
    return hou.FolderParmTemplate(
        name,
        label,
        folder_type=hou.folderType.Collapsible,
        tags={
            "group_default": "1" if expanded else "0",
            "group_type": "collapsible",
        },
    )


def _join(*parms: hou.ParmTemplate) -> tuple[hou.ParmTemplate, ...]:
    for parm in parms[:-1]:
        parm.setJoinWithNext(True)
    return parms


def _hidden_string(name: str) -> hou.StringParmTemplate:
    parm = hou.StringParmTemplate(name, name, 1)
    parm.hide(True)
    return parm


def _callback(script: str) -> str:
    return f"hou.phm().{script}(kwargs)"


def _cache_out_parameters() -> hou.ParmTemplateGroup:
    group = hou.ParmTemplateGroup()

    caching = hou.FolderParmTemplate("caching_folder", "Caching")
    cache = _collapsible("cache_controls", "Cache", expanded=True)
    name = hou.StringParmTemplate("cache_name", "Cache Name", 1, default_value=("$OS",))
    name.setHelp("Example: explosion_main. One Windows-compatible folder name.")
    name.setScriptCallback(_callback("update_preview"))
    name.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    cache.addParmTemplate(name)
    cache.addParmTemplate(_menu(
        "version_mode", "Version Mode", ("auto", "manual"), ("Auto Next", "Manual"),
        callback=_callback("update_preview"),
    ))
    manual = hou.IntParmTemplate("manual_version", "Manual Version", 1, default_value=(1,), min=1, min_is_strict=True)
    manual.setConditional(hou.parmCondType.DisableWhen, "{ version_mode == auto }")
    manual.setScriptCallback(_callback("update_preview"))
    manual.setScriptCallbackLanguage(hou.scriptLanguage.Python)
    cache.addParmTemplate(manual)
    save = _button(
        "save_to_disk", "Save to Disk", _callback("save_to_disk"),
        "Writes the selected frame range or current frame as a new immutable Cache Version.",
    )
    current = _button(
        "save_current_frame", "Save Current Frame", _callback("save_current_frame"),
        "Immediately writes only the current frame as a new Cache Version.",
    )
    open_folder = _button(
        "open_cache_folder", "Open Cache Folder", _callback("open_cache_folder")
    )
    for parm in _join(save, current, open_folder):
        cache.addParmTemplate(parm)
    cache.addParmTemplate(_readonly("status", "Status", "Not saved"))
    caching.addParmTemplate(cache)

    sequence = _collapsible("sequence_controls", "Sequence", expanded=True)
    evaluate = _menu(
        "evaluate_as", "Evaluate As", ("range", "current"),
        ("Frame Range", "Current Frame"), callback=_callback("update_preview"),
    )
    evaluate.setHelp("Frame Range uses Start/End/Inc. Current Frame writes the playbar frame only.")
    sequence.addParmTemplate(evaluate)
    simulation = hou.ToggleParmTemplate("simulation", "Simulation", default_value=False)
    simulation.setConditional(hou.parmCondType.DisableWhen, "{ evaluate_as == current }")
    simulation.setHelp("Cooks frames in order for stateful simulation inputs, matching File Cache behavior.")
    sequence.addParmTemplate(simulation)
    start = hou.IntParmTemplate("frame_start", "Start/End/Inc", 1, default_value=(1001,))
    start.setDefaultExpression(("$SHOT_FRAME_START",))
    end = hou.IntParmTemplate("frame_end", "End", 1, default_value=(1100,))
    end.setDefaultExpression(("$SHOT_FRAME_END",))
    increment = hou.IntParmTemplate(
        "frame_increment", "Inc", 1, default_value=(1,), min=1, min_is_strict=True
    )
    for parm in (start, end, increment):
        parm.setConditional(hou.parmCondType.DisableWhen, "{ evaluate_as == current }")
    for parm in _join(start, end, increment):
        sequence.addParmTemplate(parm)
    caching.addParmTemplate(sequence)
    group.append(caching)

    filters = hou.FolderParmTemplate("save_filters_folder", "Save Filters")
    delete_attributes = hou.StringParmTemplate(
        "delete_attributes", "Delete Attributes", 1, default_value=("",)
    )
    delete_attributes.setHelp("Optional File Cache pattern, for example: debug* temp*")
    filters.addParmTemplate(delete_attributes)
    delete_groups = hou.StringParmTemplate(
        "delete_groups", "Delete Groups", 1, default_value=("",)
    )
    delete_groups.setHelp("Optional File Cache group pattern, for example: temp_* __debug")
    filters.addParmTemplate(delete_groups)
    group.append(filters)

    metadata = hou.FolderParmTemplate("metadata_folder", "Metadata")
    description = hou.StringParmTemplate("description", "Description", 1, default_value=("",))
    description.setHelp("Short note describing what this cache contains or how it was generated.")
    metadata.addParmTemplate(description)
    paths = _collapsible("resolved_paths", "Resolved Paths")
    paths.addParmTemplate(_readonly("resolved_geo_root", "Geo Root"))
    paths.addParmTemplate(_readonly("resolved_cache_path", "Cache Path"))
    metadata.addParmTemplate(paths)
    group.append(metadata)

    advanced = hou.FolderParmTemplate("advanced_folder", "Advanced")
    task = hou.StringParmTemplate("manual_task_root", "Manual Task Root", 1, string_type=hou.stringParmType.FileReference)
    task.setHelp("Fallback example: D:/project/fire. Normally leave empty and launch from HouD2Launcher.")
    geo = hou.StringParmTemplate("manual_geo_root", "Manual Geo Root", 1, string_type=hou.stringParmType.FileReference)
    geo.setHelp("Fallback example: D:/project/fire/houdini/geo. Must be inside Manual Task Root/houdini.")
    advanced.addParmTemplate(task)
    advanced.addParmTemplate(geo)
    group.append(advanced)

    lock = hou.ToggleParmTemplate("lock_info", "lock_info", default_value=True)
    lock.hide(True)
    group.append(lock)
    group.append(_hidden_string("manifest_path"))
    group.append(_hidden_string("cache_id"))
    group.append(_hidden_string("internal_file_pattern"))
    for name, default in (("internal_start", 1), ("internal_end", 1), ("internal_step", 1)):
        internal = hou.IntParmTemplate(name, name, 1, default_value=(default,))
        internal.hide(True)
        group.append(internal)
    current_only = hou.ToggleParmTemplate("internal_current_only", "internal_current_only")
    current_only.hide(True)
    group.append(current_only)
    resolved_version = hou.IntParmTemplate("resolved_version", "resolved_version", 1, default_value=(0,))
    resolved_version.hide(True)
    group.append(resolved_version)
    return group


def _cache_in_parameters() -> hou.ParmTemplateGroup:
    group = hou.ParmTemplateGroup()

    load = hou.FolderParmTemplate("load_folder", "Load")
    load.addParmTemplate(_readonly("local_status", "Status", "Select a Cache"))
    callback = _callback("selection_changed")

    context = _collapsible("source_context", "Source Context", expanded=True)
    context.addParmTemplate(_dynamic_menu("project_id", "Project", "hou.phm().project_menu(kwargs)", callback))
    context.addParmTemplate(_dynamic_menu("task_id", "Task", "hou.phm().task_menu(kwargs)", callback))
    load.addParmTemplate(context)

    selection = _collapsible("cache_selection", "Cache Version", expanded=True)
    selection.addParmTemplate(_dynamic_menu("cache_name", "Cache", "hou.phm().cache_menu(kwargs)", callback))
    selection.addParmTemplate(_menu("version_mode", "Version", ("latest", "specific"), ("Latest", "Specific"), callback=callback))
    specific = _dynamic_menu("specific_version", "Specific Version", "hou.phm().version_menu(kwargs)", callback)
    specific.setConditional(hou.parmCondType.DisableWhen, "{ version_mode == latest }")
    selection.addParmTemplate(specific)
    selection.addParmTemplate(_menu("load_mode", "Load Mode", ("full", "delayed"), ("Full Geometry", "Packed Disk Primitive"), callback=callback))
    load.addParmTemplate(selection)

    actions = _collapsible("load_actions", "Actions", expanded=True)
    refresh = _button("refresh_catalog", "Refresh Catalog", _callback("refresh_catalog"))
    reload_button = _button("reload_cache", "Reload Cache", _callback("reload_cache"))
    open_button = _button("open_cache_folder", "Open Cache Folder", _callback("open_cache_folder"))
    sync = _button(
        "sync_to_local", "Sync to Local", _callback("sync_to_local"),
        "Requests the Launcher sync provider. Network transfer is unavailable until a provider is configured.",
    )
    for parm in _join(refresh, reload_button, open_button, sync):
        actions.addParmTemplate(parm)
    load.addParmTemplate(actions)
    group.append(load)

    info = hou.FolderParmTemplate("info_folder", "Info")
    summary = _collapsible("cache_summary", "Cache Summary", expanded=True)
    for name, label in (
        ("info_source", "Source"), ("info_creator", "Created By"),
        ("info_created_at", "Created At"), ("info_description", "Description"),
        ("info_type", "Cache Type"), ("info_frames", "Frames"),
        ("info_storage", "Storage"),
    ):
        summary.addParmTemplate(_readonly(name, label))
    info.addParmTemplate(summary)
    creator = _collapsible("creator_details", "Creator Details")
    creator.addParmTemplate(_readonly("info_user_id", "User ID"))
    creator.addParmTemplate(_readonly("info_machine_id", "Machine ID"))
    info.addParmTemplate(creator)
    group.append(info)

    advanced = hou.FolderParmTemplate("advanced_folder", "Advanced")
    resolved = _collapsible("resolved_cache_paths", "Resolved Paths")
    resolved.addParmTemplate(_readonly("resolved_geo_root", "Source Geo Root"))
    resolved.addParmTemplate(_readonly("resolved_file_pattern", "Resolved File Pattern"))
    advanced.addParmTemplate(resolved)
    fallback = _collapsible("fallback_roots", "Developer Fallback")
    manual_task = hou.StringParmTemplate("manual_task_root", "Manual Task Root", 1, string_type=hou.stringParmType.FileReference)
    manual_task.setHelp("Fallback example: D:/project/fire. Normally leave empty and launch from HouD2Launcher.")
    manual_geo = hou.StringParmTemplate("manual_geo_root", "Manual Geo Root", 1, string_type=hou.stringParmType.FileReference)
    manual_geo.setHelp("Fallback example: D:/project/fire/houdini/geo. Must be inside Manual Task Root/houdini.")
    fallback.addParmTemplate(manual_task)
    fallback.addParmTemplate(manual_geo)
    advanced.addParmTemplate(fallback)
    group.append(advanced)
    lock = hou.ToggleParmTemplate("lock_info", "lock_info", default_value=True)
    lock.hide(True)
    group.append(lock)
    group.append(_hidden_string("resolved_cache_id"))
    return group


def _build_cache_out(parent: hou.Node, library: Path) -> hou.Node:
    subnet = parent.createNode("subnet", "cache_out_build")
    file_cache = subnet.createNode("filecache::2.0", "filecache")
    file_cache.setInput(0, subnet.indirectInputs()[0])
    file_cache.parm("loadfromdisk").set(0)
    file_cache.parm("filemethod").set("explicit")
    file_cache.parm("file").setExpression("chs('../internal_file_pattern')", hou.exprLanguage.Hscript)
    file_cache.parm("timedependent").set(1)
    file_cache.parm("trange").setExpression("if(ch('../internal_current_only'),0,1)", hou.exprLanguage.Hscript)
    file_cache.parm("f1").setExpression("ch('../internal_start')", hou.exprLanguage.Hscript)
    file_cache.parm("f2").setExpression("ch('../internal_end')", hou.exprLanguage.Hscript)
    file_cache.parm("f3").setExpression("ch('../internal_step')", hou.exprLanguage.Hscript)
    file_cache.parm("cachesim").setExpression("ch('../simulation')", hou.exprLanguage.Hscript)
    file_cache.parm("substeps").set(1)
    file_cache.parm("mkpath").set(1)
    file_cache.parm("loadfromdiskonsave").set(0)
    file_cache.parm("savebackground").set(0)
    marker = subnet.createNode("python", "marker_output")
    marker.parm("python").set("from houd2_cache.cache_out import cook_marker\ncook_marker(hou.pwd())")
    output = subnet.createNode("output", "output0")
    output.setInput(0, marker)
    output.setDisplayFlag(True)
    output.setRenderFlag(True)
    subnet.layoutChildren()
    asset = subnet.createDigitalAsset(
        name="houd2::cache_out::1.0", hda_file_name=str(library),
        description="HouD2 Cache Out", min_num_inputs=1, max_num_inputs=1,
    )
    definition = asset.type().definition()
    definition.setParmTemplateGroup(_cache_out_parameters())
    asset.node("filecache").parm("deleteattributes").setExpression(
        "chs('../delete_attributes')", hou.exprLanguage.Hscript
    )
    asset.node("filecache").parm("deletegroups").setExpression(
        "chs('../delete_groups')", hou.exprLanguage.Hscript
    )
    definition.addSection("PythonModule", CACHE_OUT_MODULE)
    definition.addSection("OnCreated", "kwargs['node'].hdaModule().update_preview(kwargs)")
    definition.setExtraFileOption("OnCreated/IsPython", True)
    definition.updateFromNode(asset)
    return asset


def _build_cache_in(parent: hou.Node, library: Path) -> hou.Node:
    subnet = parent.createNode("subnet", "cache_in_build")
    file_node = subnet.createNode("file", "load_cache")
    file_node.parm("filemode").set("read")
    file_node.parm("missingframe").set("empty")
    file_node.parm("file").setExpression(
        "hou.pwd().parent().hdaModule().resolved_file(hou.pwd().parent())",
        hou.exprLanguage.Python,
    )
    file_node.parm("loadtype").setExpression("ch('../load_mode')", hou.exprLanguage.Hscript)
    output = subnet.createNode("output", "output0")
    output.setInput(0, file_node)
    output.setDisplayFlag(True)
    output.setRenderFlag(True)
    subnet.layoutChildren()
    asset = subnet.createDigitalAsset(
        name="houd2::cache_in::1.0", hda_file_name=str(library),
        description="HouD2 Cache In", min_num_inputs=0, max_num_inputs=0,
    )
    definition = asset.type().definition()
    definition.setParmTemplateGroup(_cache_in_parameters())
    definition.addSection("PythonModule", CACHE_IN_MODULE)
    definition.addSection(
        "OnCreated",
        "node=kwargs['node']\n"
        "node.parm('project_id').setExpression('$HOUD2_PROJECT_ID', hou.exprLanguage.Hscript)\n"
        "node.parm('task_id').setExpression('$HOUD2_TASK_ID', hou.exprLanguage.Hscript)",
    )
    definition.setExtraFileOption("OnCreated/IsPython", True)
    definition.updateFromNode(asset)
    return asset


def _library_path() -> Path:
    if len(sys.argv) > 1:
        return Path(sys.argv[1]).expanduser().resolve()
    license_name = str(hou.licenseCategory()).casefold()
    extension = ".hdalc" if "indie" in license_name else ".hdanc" if "apprentice" in license_name or "noncommercial" in license_name else ".hda"
    return (ROOT / "otls" / f"houd2_cache{extension}").resolve()


def main() -> int:
    library = _library_path()
    library.parent.mkdir(parents=True, exist_ok=True)
    if library.exists():
        try:
            hou.hda.uninstallFile(str(library))
        except hou.OperationFailed:
            pass
        library.unlink()
    obj = hou.node("/obj")
    container = obj.createNode("geo", "houd2_hda_builder")
    for child in container.children():
        child.destroy()
    try:
        cache_out = _build_cache_out(container, library)
        cache_out.destroy()
        cache_in = _build_cache_in(container, library)
        cache_in.destroy()
    finally:
        container.destroy()
    hou.hda.installFile(str(library))
    definitions = hou.hda.definitionsInFile(str(library))
    names = sorted(item.nodeTypeName() for item in definitions)
    expected = ["houd2::cache_in::1.0", "houd2::cache_out::1.0"]
    if names != expected:
        raise RuntimeError(f"Unexpected HDA definitions: {names}")
    print(f"Built {library}")
    print("Definitions: " + ", ".join(names))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
