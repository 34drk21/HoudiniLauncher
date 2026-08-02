from __future__ import annotations

from houd2launcher.houdini.cache_probe import (
    _file_cache_reference,
    _houd2_cache_in_reference,
    _is_file_cache,
)


class _Type:
    def name(self) -> str:
        return "filecache::2.0"


class _Parm:
    def __init__(
        self, name: str, value: object, raw: str = "", expression: str | None = None
    ) -> None:
        self._name = name
        self._value = value
        self._raw = raw
        self._expression = expression

    def eval(self) -> object:
        return self._value

    def evalAsString(self) -> str:
        return str(self._value)

    def unexpandedString(self) -> str:
        if self._expression is not None:
            raise RuntimeError("keyframed string parameter")
        return self._raw

    def expression(self) -> str:
        if self._expression is None:
            raise RuntimeError("parameter has no expression")
        return self._expression

    def name(self) -> str:
        return self._name


class _Node:
    def __init__(self, loading: bool) -> None:
        self._parms = {
            "loadfromdisk": _Parm("loadfromdisk", int(loading)),
            "sopoutput": _Parm("sopoutput", "D:/show/geo/fire/v2/fire.1001.bgeo.sc", "$HIP/geo/fire/v2/fire.$F4.bgeo.sc"),
        }

    def type(self) -> _Type:
        return _Type()

    def parm(self, name: str):
        return self._parms.get(name)

    def isBypassed(self) -> bool:
        return False

    def path(self) -> str:
        return "/obj/geo1/filecache1"


def test_file_cache_probe_only_reports_effective_output_when_loading() -> None:
    assert _is_file_cache(_Node(True))
    assert _file_cache_reference(_Node(False)) is None
    reference = _file_cache_reference(_Node(True))
    assert reference == {
        "node_path": "/obj/geo1/filecache1",
        "parameter": "sopoutput",
        "raw_path": "$HIP/geo/fire/v2/fire.$F4.bgeo.sc",
        "expanded_path": "D:/show/geo/fire/v2/fire.1001.bgeo.sc",
    }


def test_file_cache_probe_keeps_expression_driven_sopoutput() -> None:
    node = _Node(True)
    node._parms["sopoutput"] = _Parm(
        "sopoutput",
        "D:/show/geo/box/v2/box_v2.1001.bgeo.sc",
        expression='chs("cachedir") + "/" + chs("cachename")',
    )

    reference = _file_cache_reference(node)

    assert reference is not None
    assert reference["raw_path"] == 'chs("cachedir") + "/" + chs("cachename")'
    assert reference["expanded_path"].endswith("/box/v2/box_v2.1001.bgeo.sc")


class _NamedType:
    def __init__(self, name: str) -> None:
        self._name = name

    def name(self) -> str:
        return self._name


class _LoadNode:
    def __init__(self) -> None:
        self._file = _Parm(
            "file", "D:/show/geo/box/v003/geo/box.1001.bgeo.sc"
        )

    def parm(self, name: str):
        return self._file if name == "file" else None


class _CacheInNode:
    def __init__(self, bypassed: bool = False) -> None:
        self._bypassed = bypassed
        self._load = _LoadNode()
        self._pattern = _Parm(
            "resolved_file_pattern",
            "D:/show/geo/box/v003/geo/box.$F4.bgeo.sc",
        )

    def type(self) -> _NamedType:
        return _NamedType("houd2::cache_in::1.0")

    def isBypassed(self) -> bool:
        return self._bypassed

    def node(self, name: str):
        return self._load if name == "load_cache" else None

    def parm(self, name: str):
        return self._pattern if name == "resolved_file_pattern" else None

    def path(self) -> str:
        return "/obj/geo1/cache_in1"


def test_houd2_cache_in_probe_reports_public_node_and_effective_file() -> None:
    reference = _houd2_cache_in_reference(_CacheInNode())

    assert reference == {
        "node_path": "/obj/geo1/cache_in1",
        "parameter": "resolved_file_pattern",
        "raw_path": "D:/show/geo/box/v003/geo/box.$F4.bgeo.sc",
        "expanded_path": "D:/show/geo/box/v003/geo/box.1001.bgeo.sc",
    }
    assert _houd2_cache_in_reference(_CacheInNode(bypassed=True)) is None
