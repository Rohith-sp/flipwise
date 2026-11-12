"""Static files of the demo UI, shared by the live scheduler and each datacentre service.

Display only: nothing here touches simulation state.
"""

from __future__ import annotations

import datetime as dt
import mimetypes
import sys
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

_IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
WEB_DIR = Path(__file__).resolve().parent / "web"


def read_static(rel: str) -> tuple[bytes, str] | None:
    """`(bytes, content type)` for a file under `web/`, or None when it is missing or outside it.

    Resolves and checks containment: "..", encoded slashes and symlinks must not escape.
    """
    root = WEB_DIR.resolve()
    target = (root / unquote(rel).lstrip("/")).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target.read_bytes(), mimetypes.guess_type(target.name)[0] or "application/octet-stream"


def ist_string(t_s: int) -> str:
    """A simulated Unix time as IST text. Formats the given value; never reads the wall clock."""
    return dt.datetime.fromtimestamp(t_s, _IST).strftime("%a %d %b %H:%M IST")


# A browser that reloads or closes a page drops its open requests; the reply then has nowhere to go.
CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class QuietHTTPServer(ThreadingHTTPServer):
    """Threaded server that does not print a traceback when a viewer disconnects mid-reply."""

    daemon_threads = True

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001 (socketserver API)
        if isinstance(sys.exc_info()[1], CLIENT_GONE):
            return
        super().handle_error(request, client_address)
