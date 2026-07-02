from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from nail_security.gateway_exposure import (
    FindingSeverity,
    GatewayExposureScanner,
    report_to_markdown,
    scan_source_tree,
)


class _ExposedMCPHandler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):  # noqa: ANN001
        pass

    def do_GET(self):  # noqa: N802
        if self.path == "/health":
            self._send(200, {"status": "ok"})
            return
        if self.path == "/openapi.json":
            self._send(200, {"paths": {"/mcp-rest/test/connection": {}}})
            return
        self._send(404, {"error": "not found"})

    def do_POST(self):  # noqa: N802
        if self.path == "/mcp-rest/test/connection":
            self._send(422, {"detail": "validation error"})
            return
        self._send(404, {"error": "not found"})

    def _send(self, status: int, body: dict):
        raw = json.dumps(body).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        self.wfile.write(raw)


class _ProtectedMCPHandler(_ExposedMCPHandler):
    def do_POST(self):  # noqa: N802
        if self.path == "/mcp-rest/test/connection":
            self._send(403, {"detail": "forbidden"})
            return
        self._send(404, {"error": "not found"})


def test_http_scan_flags_unauthenticated_mcp_test_endpoint():
    with _server(_ExposedMCPHandler) as url:
        report = GatewayExposureScanner(url, host_header_probe=False).scan()

    titles = [f.title for f in report.findings]
    assert "LiteLLM/MCP test endpoint reachable without authentication" in titles
    assert report.max_severity == FindingSeverity.HIGH


def test_http_scan_does_not_flag_auth_protected_mcp_endpoint():
    with _server(_ProtectedMCPHandler) as url:
        report = GatewayExposureScanner(url, host_header_probe=False).scan()

    assert all(
        f.title != "LiteLLM/MCP test endpoint reachable without authentication"
        for f in report.findings
    )


def test_source_scan_flags_vulnerable_dependency_and_open_admin(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "litellm==1.82.0\nstarlette>=0.48\n",
        encoding="utf-8",
    )
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "def check(admin_token):\n"
        "    if not admin_token:\n"
        "        return True\n",
        encoding="utf-8",
    )

    report = scan_source_tree(tmp_path)
    titles = {f.title for f in report.findings}

    assert "litellm dependency floor is below patched version" in titles
    assert "starlette dependency floor is below patched version" in titles
    assert "Admin token appears optional" in titles


def test_source_scan_flags_actual_mcp_route_definition(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\ndependencies = []\n", encoding="utf-8")
    (tmp_path / "app.py").write_text(
        "from fastapi import FastAPI\n"
        "app = FastAPI()\n"
        "@app.post('/mcp-rest/test/connection')\n"
        "def test_connection():\n"
        "    return {'ok': True}\n",
        encoding="utf-8",
    )

    report = scan_source_tree(tmp_path)
    assert any(f.title == "MCP test route present in source" for f in report.findings)


def test_markdown_report_contains_findings(tmp_path):
    (tmp_path / "requirements.txt").write_text("litellm\n", encoding="utf-8")
    report = scan_source_tree(tmp_path)
    markdown = report_to_markdown(report)
    assert "# AI Gateway Exposure Scan" in markdown
    assert "litellm dependency is unpinned" in markdown


class _server:
    def __init__(self, handler):
        self.handler = handler
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)

    def __enter__(self):
        self.thread.start()
        host, port = self.httpd.server_address
        return f"http://{host}:{port}"

    def __exit__(self, exc_type, exc, tb):  # noqa: ANN001
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=2)
