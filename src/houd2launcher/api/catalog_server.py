from __future__ import annotations

import json
import secrets
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import unquote, urlparse

from ..core.cache_catalog import CacheCatalogService


class CatalogApiServer:
    """Authenticated localhost HTTP bridge for Houdini cache menus."""

    def __init__(self, catalog: CacheCatalogService) -> None:
        self.catalog = catalog
        self.token = secrets.token_urlsafe(32)
        self._server: ThreadingHTTPServer | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        if not self._server:
            return ""
        return f"http://127.0.0.1:{self._server.server_port}"

    def start(self) -> None:
        if self._server:
            return
        catalog = self.catalog
        token = self.token

        class Handler(BaseHTTPRequestHandler):
            def do_GET(self) -> None:  # noqa: N802
                if not self._authorized(token):
                    return
                try:
                    self._dispatch_get(catalog)
                except KeyError as exc:
                    self._json(HTTPStatus.NOT_FOUND, {"error": str(exc)})
                except Exception as exc:
                    self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

            def do_POST(self) -> None:  # noqa: N802
                if not self._authorized(token):
                    return
                path = urlparse(self.path).path.rstrip("/")
                if path == "/v1/catalog/refresh":
                    catalog.refresh()
                    self._json(HTTPStatus.OK, {"status": "refreshed"})
                    return
                if path.startswith("/v1/caches/") and path.endswith("/sync"):
                    self._json(
                        HTTPStatus.NOT_IMPLEMENTED,
                        {"status": "unavailable", "message": "Cache sync provider is not configured"},
                    )
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})

            def _dispatch_get(self, service: CacheCatalogService) -> None:
                parts = [unquote(item) for item in urlparse(self.path).path.split("/") if item]
                if parts == ["v1", "projects"]:
                    self._json(HTTPStatus.OK, {"items": service.list_projects()})
                    return
                if len(parts) == 4 and parts[:2] == ["v1", "projects"] and parts[3] == "tasks":
                    self._json(HTTPStatus.OK, {"items": service.list_tasks(parts[2])})
                    return
                if len(parts) == 6 and parts[:2] == ["v1", "projects"] and parts[3] == "tasks" and parts[5] == "caches":
                    self._json(HTTPStatus.OK, {"items": service.list_caches(parts[2], parts[4])})
                    return
                if len(parts) == 8 and parts[:2] == ["v1", "projects"] and parts[3] == "tasks" and parts[5] == "caches" and parts[7] == "versions":
                    self._json(HTTPStatus.OK, {"items": service.versions(parts[2], parts[4], parts[6])})
                    return
                if len(parts) == 3 and parts[:2] == ["v1", "caches"]:
                    self._json(HTTPStatus.OK, service.find_cache(parts[2]))
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})

            def _authorized(self, expected: str) -> bool:
                if self.headers.get("Authorization") == f"Bearer {expected}":
                    return True
                self._json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
                return False

            def _json(self, status: HTTPStatus, payload: object) -> None:
                data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
                self.send_response(int(status))
                self.send_header("Content-Type", "application/json; charset=utf-8")
                self.send_header("Content-Length", str(len(data)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(data)

            def log_message(self, _format: str, *_args: object) -> None:
                return

        self._server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self._thread = threading.Thread(
            target=self._server.serve_forever,
            name="HouD2CatalogApi",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._server:
            return
        self._server.shutdown()
        self._server.server_close()
        if self._thread:
            self._thread.join(timeout=2)
        self._server = None
        self._thread = None
