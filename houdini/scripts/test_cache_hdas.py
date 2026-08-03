from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlparse

import hou


ROOT = Path(__file__).resolve().parents[1]
PYTHON_ROOT = ROOT / "python"
if str(PYTHON_ROOT) not in sys.path:
    sys.path.insert(0, str(PYTHON_ROOT))

from houd2_cache.cache_in import update_info, version_menu
from houd2_cache.manifest import load_manifest


def _record(manifest: dict[str, object], geo_root: Path) -> dict[str, object]:
    frame = manifest["frame"]
    creator = manifest["creator"]
    storage = manifest["storage"]
    assert isinstance(frame, dict) and isinstance(creator, dict) and isinstance(storage, dict)
    return {
        "cache_id": manifest["cache_id"], "project_id": "project-test",
        "project_name": "HDA Test", "task_id": "task-test", "task_name": "fire",
        "cache_name": manifest["name"], "version": manifest["version"],
        "cache_type": manifest["cache_type"], "geo_root": str(geo_root),
        "file_pattern": manifest["file_pattern"], "description": manifest["description"],
        "created_at": manifest["created_at"],
        "creator_user_id": creator["user_id"],
        "creator_display_name": creator["display_name"],
        "creator_machine_id": creator["machine_id"],
        "frame_start": frame["start"], "frame_end": frame["end"],
        "frame_step": frame["step"], "fps": frame["fps"],
        "file_count": storage["file_count"], "size_bytes": storage["size_bytes"],
        "status": "complete", "loadable": True, "legacy": False,
    }


def _server(record_ref: list[dict[str, object]], token: str) -> ThreadingHTTPServer:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            if self.headers.get("Authorization") != f"Bearer {token}":
                self.send_error(401)
                return
            path = urlparse(self.path).path
            if path == "/v1/projects":
                payload = {"items": [{"project_id": "project-test", "name": "HDA Test"}]}
            elif path == "/v1/projects/project-test/tasks":
                payload = {"items": [{"project_id": "project-test", "task_id": "task-test", "name": "fire"}]}
            elif path == "/v1/projects/project-test/tasks/task-test/caches":
                payload = {"items": record_ref}
            else:
                self.send_error(404)
                return
            self._send(payload)

        def do_POST(self) -> None:  # noqa: N802
            if self.headers.get("Authorization") != f"Bearer {token}":
                self.send_error(401)
                return
            self._send({"status": "refreshed"})

        def _send(self, payload: object) -> None:
            data = json.dumps(payload).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return ThreadingHTTPServer(("127.0.0.1", 0), Handler)


def run(root: Path) -> None:
    project_root = root / "日本語 Project"
    task_root = project_root / "fire"
    houdini_root = task_root / "houdini"
    geo_root = houdini_root / "geo"
    geo_root.mkdir(parents=True)
    os.environ.update({
        "HOUD2_PROJECT_ID": "project-test", "HOUD2_PROJECT_ROOT": str(project_root),
        "HOUD2_TASK_ID": "task-test", "HOUD2_TASK_ROOT": str(task_root),
        "HOUD2_HOUDINI_ROOT": str(houdini_root), "HOUD2_GEO_ROOT": str(geo_root),
        "HOUD2_USER_ID": "artist-id", "HOUD2_MACHINE_ID": "machine-id",
        "HOUD2_USER": "QA Artist",
    })
    token = "hda-test-token"
    records: list[dict[str, object]] = []
    server = _server(records, token)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    os.environ["HOUD2_API_URL"] = f"http://127.0.0.1:{server.server_port}"
    os.environ["HOUD2_API_TOKEN"] = token
    library = ROOT / "otls" / "houd2_cache.hda"
    if not library.is_file():
        raise RuntimeError(f"Commercial HDA library is missing: {library}")
    hou.hda.installFile(str(library))
    try:
        container = hou.node("/obj").createNode("geo", "houd2_integration_test")
        for child in container.children():
            child.destroy()
        box = container.createNode("box", "source_box")
        cache_out = container.createNode("houd2::cache_out::1.0", "cache_out")
        cache_out.setInput(0, box)
        assert cache_out.parm("cache_name").unexpandedString() == "$OS"
        assert cache_out.evalParm("cache_name") == "cache_out"
        cache_out.parm("cache_name").set("box_main")
        cache_out.parm("description").set("HDA integration cache")
        cache_out.parm("evaluate_as").set("current")
        cache_out.parm("delete_attributes").set("test_debug_attribute")
        cache_out.parm("delete_groups").set("test_debug_group")
        assert cache_out.node("filecache").evalParm("deleteattributes") == "test_debug_attribute"
        assert cache_out.node("filecache").evalParm("deletegroups") == "test_debug_group"
        assert cache_out.node("filecache").evalParm("cachesim") == 0
        cache_out.parm("simulation").set(1)
        assert cache_out.node("filecache").evalParm("cachesim") == 1
        cache_out.parm("simulation").set(0)
        cache_out.parm("save_to_disk").pressButton()
        assert str(cache_out.evalParm("status")).startswith("Complete")
        assert len(cache_out.geometry().points()) == 1
        manifest_path = Path(str(cache_out.evalParm("manifest_path")))
        manifest = load_manifest(manifest_path)
        records.append(_record(manifest, geo_root))

        cache_in = container.createNode("houd2::cache_in::1.0", "cache_in")
        for name, value in (("project_id", "project-test"), ("task_id", "task-test"), ("cache_name", "box_main")):
            cache_in.parm(name).deleteAllKeyframes()
            cache_in.parm(name).set(value)
        update_info(cache_in)
        assert cache_in.parm("project_id").menuItems() == ("project-test",)
        assert cache_in.parm("task_id").menuItems() == ("task-test",)
        assert cache_in.parm("cache_name").menuItems() == ("box_main",)
        assert cache_in.parm("specific_version").menuItems() == ("1",)
        assert cache_in.evalParm("local_status") == "READY"
        assert cache_in.evalParm("info_creator") == "QA Artist"
        assert version_menu({"node": cache_in})[:2] == ["1", "v001 - COMPLETE"]
        loaded = cache_in.geometry()
        file_node = cache_in.node("load_cache")
        assert len(loaded.points()) == len(box.geometry().points()), (
            len(loaded.points()), len(box.geometry().points()),
            file_node.evalParm("file"), file_node.errors(), file_node.warnings(),
        )
        assert not cache_in.errors(), cache_in.errors()
        probe_path = ROOT.parent / "src" / "houd2launcher" / "houdini" / "cache_probe.py"
        spec = importlib.util.spec_from_file_location("houd2_cache_probe_test", probe_path)
        assert spec and spec.loader
        probe = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(probe)
        assert probe._file_cache_reference(cache_out.node("filecache")) is None
        assert probe._houd2_owner(file_node) == ("in", cache_in.path())
        reference = probe._houd2_cache_in_reference(cache_in)
        assert reference is not None
        assert reference["node_path"] == cache_in.path()
        reference_path = Path(reference["expanded_path"])
        assert reference_path.parent == geo_root / "box_main" / "v001" / "geo"
        assert reference_path.name.startswith("box_main.")
        assert reference_path.name.endswith(".bgeo.sc")

        saved_hip = root / "cache_in_probe.hiplc"
        hou.hipFile.save(str(saved_hip))
        hou.hipFile.clear(suppress_save_prompt=True)
        hou.hipFile.load(str(saved_hip), suppress_save_prompt=True, ignore_load_warnings=True)
        loaded_cache_in = hou.node("/obj/houd2_integration_test/cache_in")
        assert loaded_cache_in is not None
        loaded_reference = probe._houd2_cache_in_reference(loaded_cache_in)
        assert loaded_reference is not None
        assert loaded_reference["node_path"] == loaded_cache_in.path()
        assert Path(loaded_reference["expanded_path"]) == reference_path
        print("Cache Out -> Catalog -> Cache In integration passed")
        print(f"Manifest: {manifest_path}")
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)


def main() -> int:
    if len(sys.argv) > 1:
        root = Path(sys.argv[1]).resolve()
        shutil.rmtree(root, ignore_errors=True)
        run(root)
    else:
        with tempfile.TemporaryDirectory(prefix="houd2-hda-test-") as temporary:
            run(Path(temporary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
