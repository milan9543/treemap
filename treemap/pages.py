"""The built web pages (``web/``, built into ``treemap/web_dist``): the server's page,
served by ``treemap serve``, and the virtual WLED's screen, served by ``treemap sim
wled``."""

from __future__ import annotations

from importlib import resources
from importlib.resources.abc import Traversable

CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png",
    ".json": "application/json", ".map": "application/json", ".woff2": "font/woff2",
}


def pages_dir() -> Traversable:
    return resources.files("treemap").joinpath("web_dist")
