from __future__ import annotations

import json
import sys


def _is_file_cache(node: object) -> bool:
    try:
        return "filecache" in node.type().name().casefold()
    except Exception:
        return False


def _file_cache_reference(node: object) -> dict[str, str] | None:
    """Return the effective output only when a File Cache is loading from disk."""
    try:
        load_parm = node.parm("loadfromdisk")
        if load_parm is None or not bool(load_parm.eval()) or node.isBypassed():
            return None
        output = next(
            (node.parm(name) for name in ("sopoutput", "file", "filepath") if node.parm(name)),
            None,
        )
        if output is None:
            return None
        expanded = output.evalAsString()
        try:
            raw = output.unexpandedString()
        except Exception:
            # Expression/keyframed string parms do not expose an unexpanded string.
            # The evaluated output still identifies the active cache Version.
            try:
                raw = output.expression()
            except Exception:
                raw = expanded
        return {
            "node_path": node.path(),
            "parameter": output.name(),
            "raw_path": str(raw),
            "expanded_path": str(expanded),
        }
    except Exception:
        return None


def _houd2_owner(node: object) -> tuple[str, str] | None:
    """Return the containing HouD2 cache HDA kind and public node path."""
    try:
        parent = node.parent()
        while parent is not None:
            type_name = parent.type().name().casefold()
            if "houd2::cache_out" in type_name:
                return "out", parent.path()
            if "houd2::cache_in" in type_name:
                return "in", parent.path()
            parent = parent.parent()
    except Exception:
        return None
    return None


def _houd2_cache_in_reference(node: object) -> dict[str, str] | None:
    """Return the effective local file read by one HouD2 Cache In HDA."""
    try:
        if "houd2::cache_in" not in node.type().name().casefold() or node.isBypassed():
            return None
        file_node = node.node("load_cache")
        file_parm = file_node.parm("file") if file_node is not None else None
        if file_parm is None:
            return None
        expanded = str(file_parm.evalAsString()).strip()
        if not expanded:
            return None
        pattern_parm = node.parm("resolved_file_pattern")
        raw = (
            str(pattern_parm.evalAsString()).strip()
            if pattern_parm is not None
            else expanded
        )
        return {
            "node_path": node.path(),
            "parameter": "resolved_file_pattern",
            "raw_path": raw or expanded,
            "expanded_path": expanded,
        }
    except Exception:
        return None


def main() -> int:
    """Load one HIP in hython and print its external file references as JSON."""
    import hou

    hou.hipFile.load(
        file_name=sys.argv[1],
        suppress_save_prompt=True,
        ignore_load_warnings=True,
    )
    references: list[dict[str, str]] = []
    houd2_cache_in_nodes = {
        node.path(): node
        for node in hou.node("/").allSubChildren()
        if "houd2::cache_in" in node.type().name().casefold()
    }
    for node in houd2_cache_in_nodes.values():
        reference = _houd2_cache_in_reference(node)
        if reference:
            references.append(reference)
    file_cache_nodes = {
        node.path(): node
        for node in hou.node("/").allSubChildren()
        if _is_file_cache(node)
    }
    for node in file_cache_nodes.values():
        reference = _file_cache_reference(node)
        if reference:
            references.append(reference)
    for parm, raw_path in hou.fileReferences("HIP", True):
        if parm is None:
            continue
        if parm.node().path() in file_cache_nodes:
            continue
        owner = _houd2_owner(parm.node())
        # Cache In is reported explicitly above, while Cache Out only writes data.
        if owner:
            continue
        try:
            expanded = parm.evalAsString()
        except (hou.Error, TypeError):
            try:
                expanded = hou.text.expandString(str(raw_path))
            except hou.Error:
                expanded = str(raw_path)
        references.append(
            {
                "node_path": owner[1] if owner else parm.node().path(),
                "parameter": parm.name(),
                "raw_path": str(raw_path),
                "expanded_path": str(expanded),
            }
        )
    print("HOUD2_CACHE_REFERENCES=" + json.dumps(references, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
