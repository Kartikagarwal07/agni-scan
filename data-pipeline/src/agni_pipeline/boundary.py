"""Loading and validation of user-supplied boundary GeoJSON (state and districts).

The pipeline ships no boundary data. Operators must supply an authoritative
Punjab state boundary and, for district attribution, authoritative district
boundaries. Both must be WGS84 longitude/latitude GeoJSON (RFC 7946).

Checks performed:

* the file is GeoJSON with Polygon/MultiPolygon geometry only;
* a legacy ``crs`` member, if present, names WGS84 (CRS84 / EPSG:4326);
  anything else is rejected rather than guessed at;
* every position is a finite [longitude, latitude] pair inside valid ranges;
* geometries are valid (or repaired with ``make_valid`` when asked to);
* the extent lies within a loose Punjab envelope, which catches swapped
  coordinate order and projected coordinates mislabelled as degrees;
* the state area is compared with the published area of Punjab; a large
  difference is reported as a warning (it can indicate a wrong file).
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import MultiPolygon, Polygon, shape
from shapely.validation import explain_validity

from .errors import BoundaryError
from .firms import file_sha256

WGS84 = "EPSG:4326"
# WGS 84 / UTM zone 43N covers 72°E-78°E, which contains all of Punjab
# (about 73.9°E-76.9°E), so distortion of cell sizes stays small.
PROJECTED_CRS = "EPSG:32643"

# Loose envelope around Punjab, India (lon_min, lat_min, lon_max, lat_max).
PUNJAB_ENVELOPE = (73.5, 29.3, 77.5, 32.8)
# Census of India area of Punjab; used only for a plausibility warning.
PUNJAB_REFERENCE_AREA_KM2 = 50_362
AREA_WARNING_TOLERANCE = 0.15

_ACCEPTED_CRS_NAMES = {
    "urn:ogc:def:crs:ogc:1.3:crs84",
    "urn:ogc:def:crs:ogc::crs84",
    "urn:ogc:def:crs:epsg::4326",
    "epsg:4326",
    "crs84",
}

SYNTHETIC_MARKER = "agni_scan_synthetic"

_to_projected = Transformer.from_crs(WGS84, PROJECTED_CRS, always_xy=True)
_to_wgs84 = Transformer.from_crs(PROJECTED_CRS, WGS84, always_xy=True)


def _apply(transformer: Transformer, geom):
    def fn(coords: np.ndarray) -> np.ndarray:
        x, y = transformer.transform(coords[:, 0], coords[:, 1])
        return np.column_stack([x, y])

    return shapely.transform(geom, fn)


def to_projected(geom):
    return _apply(_to_projected, geom)


def to_wgs84(geom):
    return _apply(_to_wgs84, geom)


def project_points(lons, lats) -> tuple[np.ndarray, np.ndarray]:
    x, y = _to_projected.transform(np.asarray(lons, dtype=float), np.asarray(lats, dtype=float))
    return np.asarray(x), np.asarray(y)


@dataclass
class Region:
    """A validated polygonal area in both WGS84 and the projected CRS."""

    name: str
    geometry_wgs84: Polygon | MultiPolygon
    geometry_projected: Polygon | MultiPolygon
    source: Path
    sha256: str
    synthetic: bool
    warnings: list[str] = field(default_factory=list)

    @property
    def area_km2(self) -> float:
        return self.geometry_projected.area / 1e6


@dataclass
class District:
    name: str
    geometry_projected: Polygon | MultiPolygon


@dataclass
class DistrictSet:
    districts: list[District]
    source: Path
    sha256: str
    synthetic: bool
    name_field: str
    warnings: list[str] = field(default_factory=list)


def _read_geojson(path: Path) -> dict:
    if not path.is_file():
        raise BoundaryError(f"GeoJSON not found: {path}")
    try:
        with open(path, encoding="utf-8-sig") as fh:
            data = json.load(fh)
    except json.JSONDecodeError as exc:
        raise BoundaryError(f"{path.name}: not valid JSON ({exc})") from None
    if not isinstance(data, dict) or "type" not in data:
        raise BoundaryError(f"{path.name}: not a GeoJSON object (missing 'type')")
    return data


def _check_crs(data: dict, label: str) -> None:
    crs = data.get("crs")
    if crs is None:
        return  # RFC 7946: no crs member means WGS84 lon/lat.
    name = None
    if isinstance(crs, dict):
        props = crs.get("properties") or {}
        name = props.get("name") or (f"EPSG:{props['code']}" if "code" in props else None)
    if not isinstance(name, str) or name.strip().lower() not in _ACCEPTED_CRS_NAMES:
        raise BoundaryError(
            f"{label}: declares CRS {name or crs!r}; only WGS84 longitude/latitude (EPSG:4326 / CRS84) is accepted. "
            "Reproject the file (e.g. `ogr2ogr -t_srs EPSG:4326 out.geojson in.geojson`) and retry."
        )


def _features(data: dict, label: str) -> list[dict]:
    kind = data["type"]
    if kind == "FeatureCollection":
        feats = data.get("features")
        if not isinstance(feats, list) or not feats:
            raise BoundaryError(f"{label}: FeatureCollection has no features")
        return feats
    if kind == "Feature":
        return [data]
    if kind in ("Polygon", "MultiPolygon"):
        return [{"type": "Feature", "properties": {}, "geometry": data}]
    raise BoundaryError(f"{label}: unsupported GeoJSON type {kind!r}; expected Polygon/MultiPolygon features")


def _check_positions(geom_json: dict, label: str) -> None:
    def walk(node):
        if isinstance(node, (list, tuple)) and node and isinstance(node[0], (int, float)):
            if len(node) < 2:
                raise BoundaryError(f"{label}: coordinate {node!r} has fewer than 2 values")
            lon, lat = node[0], node[1]
            if not (math.isfinite(lon) and math.isfinite(lat)):
                raise BoundaryError(f"{label}: non-finite coordinate {node!r}")
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                raise BoundaryError(
                    f"{label}: coordinate {node!r} is outside longitude/latitude ranges; "
                    "the file is probably in a projected CRS and must be reprojected to EPSG:4326"
                )
            return
        if not isinstance(node, (list, tuple)):
            raise BoundaryError(f"{label}: malformed coordinates")
        for child in node:
            walk(child)

    walk(geom_json.get("coordinates"))


def _parse_geometry(feature: dict, label: str, repair: bool):
    geom_json = feature.get("geometry")
    if not isinstance(geom_json, dict):
        raise BoundaryError(f"{label}: feature has no geometry")
    if geom_json.get("type") not in ("Polygon", "MultiPolygon"):
        raise BoundaryError(f"{label}: geometry type {geom_json.get('type')!r} is not Polygon/MultiPolygon")
    _check_positions(geom_json, label)
    try:
        geom = shape(geom_json)
    except Exception as exc:  # shapely raises several types for malformed rings
        raise BoundaryError(f"{label}: cannot build geometry ({exc})") from None
    if geom.is_empty:
        raise BoundaryError(f"{label}: geometry is empty")
    if not geom.is_valid:
        reason = explain_validity(geom)
        if not repair:
            raise BoundaryError(f"{label}: invalid geometry ({reason}). Fix the file or rerun with --repair-geometry.")
        geom = _polygonal(shapely.make_valid(geom))
        if geom.is_empty:
            raise BoundaryError(f"{label}: geometry is empty after repair ({reason})")
    return geom


def _polygonal(geom):
    """Keep only the polygonal parts of a geometry (e.g. after make_valid)."""
    if isinstance(geom, (Polygon, MultiPolygon)):
        return geom
    parts = [g for g in getattr(geom, "geoms", []) if isinstance(g, (Polygon, MultiPolygon))]
    return shapely.union_all(parts) if parts else Polygon()


def _check_envelope(geom, label: str) -> None:
    minx, miny, maxx, maxy = geom.bounds
    e = PUNJAB_ENVELOPE
    if minx < e[0] or miny < e[1] or maxx > e[2] or maxy > e[3]:
        hint = ""
        if e[1] <= minx <= e[3] and e[0] <= miny <= e[2]:
            hint = " Coordinates look like [latitude, longitude]; GeoJSON requires [longitude, latitude]."
        raise BoundaryError(
            f"{label}: extent ({minx:.4f}, {miny:.4f}, {maxx:.4f}, {maxy:.4f}) is outside the expected Punjab "
            f"envelope {e}.{hint}"
        )


def _is_synthetic(data: dict, features: list[dict]) -> bool:
    if data.get(SYNTHETIC_MARKER) is True:
        return True
    return any((f.get("properties") or {}).get("synthetic") is True for f in features)


def load_region(path: str | Path, *, repair: bool = False) -> Region:
    """Load the Punjab state boundary. Multiple features are dissolved into one."""
    path = Path(path)
    data = _read_geojson(path)
    label = path.name
    _check_crs(data, label)
    features = _features(data, label)
    geoms = [_parse_geometry(f, f"{label} feature {i}", repair) for i, f in enumerate(features)]
    geom = _polygonal(shapely.union_all(geoms))
    _check_envelope(geom, label)
    synthetic = _is_synthetic(data, features)

    projected = to_projected(geom)
    region = Region(
        name=str((features[0].get("properties") or {}).get("name", "Punjab")),
        geometry_wgs84=geom,
        geometry_projected=projected,
        source=path,
        sha256=file_sha256(path),
        synthetic=synthetic,
    )
    ratio = region.area_km2 / PUNJAB_REFERENCE_AREA_KM2
    if not synthetic and abs(ratio - 1) > AREA_WARNING_TOLERANCE:
        region.warnings.append(
            f"{label}: boundary area {region.area_km2:,.0f} km² differs from the reference Punjab area "
            f"({PUNJAB_REFERENCE_AREA_KM2:,} km²) by {abs(ratio - 1):.0%}; confirm this is the full state boundary."
        )
    return region


def load_districts(path: str | Path, name_field: str, region: Region, *, repair: bool = False) -> DistrictSet:
    """Load district boundaries. Features sharing a name are dissolved together."""
    path = Path(path)
    data = _read_geojson(path)
    label = path.name
    _check_crs(data, label)
    features = _features(data, label)

    by_name: dict[str, list] = {}
    for i, f in enumerate(features):
        props = f.get("properties") or {}
        if name_field not in props:
            available = ", ".join(sorted(props)) or "(none)"
            raise BoundaryError(
                f"{label} feature {i}: property {name_field!r} not found (available: {available}); "
                "pass the correct --district-name-field"
            )
        name = props[name_field]
        if not isinstance(name, str) or not name.strip():
            raise BoundaryError(f"{label} feature {i}: district name {name!r} is empty or not a string")
        geom = _parse_geometry(f, f"{label} feature {i} ({name})", repair)
        by_name.setdefault(name.strip(), []).append(geom)

    union_wgs = _polygonal(shapely.union_all([g for gs in by_name.values() for g in gs]))
    _check_envelope(union_wgs, label)

    districts = [
        District(name=name, geometry_projected=to_projected(_polygonal(shapely.union_all(geoms))))
        for name, geoms in sorted(by_name.items())
    ]
    result = DistrictSet(
        districts=districts,
        source=path,
        sha256=file_sha256(path),
        synthetic=_is_synthetic(data, features),
        name_field=name_field,
    )
    covered = shapely.union_all([d.geometry_projected for d in districts])
    coverage = covered.intersection(region.geometry_projected).area / region.geometry_projected.area
    if coverage < 0.99:
        result.warnings.append(
            f"{label}: districts cover only {coverage:.1%} of the state boundary; "
            "cells outside every district will have no district assignment."
        )
    return result
