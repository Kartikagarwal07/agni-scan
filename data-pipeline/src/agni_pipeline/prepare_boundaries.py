"""Prepare authoritative boundary files for the pipeline.

Reads a boundary GeoJSON (or a .zip containing exactly one), keeps the features
whose property matches a value (e.g. stcode == "03" for Punjab in the Survey of
India / NWIC files), reprojects them from the file's declared CRS to WGS84, and
writes RFC 7946 GeoJSON ([longitude, latitude], no crs member) that
`agni-pipeline run` accepts.

Zip archives are read in memory; nothing is extracted to disk. The output keeps
a `source` member naming the input file, its SHA-256 and the source CRS, so the
derived file can be traced back to the download.
"""

from __future__ import annotations

import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from pathlib import Path

from pyproj import CRS, Transformer

from .errors import BoundaryError

COORD_DECIMALS = 7  # about 1 cm
_EPSG_RE = re.compile(r"EPSG:+(\d+)$", re.IGNORECASE)
_WGS84 = {"urn:ogc:def:crs:ogc:1.3:crs84", "urn:ogc:def:crs:epsg::4326", "epsg:4326", "crs84"}


@dataclass
class PreparedBoundary:
    path: Path
    features: int
    values: list[str]
    source_crs: str
    input_sha256: str


def _read_input(path: Path) -> tuple[bytes, str]:
    """Raw GeoJSON bytes and a display name; a zip must hold exactly one GeoJSON."""
    if not path.is_file():
        raise BoundaryError(f"boundary input not found: {path}")
    raw = path.read_bytes()
    if not zipfile.is_zipfile(io.BytesIO(raw)):
        return raw, path.name
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        members = [m for m in archive.namelist() if m.lower().endswith((".geojson", ".json")) and not m.endswith("/")]
        if len(members) != 1:
            raise BoundaryError(f"{path.name}: expected exactly one .geojson inside the zip, found {members or 'none'}")
        return archive.read(members[0]), f"{path.name}!{members[0]}"


def _source_crs(data: dict, label: str) -> CRS:
    name = ((data.get("crs") or {}).get("properties") or {}).get("name")
    if name is None or str(name).strip().lower() in _WGS84:
        return CRS.from_epsg(4326)
    match = _EPSG_RE.search(str(name).strip())
    if not match:
        raise BoundaryError(f"{label}: unsupported crs {name!r}; expected an EPSG code")
    return CRS.from_epsg(int(match.group(1)))


def prepare_boundary(
    input_path: str | Path,
    output_path: str | Path,
    *,
    field: str,
    value: str,
    keep_properties: tuple[str, ...] = ("state_name", "stcode", "district", "dtcode", "src_agency"),
    label_field: str | None = None,
) -> PreparedBoundary:
    input_path = Path(input_path)
    raw, label = _read_input(input_path)
    try:
        data = json.loads(raw.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BoundaryError(f"{label}: not valid GeoJSON ({exc})") from None
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise BoundaryError(f"{label}: expected a GeoJSON FeatureCollection")

    crs = _source_crs(data, label)
    transform = None if crs.to_epsg() == 4326 else Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    def reproject(node):
        if node and isinstance(node[0], (int, float)):
            x, y = (node[0], node[1]) if transform is None else transform.transform(node[0], node[1])
            return [round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)]
        return [reproject(child) for child in node]

    matched = [f for f in data["features"] if str((f.get("properties") or {}).get(field, "")).strip() == value]
    if not matched:
        seen = sorted({str((f.get("properties") or {}).get(field)) for f in data["features"]})[:20]
        raise BoundaryError(f"{label}: no feature has {field} == {value!r} (values seen: {seen})")

    features = []
    for f in matched:
        geom = f.get("geometry") or {}
        if geom.get("type") not in ("Polygon", "MultiPolygon"):
            raise BoundaryError(f"{label}: matched feature has geometry {geom.get('type')!r}, not Polygon/MultiPolygon")
        props = f.get("properties") or {}
        kept = {k: props[k] for k in keep_properties if k in props}
        features.append(
            {"type": "Feature", "properties": kept, "geometry": {"type": geom["type"], "coordinates": reproject(geom["coordinates"])}}
        )

    sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
    agencies = sorted({str((f.get("properties") or {}).get("src_agency")) for f in matched if (f.get("properties") or {}).get("src_agency")})
    out = {
        "type": "FeatureCollection",
        "source": {
            "file": label,
            "sha256": sha,
            "source_crs": f"EPSG:{crs.to_epsg()}",
            "filter": f"{field} == {value!r}",
            "src_agency": agencies,
            "prepared_by": "agni-pipeline prepare-boundaries",
        },
        "features": features,
    }
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")

    values = sorted(str(f["properties"].get(label_field, "")) for f in features) if label_field else []
    return PreparedBoundary(output_path, len(features), values, f"EPSG:{crs.to_epsg()}", sha)
