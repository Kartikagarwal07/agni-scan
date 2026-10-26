"""GeoJSON output conforming to docs/DATA_CONTRACT.md v1.0.0, and its validator.

Each Feature carries exactly the eight contract properties. Provenance,
scoring parameters and input checksums go in a top-level ``metadata``
foreign member of the FeatureCollection (permitted by RFC 7946 §6.1), so the
per-feature schema stays exactly as agreed.
"""

from __future__ import annotations

import datetime as dt
import json
import math
import re
from pathlib import Path

import shapely
from shapely.geometry import Polygon
from shapely.geometry.polygon import orient

from .boundary import PUNJAB_ENVELOPE, to_wgs84

REQUIRED_PROPERTIES = (
    "cell_id",
    "district",
    "risk_score",
    "risk_level",
    "observed_fire_count",
    "evidence_completeness",
    "verification_status",
    "analysis_date",
)
RISK_LEVELS = ("low", "medium", "high", "unknown")
VERIFICATION_STATUSES = ("unverified", "scheduled", "verified_fire", "verified_no_fire")
PROVENANCE_SYNTHETIC = "SYNTHETIC_DEMONSTRATION_NOT_REAL_SATELLITE_DATA"
PROVENANCE_OBSERVED = "PROCESSED_USER_SUPPLIED_FIRMS_OBSERVATIONS"
# Written only when the operator explicitly allows cells without a district;
# the contract requires a Punjab district name, so such output is non-conforming.
DISTRICT_UNAVAILABLE = "UNAVAILABLE"
COORD_DECIMALS = 6

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _ring(coords) -> list[list[float]]:
    out: list[list[float]] = []
    for x, y in coords:
        pos = [round(x, COORD_DECIMALS), round(y, COORD_DECIMALS)]
        if not out or out[-1] != pos:
            out.append(pos)
    if out[0] != out[-1]:
        out.append(list(out[0]))
    return out


def polygon_to_geojson(poly_projected: Polygon) -> dict:
    """Reproject to WGS84 and encode with RFC 7946 winding (exterior CCW)."""
    poly = orient(to_wgs84(poly_projected), sign=1.0)
    rings = [_ring(poly.exterior.coords)] + [_ring(r.coords) for r in poly.interiors]
    rings = [r for r in rings if len(r) >= 4]
    return {"type": "Polygon", "coordinates": rings}


def build_feature(cell_id: str, geometry: dict, properties: dict) -> dict:
    props = {k: properties[k] for k in REQUIRED_PROPERTIES}
    return {"type": "Feature", "id": cell_id, "geometry": geometry, "properties": props}


def build_feature_collection(features: list[dict], metadata: dict) -> dict:
    return {"type": "FeatureCollection", "metadata": metadata, "features": features}


def write_geojson(path: str | Path, collection: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(collection, fh, ensure_ascii=False, separators=(",", ":"))
        fh.write("\n")


def _is_number(v) -> bool:
    return isinstance(v, (int, float)) and not isinstance(v, bool) and math.isfinite(v)


def _expected_level(score) -> str:
    if score is None:
        return "unknown"
    return "high" if score >= 70 else "medium" if score >= 40 else "low"


def _check_geometry(geom, where: str, errors: list[str], check_envelope: bool) -> None:
    if not isinstance(geom, dict) or geom.get("type") != "Polygon":
        errors.append(f"{where}: geometry must be a Polygon (rule 1)")
        return
    rings = geom.get("coordinates")
    if not isinstance(rings, list) or not rings:
        errors.append(f"{where}: Polygon has no rings")
        return
    e = PUNJAB_ENVELOPE
    for r_i, ring in enumerate(rings):
        if not isinstance(ring, list) or not ring:
            errors.append(f"{where}: ring {r_i} is empty or malformed")
            continue
        if ring[0] != ring[-1]:
            errors.append(f"{where}: ring {r_i} is not closed (rule 2)")
        if len(ring) < 4:
            errors.append(f"{where}: ring {r_i} needs at least 4 positions")
        for pos in ring:
            if not (isinstance(pos, list) and len(pos) == 2 and all(_is_number(v) for v in pos)):
                errors.append(f"{where}: ring {r_i} has malformed position {pos!r}")
                break
            lon, lat = pos
            if not (-180 <= lon <= 180 and -90 <= lat <= 90):
                errors.append(f"{where}: position {pos!r} is outside lon/lat ranges")
                break
            if check_envelope and not (e[0] <= lon <= e[2] and e[1] <= lat <= e[3]):
                errors.append(
                    f"{where}: position {pos!r} is outside the Punjab envelope; "
                    "check [longitude, latitude] order (rule 4)"
                )
                break
    else:
        try:
            if not shapely.is_valid(Polygon(rings[0], rings[1:])):
                errors.append(f"{where}: polygon is not a valid simple geometry")
        except Exception:
            errors.append(f"{where}: polygon rings cannot be parsed")


def validate_feature_collection(
    data: dict,
    *,
    require_metadata: bool = True,
    allow_unavailable_district: bool = False,
    check_envelope: bool = True,
) -> list[str]:
    """Return a list of contract violations (empty when the file conforms)."""
    errors: list[str] = []
    if not isinstance(data, dict) or data.get("type") != "FeatureCollection":
        return ["top level must be a GeoJSON FeatureCollection"]
    features = data.get("features")
    if not isinstance(features, list):
        return ["'features' must be a list"]

    meta = data.get("metadata")
    synthetic = False
    if meta is None:
        if require_metadata:
            errors.append("missing 'metadata' member with data_provenance (rule 7: mock data must be labelled)")
    elif not isinstance(meta, dict):
        errors.append("'metadata' must be an object")
    else:
        prov = meta.get("data_provenance")
        if prov not in (PROVENANCE_SYNTHETIC, PROVENANCE_OBSERVED):
            errors.append(f"metadata.data_provenance must be {PROVENANCE_SYNTHETIC!r} or {PROVENANCE_OBSERVED!r}")
        synthetic = prov == PROVENANCE_SYNTHETIC
        if meta.get("synthetic") is not synthetic:
            errors.append("metadata.synthetic must be a boolean consistent with data_provenance")
        if synthetic and not meta.get("disclaimer"):
            errors.append("synthetic output must carry metadata.disclaimer")

    seen: set[str] = set()
    for i, feat in enumerate(features):
        where = f"feature {i}"
        if not isinstance(feat, dict) or feat.get("type") != "Feature":
            errors.append(f"{where}: must be a GeoJSON Feature")
            continue
        props = feat.get("properties")
        if not isinstance(props, dict):
            errors.append(f"{where}: missing properties")
            continue
        cid = props.get("cell_id")
        if isinstance(cid, str):
            where = f"feature {i} ({cid})"
        missing = [k for k in REQUIRED_PROPERTIES if k not in props]
        extra = sorted(set(props) - set(REQUIRED_PROPERTIES))
        if missing:
            errors.append(f"{where}: missing properties {missing}")
        if extra:
            errors.append(f"{where}: properties not in the contract {extra}")

        if not isinstance(cid, str) or not cid:
            errors.append(f"{where}: cell_id must be a non-empty string")
        else:
            if cid in seen:
                errors.append(f"{where}: duplicate cell_id")
            seen.add(cid)
            if feat.get("id") != cid:
                errors.append(f"{where}: Feature.id {feat.get('id')!r} must equal properties.cell_id (rule 3)")
            if synthetic and not cid.startswith("SYNTH-"):
                errors.append(f"{where}: synthetic output cell_id must start with 'SYNTH-'")

        district = props.get("district")
        if not isinstance(district, str) or not district.strip():
            errors.append(f"{where}: district must be a non-empty string")
        elif district == DISTRICT_UNAVAILABLE and not allow_unavailable_district:
            errors.append(f"{where}: district is {DISTRICT_UNAVAILABLE!r}; contract requires a Punjab district")

        score = props.get("risk_score", "missing")
        if score is not None and not (_is_number(score) and 0 <= score <= 100):
            errors.append(f"{where}: risk_score must be null or a number in 0-100 (got {score!r})")
        level = props.get("risk_level")
        if level not in RISK_LEVELS:
            errors.append(f"{where}: risk_level {level!r} not in {RISK_LEVELS}")
        elif (score is None or _is_number(score)) and level != _expected_level(score):
            errors.append(f"{where}: risk_level {level!r} inconsistent with risk_score {score!r}")

        count = props.get("observed_fire_count")
        if not (isinstance(count, int) and not isinstance(count, bool) and count >= 0):
            errors.append(f"{where}: observed_fire_count must be an integer >= 0")
        comp = props.get("evidence_completeness")
        if not (_is_number(comp) and 0 <= comp <= 1):
            errors.append(f"{where}: evidence_completeness must be a number in 0-1")
        if props.get("verification_status") not in VERIFICATION_STATUSES:
            errors.append(f"{where}: verification_status must be one of {VERIFICATION_STATUSES}")
        date = props.get("analysis_date")
        try:
            ok = isinstance(date, str) and bool(_DATE_RE.match(date)) and bool(dt.date.fromisoformat(date))
        except ValueError:
            ok = False
        if not ok:
            errors.append(f"{where}: analysis_date must be a valid YYYY-MM-DD date")

        _check_geometry(feat.get("geometry"), where, errors, check_envelope)
    return errors
