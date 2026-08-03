from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
HANDBOOK = ROOT / "docs" / "houd2-handbook.html"


class _HandbookParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.ids: list[str] = []
        self.roles: list[str] = []
        self.images: list[str] = []

    def handle_starttag(
        self, tag: str, attrs: list[tuple[str, str | None]]
    ) -> None:
        values = dict(attrs)
        if values.get("id"):
            self.ids.append(str(values["id"]))
        if values.get("data-role"):
            self.roles.append(str(values["data-role"]))
        if tag == "img" and values.get("src"):
            self.images.append(str(values["src"]))


def test_handbook_contains_current_guides_and_code_reference() -> None:
    html = HANDBOOK.read_text(encoding="utf-8")
    parser = _HandbookParser()
    parser.feed(html)

    assert parser.roles == ["user", "supervisor", "developer"]
    assert len(parser.ids) == len(set(parser.ids))
    assert html.count('<section class="doc-section"') >= 30
    assert html.count('<details class="file-reference"') >= 40
    for required in (
        "Cache Out / Cache In HDA",
        "既定値は<code>$OS</code>",
        "hidden_console_options()",
        "HoudiniCacheScanner.scan()",
        "resolve_houd2_context(node)",
        "Cache HDA Pythonリファレンス",
        "houdini/otls/houd2_cache.hda",
        "Database・Settings・UIリファレンス",
    ):
        assert required in html
    for source in parser.images:
        assert (HANDBOOK.parent / source).is_file()


def test_handbook_script_is_present_and_structurally_complete() -> None:
    html = HANDBOOK.read_text(encoding="utf-8")
    scripts = re.findall(r"<script>(.*?)</script>", html, flags=re.DOTALL)

    assert len(scripts) == 1
    script = scripts[0]
    for behavior in (
        "buildNav()",
        "activateRole(",
        "renderSearch()",
        "updateCurrentNav()",
        "navigator.clipboard.writeText",
    ):
        assert behavior in script
