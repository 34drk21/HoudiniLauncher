from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import Request, urlopen


class CatalogUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class CatalogClient:
    base_url: str
    token: str
    timeout: float = 2.0

    def projects(self) -> list[dict[str, Any]]:
        return self._items("/v1/projects")

    def tasks(self, project_id: str) -> list[dict[str, Any]]:
        return self._items(f"/v1/projects/{quote(project_id, safe='')}/tasks")

    def caches(self, project_id: str, task_id: str) -> list[dict[str, Any]]:
        return self._items(
            f"/v1/projects/{quote(project_id, safe='')}/tasks/{quote(task_id, safe='')}/caches"
        )

    def versions(self, project_id: str, task_id: str, cache_name: str) -> list[dict[str, Any]]:
        return self._items(
            f"/v1/projects/{quote(project_id, safe='')}/tasks/{quote(task_id, safe='')}/caches/"
            f"{quote(cache_name, safe='')}/versions"
        )

    def cache(self, cache_id: str) -> dict[str, Any]:
        data = self._request("GET", f"/v1/caches/{quote(cache_id, safe='')}")
        if not isinstance(data, dict):
            raise CatalogUnavailable("Catalog returned an invalid Cache record")
        return data

    def refresh(self) -> None:
        self._request("POST", "/v1/catalog/refresh")

    def sync(self, cache_id: str) -> dict[str, Any]:
        data = self._request("POST", f"/v1/caches/{quote(cache_id, safe='')}/sync")
        return data if isinstance(data, dict) else {"status": "unknown"}

    def _items(self, path: str) -> list[dict[str, Any]]:
        data = self._request("GET", path)
        if not isinstance(data, dict) or not isinstance(data.get("items"), list):
            raise CatalogUnavailable("Catalog returned an invalid list")
        return [item for item in data["items"] if isinstance(item, dict)]

    def _request(self, method: str, path: str) -> Any:
        request = Request(
            self.base_url.rstrip("/") + path, method=method,
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            try:
                payload = json.loads(exc.read().decode("utf-8"))
                detail = payload.get("message") or payload.get("error")
            except Exception:
                detail = None
            raise CatalogUnavailable(detail or f"Catalog request failed ({exc.code})") from exc
        except (URLError, OSError, json.JSONDecodeError) as exc:
            raise CatalogUnavailable(f"HouD2 Catalog is unavailable: {exc}") from exc
