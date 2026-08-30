"""Web Hub Local HTTP Server.

Starts a local HTTP server with automatic port discovery and no-cache headers,
serving the Web Hub static frontend from apps/web-hub/static and streaming Python
engine modules to Pyodide WebAssembly from libs/*/src/.
"""

from __future__ import annotations

import importlib.resources
import json
import logging
import sys
import threading
import time
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, override

from web_server.updater import check_update_available, perform_app_update

logger: logging.Logger = logging.getLogger(__name__)

STATIC_DIR: Path = Path(str(importlib.resources.files("web_server") / "static"))


def get_package_file(package_name: str, filename: str = "engine.py") -> Path | None:
    """Robustly locate a file within an installed workspace package via importlib.resources.

    Args:
        package_name: Package name (e.g. "vat_report", "image_renamer").
        filename: Target filename within the package.

    Returns:
        Path to the resource if found, or None.
    """
    try:
        path = Path(str(importlib.resources.files(package_name) / filename))
        if path.is_file():
            return path
    except (TypeError, ValueError, ModuleNotFoundError) as err:
        logger.warning("Could not resolve package resource %s/%s: %s", package_name, filename, err)
    return None


class WebHubRequestHandler(SimpleHTTPRequestHandler):
    """Custom request handler that serves static assets and provides engine files to Pyodide."""

    def __init__(
        self,
        request: Any,  # ruff: ignore[any-type]
        client_address: tuple[str, int] | str,
        server: ThreadingHTTPServer,
        directory: str | None = None,
    ) -> None:
        """Initialize request handler serving from STATIC_DIR."""
        super().__init__(request, client_address, server, directory=directory or str(STATIC_DIR))

    @override
    def do_GET(self) -> None:
        """Handle GET requests for static files, API status, and dynamic Python modules."""
        if self.path in {"/api/check-update", "/api/update-status"}:
            info = check_update_available()
            payload = json.dumps(info).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return

        if self.path in {
            "/vat_report/engine.py",
            "/vat_report.py",
            "/process_report.py",
            "/process_report",
        }:
            source_file = get_package_file("vat_report", "engine.py")
            if source_file:
                self._serve_python_file(source_file)
                return
        elif self.path in {"/image_renamer/engine.py", "/image_renamer.py"}:
            source_file = get_package_file("image_renamer", "engine.py")
            if source_file:
                self._serve_python_file(source_file)
                return
        elif self.path in {"/b2b_vat/engine.py", "/b2b_vat.py"}:
            source_file = get_package_file("b2b_vat", "engine.py")
            if source_file:
                self._serve_python_file(source_file)
                return

        super().do_GET()

    def do_POST(self) -> None:
        """Handle POST requests for in-browser application updates."""
        if self.path in {"/api/update", "/update"}:
            result = perform_app_update()
            payload = json.dumps({"success": result.success, "message": result.message}).encode(
                "utf-8"
            )
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)
            return
        self.send_error(404, "Endpoint not found")

    def _serve_python_file(self, file_path: Path) -> None:
        if not file_path.exists():
            self.send_error(404, f"Module file not found: {file_path.name}")
            return
        content = file_path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.end_headers()
        self.wfile.write(content)

    @override
    def end_headers(self) -> None:
        """Send no-cache headers on all responses."""
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    @override
    def log_message(self, format: str, *args: object) -> None:
        """Silence standard console access logging."""


def serve_web(starting_port: int = 8000, max_attempts: int = 25) -> None:
    """Start local web server on an available port and open in default browser.

    Args:
        starting_port: Port number to try first.
        max_attempts: Maximum consecutive ports to check.
    """
    server: ThreadingHTTPServer | None = None
    active_port = starting_port

    for port in range(starting_port, starting_port + max_attempts):
        try:
            server = ThreadingHTTPServer(("127.0.0.1", port), WebHubRequestHandler)
            active_port = port
            break
        except OSError:
            continue

    if server is None:
        logger.error(
            "Could not bind to any open port between %d and %d",
            starting_port,
            starting_port + max_attempts,
        )
        sys.exit(1)

    url = f"http://localhost:{active_port}"
    print("\n" + "=" * 64)
    print("  Tinite Automation - Web Hub Server")
    print("=" * 64)
    print(f"  URL:     {url}")
    print("  Status:  Opening in your default browser...")
    print("  (Press Ctrl+C in this terminal window to stop the server)")
    print("=" * 64 + "\n")

    def _open_browser() -> None:
        time.sleep(0.3)
        webbrowser.open(url)

    threading.Thread(target=_open_browser, daemon=True).start()

    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nWeb server stopped cleanly.")
    finally:
        server.server_close()
        sys.exit(0)


def main() -> None:
    """Entry point for the Web Hub HTTP server."""
    logging.basicConfig(level=logging.INFO, format="  [%(levelname)s] %(message)s")
    serve_web()


if __name__ == "__main__":
    main()
