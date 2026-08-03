from pathlib import Path

from houd2launcher.core.cache_manager import CacheManager
from houd2launcher.core.models import ProjectSettings, TaskSettings
from houd2launcher.core.path_resolver import PathResolver
from houd2launcher.core.sdm_package import SdmPackageService


def test_sdm_includes_all_hips_selected_roles_and_selected_cache(tmp_path: Path) -> None:
    resolver = PathResolver()
    project = ProjectSettings(name="Demo", project_root=tmp_path / "Demo")
    task = TaskSettings(project_id=project.project_id, name="fire")
    houdini = resolver.resolve_houdini_root(project, task)
    houdini.mkdir(parents=True)
    (houdini / "fire_v001.hip").write_bytes(b"hip")
    abc = resolver.resolve_role(project, task, "alembic")
    abc.mkdir(parents=True)
    (abc / "asset.abc").write_bytes(b"abc")
    geo = resolver.resolve_role(project, task, "geo_cache")
    for version in (1, 2):
        root = geo / "smoke" / f"v{version:03d}"
        root.mkdir(parents=True)
        (root / f"smoke.{version:04d}.bgeo.sc").write_bytes(str(version).encode())
    records = list(CacheManager(resolver).discover(project, task, []))
    package = SdmPackageService(resolver).export(
        project, task, tmp_path / "delivery", ["alembic"], [records[0]]
    )
    assert package.name == "fire_SDM2.0"
    assert (package / "houdini" / "fire_v001.hip").is_file()
    assert (package / "houdini" / "abc" / "asset.abc").is_file()
    assert (package / "houdini" / "geo" / "smoke" / "v001").is_dir()
    assert not (package / "houdini" / "geo" / "smoke" / "v002").exists()
