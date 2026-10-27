"""Download NASA FIRMS VIIRS detections through the FIRMS Area API.

API: https://firms.modaps.eosdis.nasa.gov/api/area/
    /api/area/csv/<MAP_KEY>/<SOURCE>/<west,south,east,north>/<DAY_RANGE>[/<DATE>]

* DAY_RANGE is 1-5. Without DATE the range is TODAY-(DAY_RANGE-1) .. TODAY;
  with DATE it is DATE .. DATE+(DAY_RANGE-1) (UTC acq_date).
* Errors come back as HTTP 400 with a short text body (e.g. "Invalid MAP_KEY.").
* The free MAP_KEY allows 5000 transactions per 10 minutes.

The MAP_KEY is read from the FIRMS_MAP_KEY environment variable or from an env
file (default: the repository's .env.local). It is never written to disk or printed:
the manifest records the request URL with the key replaced by <MAP_KEY>.

Each fetch writes one CSV per source plus manifest.json (SHA-256 of every file),
so a pipeline run can later be reproduced from exactly the same raw inputs.
Near-real-time (NRT) files are replaced by standard-processing (SP) data weeks
later, so re-downloading the same dates is not guaranteed to return identical rows.
"""

from __future__ import annotations

import datetime as dt
import hashlib
import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .errors import PipelineError

API_ROOT = "https://firms.modaps.eosdis.nasa.gov/api/area/csv"
NRT_SOURCES = ("VIIRS_SNPP_NRT", "VIIRS_NOAA20_NRT", "VIIRS_NOAA21_NRT")
SP_SOURCES = ("VIIRS_SNPP_SP", "VIIRS_NOAA20_SP", "VIIRS_NOAA21_SP")
VALID_SOURCES = NRT_SOURCES + SP_SOURCES
MAX_DAY_RANGE = 5
DEFAULT_ENV_FILE = Path(__file__).resolve().parents[3] / ".env.local"
_KEY_RE = re.compile(r"^[A-Za-z0-9]{16,64}$")

# (url, timeout) -> (status, body bytes). Injectable so tests never touch the network.
Opener = Callable[[str, float], tuple[int, bytes]]


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float

    def __post_init__(self):
        if not (-180 <= self.west < self.east <= 180 and -90 <= self.south < self.north <= 90):
            raise PipelineError(f"invalid bounding box {self.as_param()} (expected west,south,east,north)")

    def as_param(self) -> str:
        return f"{self.west:g},{self.south:g},{self.east:g},{self.north:g}"

    @classmethod
    def parse(cls, text: str) -> "BBox":
        try:
            w, s, e, n = (float(v) for v in text.split(","))
        except ValueError:
            raise PipelineError(f"--bbox {text!r} must be four numbers: west,south,east,north") from None
        return cls(w, s, e, n)

    @classmethod
    def around(cls, bounds: tuple[float, float, float, float], pad_deg: float = 0.05) -> "BBox":
        """Padded box around geometry bounds, rounded outward to 0.01 degree."""
        w, s, e, n = bounds
        return cls(
            math.floor((w - pad_deg) * 100) / 100,
            math.floor((s - pad_deg) * 100) / 100,
            math.ceil((e + pad_deg) * 100) / 100,
            math.ceil((n + pad_deg) * 100) / 100,
        )


def read_map_key(env_file: Path | None = DEFAULT_ENV_FILE) -> str:
    """FIRMS_MAP_KEY from the environment, else from a KEY=value env file."""
    key = os.environ.get("FIRMS_MAP_KEY", "").strip()
    if not key and env_file is not None and Path(env_file).is_file():
        for line in Path(env_file).read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.partition("=")
            if sep and name.strip() == "FIRMS_MAP_KEY":
                key = value.strip().strip('"').strip("'")
    if not key:
        raise PipelineError(
            "FIRMS_MAP_KEY is not set. Put FIRMS_MAP_KEY=<your key> in .env.local at the repository root, "
            "or set it in the shell ($env:FIRMS_MAP_KEY = '...' in PowerShell)."
        )
    if not _KEY_RE.match(key):
        raise PipelineError("FIRMS_MAP_KEY does not look like a FIRMS MAP_KEY (expected 16-64 letters and digits).")
    return key


def request_url(map_key: str, source: str, bbox: BBox, day_range: int, start_date: dt.date | None) -> str:
    url = f"{API_ROOT}/{map_key}/{source}/{bbox.as_param()}/{day_range}"
    return f"{url}/{start_date.isoformat()}" if start_date else url


def date_range(day_range: int, start_date: dt.date | None, today: dt.date) -> tuple[dt.date, dt.date]:
    """The UTC acq_date range FIRMS returns for these parameters."""
    if start_date is None:
        return today - dt.timedelta(days=day_range - 1), today
    return start_date, start_date + dt.timedelta(days=day_range - 1)


def _urlopen(url: str, timeout: float) -> tuple[int, bytes]:
    request = urllib.request.Request(url, headers={"User-Agent": "agni-scan-pipeline"})
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


@dataclass
class FetchedFile:
    source: str
    path: Path
    rows: int
    sha256: str
    bytes: int


def fetch_firms(
    *,
    out_dir: Path,
    bbox: BBox,
    day_range: int,
    start_date: dt.date | None = None,
    sources: tuple[str, ...] = NRT_SOURCES,
    map_key: str,
    opener: Opener = _urlopen,
    timeout: float = 120.0,
    now: dt.datetime | None = None,
) -> tuple[list[FetchedFile], dict]:
    """Download each source to out_dir/<SOURCE>.csv and write out_dir/manifest.json."""
    if not 1 <= day_range <= MAX_DAY_RANGE:
        raise PipelineError(f"day range must be 1-{MAX_DAY_RANGE} (FIRMS Area API limit), got {day_range}")
    unknown = [s for s in sources if s not in VALID_SOURCES]
    if unknown:
        raise PipelineError(f"unknown FIRMS source(s) {unknown}; choose from {list(VALID_SOURCES)}")

    now = now or dt.datetime.now(dt.timezone.utc)
    first, last = date_range(day_range, start_date, now.date())
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    fetched: list[FetchedFile] = []
    for source in sources:
        url = request_url(map_key, source, bbox, day_range, start_date)
        try:
            status, body = opener(url, timeout)
        except OSError as exc:
            raise PipelineError(f"{source}: could not reach FIRMS ({exc.__class__.__name__})") from None
        text = body.decode("utf-8", errors="replace")
        if status != 200 or not text.lstrip("﻿").lower().startswith("latitude,"):
            message = text.strip().splitlines()[0][:200] if text.strip() else "empty response"
            raise PipelineError(f"{source}: FIRMS returned HTTP {status}: {message.replace(map_key, '<MAP_KEY>')}")
        path = out_dir / f"{source}.csv"
        path.write_bytes(body)
        rows = sum(1 for line in text.splitlines()[1:] if line.strip())
        fetched.append(FetchedFile(source, path, rows, hashlib.sha256(body).hexdigest(), len(body)))

    manifest = {
        "fetched_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "api": "NASA FIRMS Area API",
        "bbox": bbox.as_param(),
        "day_range": day_range,
        "start_date": start_date.isoformat() if start_date else None,
        "acq_date_range": [first.isoformat(), last.isoformat()],
        "files": [
            {
                "source": f.source,
                "file": f.path.name,
                "rows": f.rows,
                "bytes": f.bytes,
                "sha256": f.sha256,
                "request": request_url("<MAP_KEY>", f.source, bbox, day_range, start_date),
            }
            for f in fetched
        ],
        "note": "NRT data is superseded by standard-processing (SP) data later; keep these files to reproduce a run.",
        "attribution": "Data from NASA FIRMS (https://firms.modaps.eosdis.nasa.gov).",
    }
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    return fetched, manifest
