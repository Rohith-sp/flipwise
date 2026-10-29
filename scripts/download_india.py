"""Download the raw Indian grid data for the constructed truth (PRD §6.2.2, blocker B4).

1. Grid-India NLDC daily Power Supply Position (PSP) reports: regional generation by fuel, per
   day. Listed through Grid-India's public file API, one request per month.
2. Grid-India NLDC SCADA all-India generation by fuel at 10-second resolution, published on
   Mendeley Data (Mukherjee, Kalita, Kumar; CC BY 4.0; doi:10.17632/y58jknpgs8.2): the
   within-day shape of each fuel.

Files land in data/raw/india/ (git-ignored); a manifest with SHA-256 per file goes to
data/manifests/india_raw.json. Existing files are skipped, so the script can be re-run.

Usage: uv run python scripts/download_india.py [--start 2023-03-13] [--end 2024-02-08]
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import re
import ssl
import time
import urllib.request
from pathlib import Path

PSP_API = "https://webapi.grid-india.in/api/v1/file"
PSP_CDN = "https://webcdn.grid-india.in/"
MENDELEY_FILES = (
    "https://data.mendeley.com/public-api/datasets/y58jknpgs8/files?folder_id=root&version=2"
)
HEADERS = {"User-Agent": "Mozilla/5.0 (flipwise research download)"}

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw" / "india"


def _open(req: urllib.request.Request | str, insecure: bool, timeout: int = 120):
    ctx = ssl._create_unverified_context() if insecure else None
    return urllib.request.urlopen(req, timeout=timeout, context=ctx)


def _get(url: str, dest: Path, insecure: bool) -> None:
    req = urllib.request.Request(url, headers=HEADERS)
    tmp = dest.with_suffix(dest.suffix + ".part")
    with _open(req, insecure, timeout=600) as r, tmp.open("wb") as f:
        while chunk := r.read(1 << 20):
            f.write(chunk)
    tmp.replace(dest)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        while chunk := f.read(1 << 20):
            h.update(chunk)
    return h.hexdigest()


def _financial_year(d: dt.date) -> str:
    y = d.year if d.month >= 4 else d.year - 1
    return f"{y}-{str(y + 1)[-2:]}"


def psp_listing(month: dt.date, insecure: bool) -> list[dict]:
    body = json.dumps(
        {
            "_source": "GRDW",
            "_type": "DAILY_PSP_REPORT",
            "_fileDate": _financial_year(month),
            "_month": f"{month.month:02d}",
        }
    ).encode()
    req = urllib.request.Request(
        PSP_API, data=body, method="POST", headers={**HEADERS, "Content-Type": "application/json"}
    )
    with _open(req, insecure, timeout=60) as r:
        return json.load(r).get("retData", [])


def download_psp(start: dt.date, end: dt.date, insecure: bool) -> list[dict]:
    """One spreadsheet per day; .xlsx preferred, .xls if that is all there is."""
    out = RAW / "grid-india" / "psp"
    out.mkdir(parents=True, exist_ok=True)
    wanted: dict[dt.date, dict] = {}
    month = start.replace(day=1)
    while month <= end:
        for rec in psp_listing(month, insecure):
            m = re.match(r"^(\d{2})\.(\d{2})\.(\d{2})_NLDC_PSP", rec.get("Title_", ""))
            path = rec.get("FilePath", "")
            if not m or not path.lower().endswith((".xls", ".xlsx")):
                continue
            day = dt.date(2000 + int(m[3]), int(m[2]), int(m[1]))
            if start <= day <= end and (day not in wanted or path.lower().endswith(".xlsx")):
                wanted[day] = rec
        month = (month + dt.timedelta(days=32)).replace(day=1)
        time.sleep(0.5)  # be polite to a government server

    entries = []
    for day in sorted(wanted):
        path = wanted[day]["FilePath"]
        dest = out / f"{day.isoformat()}_NLDC_PSP{Path(path).suffix.lower()}"
        if not dest.exists():
            _get(PSP_CDN + path, dest, insecure)
            time.sleep(0.3)
        entries.append(
            {
                "date": day.isoformat(),
                "file": dest.relative_to(ROOT).as_posix(),
                "url": PSP_CDN + path,
                "sha256": _sha256(dest),
            }
        )
    missing = [
        (start + dt.timedelta(days=i)).isoformat()
        for i in range((end - start).days + 1)
        if start + dt.timedelta(days=i) not in wanted
    ]
    print(f"PSP: {len(entries)} days downloaded, {len(missing)} missing: {missing[:10]}")
    return entries


MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]


def _mendeley_wanted(name: str, start: dt.date, end: dt.date) -> bool:
    """Monthly files are named like 'March 2023.xlsx'; 2024 onward is one combined file."""
    if name.startswith("January 2024"):
        return end >= dt.date(2024, 1, 1)
    m = re.match(r"^(\w+)\s+(\d{4})\.xlsx$", name)
    if not m:
        return False
    month = next((i + 1 for i, n in enumerate(MONTHS) if m[1].lower().startswith(n[:3].lower())), 0)
    if not month:
        return False
    first = dt.date(int(m[2]), month, 1)
    last = (first + dt.timedelta(days=32)).replace(day=1) - dt.timedelta(days=1)
    return first <= end and last >= start


def download_mendeley(start: dt.date, end: dt.date, insecure: bool) -> list[dict]:
    out = RAW / "mendeley"
    out.mkdir(parents=True, exist_ok=True)
    with _open(urllib.request.Request(MENDELEY_FILES, headers=HEADERS), insecure, timeout=60) as r:
        files = json.load(r)
    entries = []
    for f in sorted(files, key=lambda f: f["filename"]):
        name = f["filename"]
        if not _mendeley_wanted(name, start, end):
            continue
        dest = out / name
        url = f["content_details"]["download_url"]
        if not dest.exists() or dest.stat().st_size != f["size"]:
            print(f"Mendeley: {name} ({f['size'] / 1e6:.0f} MB)")
            _get(url, dest, insecure)
        entries.append(
            {"file": dest.relative_to(ROOT).as_posix(), "url": url, "sha256": _sha256(dest)}
        )
    print(f"Mendeley: {len(entries)} files")
    return entries


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--start", type=dt.date.fromisoformat, default=dt.date(2023, 3, 13))
    ap.add_argument("--end", type=dt.date.fromisoformat, default=dt.date(2024, 2, 8))
    ap.add_argument(
        "--insecure",
        action="store_true",
        help="skip TLS verification (only if the Grid-India certificate fails)",
    )
    ap.add_argument("--skip-mendeley", action="store_true")
    args = ap.parse_args()

    manifest = {
        "retrieved_utc": dt.datetime.now(dt.UTC).isoformat(timespec="seconds"),
        "window": [args.start.isoformat(), args.end.isoformat()],
        "psp": {
            "source": "Grid-India NLDC daily PSP reports",
            "api": PSP_API,
            "files": download_psp(args.start, args.end, args.insecure),
        },
        "mendeley": {
            "source": "Grid-India NLDC SCADA via Mendeley Data",
            "doi": "10.17632/y58jknpgs8.2",
            "licence": "CC BY 4.0",
            "files": []
            if args.skip_mendeley
            else download_mendeley(args.start, args.end, args.insecure),
        },
    }
    path = ROOT / "data" / "manifests" / "india_raw.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2) + "\n")
    print(f"wrote {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
