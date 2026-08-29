"""
Web Hub Local Server Package
"""

from __future__ import annotations

from web_server.server import main, serve_web

__version__: str = "0.2.0"
__all__: list[str] = ["main", "serve_web"]
