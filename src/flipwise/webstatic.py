"""Static files of the demo UI, shared by the live scheduler and each datacentre service.

Display only: nothing here touches simulation state.
"""

from __future__ import annotations

import datetime as dt
import gzip
import mimetypes
import sys
import threading
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import unquote

_IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
WEB_DIR = Path(__file__).resolve().parent / "web"
# Pinned third-party files do not change between releases, so a browser may reuse them for a
# day without asking; our own files are revalidated on every load (a cheap 304 when unchanged).
VENDOR_MAX_AGE_S = 86400
_GZIP_MIN_BYTES = 1024
_COMPRESSIBLE = ("text/", "application/javascript", "application/json", "image/svg+xml")


def _resolve(rel: str) -> Path | None:
    """The file under `web/` for `rel`, or None when it is missing or outside it.

    Resolves and checks containment: "..", encoded slashes and symlinks must not escape.
    """
    root = WEB_DIR.resolve()
    target = (root / unquote(rel).lstrip("/")).resolve()
    if not target.is_relative_to(root) or not target.is_file():
        return None
    return target


def _ctype(path: Path) -> str:
    return mimetypes.guess_type(path.name)[0] or "application/octet-stream"


@dataclass(frozen=True)
class _Static:
    data: bytes
    gz: bytes | None
    ctype: str
    etag: str
    cache_control: str


_cache: dict[Path, tuple[tuple[int, int], _Static]] = {}
_cache_lock = threading.Lock()


def _load(rel: str) -> _Static | None:
    """The file, read and gzipped once and kept until its size or mtime changes."""
    target = _resolve(rel)
    if target is None:
        return None
    st = target.stat()
    key = (st.st_mtime_ns, st.st_size)
    with _cache_lock:
        hit = _cache.get(target)
    if hit is not None and hit[0] == key:
        return hit[1]
    data, ctype = target.read_bytes(), _ctype(target)
    gz = None
    if len(data) >= _GZIP_MIN_BYTES and ctype.startswith(_COMPRESSIBLE):
        gz = gzip.compress(data, compresslevel=6, mtime=0)
    vendor = target.is_relative_to(WEB_DIR.resolve() / "vendor")
    item = _Static(
        data=data,
        gz=gz,
        ctype=ctype,
        etag=f'"{key[0]:x}-{key[1]:x}"',
        cache_control=f"public, max-age={VENDOR_MAX_AGE_S}" if vendor else "no-cache",
    )
    with _cache_lock:
        _cache[target] = (key, item)
    return item


def send_static(handler: BaseHTTPRequestHandler, rel: str, cors: bool = False) -> bool:
    """Reply with a file under `web/`: ETag revalidation, gzip when the browser accepts it.

    Returns False, having sent nothing, when the file is missing or outside `web/`.
    """
    item = _load(rel)
    if item is None:
        return False
    if handler.headers.get("If-None-Match") == item.etag:
        handler.send_response(304)
        handler.send_header("ETag", item.etag)
        handler.send_header("Cache-Control", item.cache_control)
        if cors:
            handler.send_header("Access-Control-Allow-Origin", "*")
        handler.end_headers()
        return True
    body = item.data
    use_gz = item.gz is not None and "gzip" in (handler.headers.get("Accept-Encoding") or "")
    if use_gz:
        body = item.gz  # type: ignore[assignment]
    handler.send_response(200)
    handler.send_header("Content-Type", item.ctype)
    if use_gz:
        handler.send_header("Content-Encoding", "gzip")
    if item.gz is not None:
        handler.send_header("Vary", "Accept-Encoding")
    handler.send_header("ETag", item.etag)
    handler.send_header("Cache-Control", item.cache_control)
    if cors:
        handler.send_header("Access-Control-Allow-Origin", "*")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)
    return True


def ist_string(t_s: int) -> str:
    """A simulated Unix time as IST text. Formats the given value; never reads the wall clock."""
    return dt.datetime.fromtimestamp(t_s, _IST).strftime("%a %d %b %H:%M IST")


# A browser that reloads or closes a page drops its open requests; the reply then has nowhere to go.
CLIENT_GONE = (BrokenPipeError, ConnectionResetError, ConnectionAbortedError)


class QuietHTTPServer(ThreadingHTTPServer):
    """Threaded server that does not print a traceback when a viewer disconnects mid-reply."""

    daemon_threads = True
    # A dashboard page opens several requests at once; the default backlog of 5 can refuse some.
    request_queue_size = 64

    def handle_error(self, request, client_address) -> None:  # noqa: ANN001 (socketserver API)
        if isinstance(sys.exc_info()[1], CLIENT_GONE):
            return
        super().handle_error(request, client_address)
