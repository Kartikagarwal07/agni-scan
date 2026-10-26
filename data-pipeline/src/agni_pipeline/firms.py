"""Ingestion and validation of locally supplied NASA FIRMS VIIRS CSV files.

Supported layout variations (all documented FIRMS VIIRS 375 m products):

* NRT CSV (FIRMS API / "Active fire data" downloads): latitude, longitude,
  bright_ti4, scan, track, acq_date, acq_time, satellite, instrument,
  confidence, version, bright_ti5, frp, daynight.
* Standard-processing archive CSV ("Archive download"): same columns plus
  ``type`` (0 presumed vegetation fire, 1 active volcano, 2 other static land
  source, 3 offshore).
* Upper-case headers, as produced when exporting the FIRMS shapefile/DBF
  products to CSV (LATITUDE, ACQ_DATE, ...). Header matching is
  case-insensitive and ignores surrounding whitespace and a UTF-8 BOM.
* ``confidence`` as VIIRS letter codes (l, n, h) or their spelled-out form
  (low, nominal, high). Numeric 0-100 confidence is the MODIS convention and
  is rejected, because this pipeline is VIIRS-only.
* ``acq_time`` as HHMM with or without leading zeros (``56`` == ``0056``).

Only ``latitude``, ``longitude`` and ``acq_date`` are required. Other
recognised columns are validated when present; unrecognised columns are
ignored. Nothing is downloaded and no observation is ever synthesised here.

Synthetic fixtures carry a ``data_label`` column with the value
``SYNTHETIC``; any such row marks the whole file as synthetic.
"""

from __future__ import annotations

import csv
import datetime as dt
import hashlib
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .errors import InputValidationError

REQUIRED_COLUMNS = ("latitude", "longitude", "acq_date")
OPTIONAL_COLUMNS = (
    "acq_time",
    "confidence",
    "satellite",
    "instrument",
    "frp",
    "type",
    "daynight",
    "version",
    "data_label",
)

CONFIDENCE_LEVELS = ("low", "nominal", "high")
_CONFIDENCE_CODES = {
    "l": "low",
    "low": "low",
    "n": "nominal",
    "nominal": "nominal",
    "h": "high",
    "high": "high",
}
FIRE_TYPES = {0: "presumed vegetation fire", 1: "active volcano", 2: "other static land source", 3: "offshore"}
SYNTHETIC_LABEL = "SYNTHETIC"

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_TIME_RE = re.compile(r"^\d{1,4}$")


@dataclass(frozen=True)
class Detection:
    """One validated satellite fire detection (pixel centre)."""

    source_file: str
    row: int
    latitude: float
    longitude: float
    acq_date: dt.date
    acq_time: str | None
    confidence: str | None
    satellite: str | None
    instrument: str | None
    frp: float | None
    fire_type: int | None


@dataclass(frozen=True)
class RowRejection:
    source_file: str
    row: int
    reason: str


@dataclass
class FirmsLoadResult:
    path: Path
    sha256: str
    columns: list[str]
    detections: list[Detection]
    rejections: list[RowRejection]
    synthetic: bool
    total_rows: int

    @property
    def date_range(self) -> tuple[dt.date, dt.date] | None:
        if not self.detections:
            return None
        dates = [d.acq_date for d in self.detections]
        return min(dates), max(dates)


@dataclass
class FilterResult:
    kept: list[Detection]
    removed: Counter = field(default_factory=Counter)


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_header(name: str) -> str:
    return name.replace("﻿", "").strip().lower()


def _parse_float(value: str, name: str) -> float:
    try:
        number = float(value)
    except ValueError:
        raise ValueError(f"{name} {value!r} is not a number") from None
    if not math.isfinite(number):
        raise ValueError(f"{name} {value!r} is not finite")
    return number


def _parse_row(raw: dict[str, str], source: str, row: int) -> Detection:
    def get(col: str) -> str:
        return (raw.get(col) or "").strip()

    for col in REQUIRED_COLUMNS:
        if not get(col):
            raise ValueError(f"required field {col!r} is empty")

    latitude = _parse_float(get("latitude"), "latitude")
    if not -90.0 <= latitude <= 90.0:
        raise ValueError(f"latitude {latitude} outside [-90, 90]")
    longitude = _parse_float(get("longitude"), "longitude")
    if not -180.0 <= longitude <= 180.0:
        raise ValueError(f"longitude {longitude} outside [-180, 180]")

    date_text = get("acq_date")
    if not _DATE_RE.match(date_text):
        raise ValueError(f"acq_date {date_text!r} is not YYYY-MM-DD")
    try:
        acq_date = dt.date.fromisoformat(date_text)
    except ValueError:
        raise ValueError(f"acq_date {date_text!r} is not a valid calendar date") from None

    acq_time = None
    if time_text := get("acq_time"):
        if not _TIME_RE.match(time_text):
            raise ValueError(f"acq_time {time_text!r} is not HHMM")
        acq_time = time_text.zfill(4)
        if int(acq_time[:2]) > 23 or int(acq_time[2:]) > 59:
            raise ValueError(f"acq_time {time_text!r} is not a valid UTC time of day")

    confidence = None
    if conf_text := get("confidence"):
        confidence = _CONFIDENCE_CODES.get(conf_text.lower())
        if confidence is None:
            if re.fullmatch(r"\d+(\.\d+)?", conf_text):
                raise ValueError(
                    f"numeric confidence {conf_text!r} is the MODIS convention; only VIIRS (l/n/h) is supported"
                )
            raise ValueError(f"confidence {conf_text!r} is not one of l, n, h")

    instrument = get("instrument") or None
    if instrument is not None and instrument.upper() != "VIIRS":
        raise ValueError(f"instrument {instrument!r} is not VIIRS; only VIIRS detections are supported")

    frp = None
    if frp_text := get("frp"):
        frp = _parse_float(frp_text, "frp")
        if frp < 0:
            raise ValueError(f"frp {frp} is negative")

    fire_type = None
    if type_text := get("type"):
        if not re.fullmatch(r"\d+", type_text) or int(type_text) not in FIRE_TYPES:
            raise ValueError(f"type {type_text!r} is not one of {sorted(FIRE_TYPES)}")
        fire_type = int(type_text)

    return Detection(
        source_file=source,
        row=row,
        latitude=latitude,
        longitude=longitude,
        acq_date=acq_date,
        acq_time=acq_time,
        confidence=confidence,
        satellite=get("satellite") or None,
        instrument=instrument,
        frp=frp,
        fire_type=fire_type,
    )


def load_firms_csv(path: str | Path) -> FirmsLoadResult:
    """Read and validate one FIRMS VIIRS CSV.

    Structural problems (missing file, missing required columns, duplicate
    headers) raise :class:`InputValidationError`. Problems with individual
    rows are collected as :class:`RowRejection` entries so the operator gets
    the full list in one run. Row numbers are 1-based file line numbers
    (the header is line 1).
    """
    path = Path(path)
    if not path.is_file():
        raise InputValidationError(f"FIRMS CSV not found: {path}")

    detections: list[Detection] = []
    rejections: list[RowRejection] = []
    synthetic = False
    total = 0
    with open(path, newline="", encoding="utf-8-sig") as fh:
        reader = csv.reader(fh)
        try:
            header = next(reader)
        except StopIteration:
            raise InputValidationError(f"{path.name}: file is empty (no header row)") from None
        columns = [_normalise_header(h) for h in header]
        dupes = sorted(c for c, n in Counter(columns).items() if n > 1 and c)
        if dupes:
            raise InputValidationError(f"{path.name}: duplicate column(s) after case-folding: {', '.join(dupes)}")
        missing = [c for c in REQUIRED_COLUMNS if c not in columns]
        if missing:
            raise InputValidationError(
                f"{path.name}: missing required column(s) {', '.join(missing)}; "
                f"found: {', '.join(columns) or '(none)'}. Expected a NASA FIRMS VIIRS CSV."
            )

        for line_no, values in enumerate(reader, start=2):
            if not any(v.strip() for v in values):
                continue
            total += 1
            if len(values) != len(columns):
                rejections.append(
                    RowRejection(path.name, line_no, f"has {len(values)} fields, header has {len(columns)}")
                )
                continue
            raw = dict(zip(columns, values))
            if raw.get("data_label", "").strip().upper() == SYNTHETIC_LABEL:
                synthetic = True
            try:
                detections.append(_parse_row(raw, path.name, line_no))
            except ValueError as exc:
                rejections.append(RowRejection(path.name, line_no, str(exc)))

    return FirmsLoadResult(
        path=path,
        sha256=file_sha256(path),
        columns=columns,
        detections=detections,
        rejections=rejections,
        synthetic=synthetic,
        total_rows=total,
    )


def deduplicate(detections: list[Detection]) -> tuple[list[Detection], int]:
    """Drop repeated detections (same position, date, time and satellite).

    Overlapping downloads (e.g. an NRT file and an archive file for the same
    days) otherwise double-count the same pixel.
    """
    seen: set[tuple] = set()
    unique: list[Detection] = []
    for d in detections:
        key = (round(d.latitude, 5), round(d.longitude, 5), d.acq_date, d.acq_time, d.satellite)
        if key in seen:
            continue
        seen.add(key)
        unique.append(d)
    return unique, len(detections) - len(unique)


def apply_quality_filters(
    detections: list[Detection],
    *,
    min_confidence: str | None,
    exclude_fire_types: tuple[int, ...] | list[int],
) -> FilterResult:
    """Remove detections below ``min_confidence`` or of excluded FIRMS types.

    A detection without a confidence value is removed when a minimum
    confidence is configured, since it cannot be shown to meet it.
    """
    result = FilterResult(kept=[])
    threshold = CONFIDENCE_LEVELS.index(min_confidence) if min_confidence else None
    excluded = set(exclude_fire_types)
    for d in detections:
        if d.fire_type is not None and d.fire_type in excluded:
            result.removed[f"type_{d.fire_type}_{FIRE_TYPES[d.fire_type].replace(' ', '_')}"] += 1
        elif threshold is not None and d.confidence is None:
            result.removed["confidence_missing"] += 1
        elif threshold is not None and CONFIDENCE_LEVELS.index(d.confidence) < threshold:
            result.removed[f"confidence_below_{min_confidence}"] += 1
        else:
            result.kept.append(d)
    return result
