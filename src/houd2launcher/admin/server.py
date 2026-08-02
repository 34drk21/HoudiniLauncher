from __future__ import annotations

import argparse
import json
import secrets
import threading
import webbrowser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from .service import DatabaseAdminService


STATIC_ROOT = Path(__file__).with_name("static")


def make_handler(service: DatabaseAdminService, token: str) -> type[BaseHTTPRequestHandler]:
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._file(STATIC_ROOT / "index.html", "text/html; charset=utf-8")
                return
            if not self._authorized():
                return
            try:
                if parsed.path == "/api/tables":
                    self._json(HTTPStatus.OK, {"items": service.tables()})
                    return
                if parsed.path.startswith("/api/table/"):
                    table = unquote(parsed.path.removeprefix("/api/table/"))
                    query = parse_qs(parsed.query)
                    self._json(HTTPStatus.OK, service.rows(
                        table, search=query.get("q", [""])[0], sort=query.get("sort", [""])[0],
                        descending=query.get("desc", ["0"])[0] == "1",
                        page=int(query.get("page", ["1"])[0]),
                        page_size=int(query.get("page_size", ["100"])[0]),
                    ))
                    return
                if parsed.path.startswith("/api/export/"):
                    table = unquote(parsed.path.removeprefix("/api/export/"))
                    file_format = parse_qs(parsed.query).get("format", ["csv"])[0]
                    filename, data = service.export(table, file_format)
                    self.send_response(HTTPStatus.OK)
                    self.send_header("Content-Type", "application/json" if file_format == "json" else "text/csv")
                    self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                    self.send_header("Content-Length", str(len(data)))
                    self.end_headers()
                    self.wfile.write(data)
                    return
                self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def do_POST(self) -> None:  # noqa: N802
            if not self._authorized():
                return
            try:
                payload = self._body()
                path = urlparse(self.path).path
                if path == "/api/backup":
                    self._json(HTTPStatus.OK, {"path": str(service.backup())})
                elif path == "/api/integrity":
                    self._json(HTTPStatus.OK, {"results": service.integrity_check()})
                elif path == "/api/repair":
                    self._json(HTTPStatus.OK, service.repair_indexes())
                elif path == "/api/reset-ui":
                    self._json(HTTPStatus.OK, {"deleted": service.reset_ui_state()})
                elif path == "/api/clear-history":
                    row_id = payload.get("id")
                    self._json(HTTPStatus.OK, {"deleted": service.clear_history(str(payload.get("table", "")), int(row_id) if row_id is not None else None)})
                else:
                    self._json(HTTPStatus.NOT_FOUND, {"error": "Unknown endpoint"})
            except Exception as exc:
                self._json(HTTPStatus.BAD_REQUEST, {"error": str(exc)})

        def _authorized(self) -> bool:
            if self.headers.get("X-HouD2-Admin-Token") == token:
                return True
            self._json(HTTPStatus.UNAUTHORIZED, {"error": "Unauthorized"})
            return False

        def _body(self) -> dict[str, object]:
            length = int(self.headers.get("Content-Length", "0"))
            if not length:
                return {}
            value = json.loads(self.rfile.read(length).decode("utf-8"))
            return value if isinstance(value, dict) else {}

        def _file(self, path: Path, content_type: str) -> None:
            data = path.read_bytes()
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _json(self, status: HTTPStatus, payload: object) -> None:
            data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def log_message(self, _format: str, *_args: object) -> None:
            return

    return Handler


def main() -> int:
    parser = argparse.ArgumentParser(description="HouD2Launcher administrator database browser")
    parser.add_argument("--database", type=Path)
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--token", default="")
    parser.add_argument("--no-browser", action="store_true")
    args = parser.parse_args()
    service = DatabaseAdminService(args.database)
    token = args.token or secrets.token_urlsafe(32)
    server = ThreadingHTTPServer(("127.0.0.1", args.port), make_handler(service, token))
    url = f"http://127.0.0.1:{server.server_port}/#token={token}"
    print(f"HouD2 DB Admin: {url}")
    print("Press Ctrl+C to stop.")
    if not args.no_browser:
        threading.Timer(0.4, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
