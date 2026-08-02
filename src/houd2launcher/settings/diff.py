from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class Difference:
    """One leaf-level settings difference."""

    path: str
    current: object
    incoming: object


def diff_values(
    current: dict[str, Any], incoming: dict[str, Any], prefix: str = ""
) -> list[Difference]:
    """Return deterministic leaf-level differences for import preview."""
    differences: list[Difference] = []
    for key in sorted(set(current) | set(incoming)):
        path = f"{prefix}.{key}" if prefix else key
        left = current.get(key)
        right = incoming.get(key)
        if isinstance(left, dict) and isinstance(right, dict):
            differences.extend(diff_values(left, right, path))
        elif left != right:
            differences.append(Difference(path, left, right))
    return differences

