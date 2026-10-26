"""End-to-end pipeline: inputs -> validated, contract-conforming risk grid."""

from __future__ import annotations

import csv
import datetime as dt
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from . import CONTRACT_VERSION, __version__
from .boundary import PROJECTED_CRS, load_districts, load_region
from .contract import (
    DISTRICT_UNAVAILABLE,
    PROVENANCE_OBSERVED,
    PROVENANCE_SYNTHETIC,
    build_feature,
    build_feature_collection,
    polygon_to_geojson,
    validate_feature_collection,
    write_geojson,
)
from .errors import ContractViolationError, InputValidationError, PipelineError
from .evidence import load_cell_evidence
from .firms import Detection, FirmsLoadResult, RowRejection, apply_quality_filters, deduplicate, load_firms_csv
from .grid import Assignment, GridSpec, assign_detections, assign_districts, generate_grid
from .scoring import CellEvidence, load_config, score_cell

SYNTHETIC_DISCLAIMER = (
    "SYNTHETIC DEMONSTRATION OUTPUT. Generated from fabricated test fixtures. "
    "These are NOT real satellite observations, NOT real Punjab boundaries and NOT real district data. "
    "Do not use for enforcement, reporting or any operational decision."
)
OBSERVED_DISCLAIMER = (
    "Derived from user-supplied NASA FIRMS VIIRS files and boundary files listed in metadata.inputs "
    "(SHA-256 recorded). The pipeline does not verify the authenticity of supplied files."
)
INTERPRETATION = (
    "risk_score is a heuristic verification-priority score for scheduling field checks; it is NOT a "
    "probability of burning or of undetected fire. observed_fire_count counts satellite detections only. "
    "Zero detections do not prove zero burning: cloud or smoke cover, overpass timing and small or "
    "short-lived fires all cause missed detections. risk_score is null (risk_level 'unknown') when the "
    "available evidence is insufficient."
)


@dataclass
class PipelineInputs:
    firms_paths: list[Path]
    boundary_path: Path
    analysis_date: dt.date
    window_days: int = 7
    cell_size_m: int = 5000
    districts_path: Path | None = None
    district_name_field: str = "district"
    history_paths: list[Path] = field(default_factory=list)
    cell_evidence_path: Path | None = None
    config_path: Path | None = None
    declare_synthetic: bool = False
    allow_missing_districts: bool = False
    repair_geometry: bool = False
    strict: bool = False


@dataclass
class PipelineResult:
    collection: dict
    explanations: list[dict]
    rejections: list[RowRejection]
    assignments: list[Assignment]
    warnings: list[str]

    @property
    def metadata(self) -> dict:
        return self.collection["metadata"]


def _load_firms_set(paths: list[Path], label: str, strict: bool) -> tuple[list[FirmsLoadResult], list[RowRejection]]:
    if not paths:
        return [], []
    results = [load_firms_csv(p) for p in paths]
    rejections = [r for res in results for r in res.rejections]
    if strict and rejections:
        listed = "\n  - ".join(f"{r.source_file} line {r.row}: {r.reason}" for r in rejections[:20])
        raise InputValidationError(f"{label}: {len(rejections)} invalid row(s) rejected (--strict):\n  - {listed}")
    return results, rejections


def _file_meta(res: FirmsLoadResult) -> dict:
    rng = res.date_range
    return {
        "file": res.path.name,
        "sha256": res.sha256,
        "rows": res.total_rows,
        "valid_rows": len(res.detections),
        "rejected_rows": len(res.rejections),
        "synthetic": res.synthetic,
        "acq_date_range": [rng[0].isoformat(), rng[1].isoformat()] if rng else None,
    }


def run_pipeline(inp: PipelineInputs) -> PipelineResult:
    if inp.window_days < 1 or inp.window_days > 366:
        raise InputValidationError("window_days must be between 1 and 366")
    if not inp.firms_paths:
        raise InputValidationError("at least one FIRMS CSV is required")
    warnings: list[str] = []
    deviations: list[str] = []
    config = load_config(inp.config_path)

    region = load_region(inp.boundary_path, repair=inp.repair_geometry)
    warnings += region.warnings
    districts = None
    if inp.districts_path is not None:
        districts = load_districts(inp.districts_path, inp.district_name_field, region, repair=inp.repair_geometry)
        warnings += districts.warnings
    elif not inp.allow_missing_districts:
        raise PipelineError(
            "District boundaries are required: DATA_CONTRACT.md requires every cell to carry a Punjab district. "
            "Supply --districts <authoritative district GeoJSON>, or pass --allow-missing-districts to write "
            f"district={DISTRICT_UNAVAILABLE!r} (output will NOT conform to the contract)."
        )

    # FIRMS: analysis window
    firms_results, rejections = _load_firms_set(inp.firms_paths, "FIRMS input", inp.strict)
    all_dets, dupes = deduplicate([d for r in firms_results for d in r.detections])
    filtered = apply_quality_filters(all_dets, min_confidence=config.min_confidence, exclude_fire_types=config.exclude_fire_types)
    end = inp.analysis_date
    start = end - dt.timedelta(days=inp.window_days - 1)
    window = [d for d in filtered.kept if start <= d.acq_date <= end]
    outside_window = len(filtered.kept) - len(window)
    if not all_dets:
        warnings.append("FIRMS input contains no valid detections; every cell will have observed_fire_count=0.")
    input_dates = {d.acq_date for d in all_dets}
    empty_days = [
        (start + dt.timedelta(days=i)).isoformat()
        for i in range(inp.window_days)
        if start + dt.timedelta(days=i) not in input_dates
    ]
    if empty_days:
        warnings.append(
            f"No FIRMS records at all for {len(empty_days)} day(s) of the window ({', '.join(empty_days[:10])}"
            f"{', ...' if len(empty_days) > 10 else ''}); confirm the input covers the full window. "
            "Missing input is not evidence of no fire."
        )

    # FIRMS: optional history (strictly before the window, to avoid double counting)
    history_results, history_rejections = _load_firms_set(inp.history_paths, "historical FIRMS input", inp.strict)
    history: list[Detection] | None = None
    history_dupes = 0
    if history_results:
        hist_all, history_dupes = deduplicate([d for r in history_results for d in r.detections])
        hist_kept = apply_quality_filters(
            hist_all, min_confidence=config.min_confidence, exclude_fire_types=config.exclude_fire_types
        ).kept
        history = [d for d in hist_kept if d.acq_date < start]
    rejections = rejections + history_rejections

    evidence_table = None
    if inp.cell_evidence_path is not None:
        evidence_table = load_cell_evidence(inp.cell_evidence_path, config.attribute_names())
        warnings += evidence_table.warnings

    synthetic = (
        inp.declare_synthetic
        or region.synthetic
        or (districts is not None and districts.synthetic)
        or any(r.synthetic for r in firms_results + history_results)
        or (evidence_table is not None and evidence_table.synthetic)
    )

    spec = GridSpec(inp.cell_size_m, id_prefix="SYNTH-PB" if synthetic else "PB")
    grid = generate_grid(region, spec)
    if not grid.cells:
        raise PipelineError("the boundary produced no grid cells; check the boundary file and cell size")

    no_district = len(grid.cells)
    if districts is not None:
        no_district = assign_districts(grid, districts)
    if no_district:
        if not inp.allow_missing_districts:
            raise PipelineError(
                f"{no_district} grid cell(s) overlap no supplied district boundary. Use complete authoritative "
                f"district boundaries, or pass --allow-missing-districts to write district={DISTRICT_UNAVAILABLE!r} "
                "(output will NOT conform to the contract)."
            )
        deviations.append(
            f"{no_district} cell(s) have district={DISTRICT_UNAVAILABLE!r} because no authoritative district "
            "boundary covers them; DATA_CONTRACT.md requires a Punjab district name."
        )

    window_assign = assign_detections(window, grid, region)
    history_counts = assign_detections(history, grid, region).counts if history is not None else None

    if evidence_table is not None:
        known = {c.cell_id for c in grid.cells}
        unknown = [cid for cid in evidence_table.values if cid not in known]
        if unknown:
            warnings.append(
                f"{evidence_table.path.name}: {len(unknown)} cell_id(s) not in this grid (e.g. {unknown[0]}); "
                "check that the evidence was prepared for the same cell size and provenance prefix."
            )

    analysis_date = end.isoformat()
    features, explanations = [], []
    levels: Counter = Counter()
    for cell in grid.cells:
        observed = window_assign.counts.get(cell.cell_id, 0)
        hist = None if history_counts is None else history_counts.get(cell.cell_id, 0)
        attrs = evidence_table.values.get(cell.cell_id, {}) if evidence_table else {}
        result = score_cell(CellEvidence(observed, hist, attrs), config)
        levels[result.risk_level] += 1
        district = cell.district or DISTRICT_UNAVAILABLE
        props = {
            "cell_id": cell.cell_id,
            "district": district,
            "risk_score": result.risk_score,
            "risk_level": result.risk_level,
            "observed_fire_count": observed,
            "evidence_completeness": result.evidence_completeness,
            "verification_status": "unverified",
            "analysis_date": analysis_date,
        }
        features.append(build_feature(cell.cell_id, polygon_to_geojson(cell.geometry_projected), props))
        row = {
            "cell_id": cell.cell_id,
            "district": district,
            "district_overlap_fraction": None if cell.district_overlap is None else round(cell.district_overlap, 4),
            "observed_fire_count": observed,
            "historical_fire_count": hist,
        }
        for comp in result.components:
            row[f"{comp.name}_value"] = None if comp.value is None else round(comp.value, 4)
            row[f"{comp.name}_weight"] = comp.weight
        row.update(
            evidence_completeness=result.evidence_completeness,
            risk_score=result.risk_score,
            risk_level=result.risk_level,
            score_reason=result.reason,
        )
        explanations.append(row)

    status = window_assign.status_counts
    metadata = {
        "contract_version": CONTRACT_VERSION,
        "data_provenance": PROVENANCE_SYNTHETIC if synthetic else PROVENANCE_OBSERVED,
        "synthetic": synthetic,
        "disclaimer": SYNTHETIC_DISCLAIMER if synthetic else OBSERVED_DISCLAIMER,
        "interpretation": INTERPRETATION,
        "generated_at": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline": {"name": "agni-pipeline", "version": __version__},
        "coordinate_reference_system": "EPSG:4326 (RFC 7946), positions are [longitude, latitude]",
        "analysis_window": {
            "start_date": start.isoformat(),
            "end_date": analysis_date,
            "days": inp.window_days,
            "date_basis": "FIRMS acq_date (UTC)",
        },
        "grid": {
            "projected_crs": PROJECTED_CRS,
            "cell_size_m": spec.cell_size_m,
            "origin_m": [0, 0],
            "cell_id_format": f"{spec.id_prefix}-<size>M-N<floor(northing/size)>-E<floor(easting/size)>[-P<part>]",
            "cell_count": len(grid.cells),
            "dropped_sliver_parts": grid.dropped_slivers,
            "assignment_rule": "pixel centre, half-open cells [x0,x0+size) x [y0,y0+size) in the projected CRS; "
            "each detection counted at most once",
        },
        "district_attribution": {
            "method": "district with the largest area overlap with the cell",
            "source": districts.source.name if districts else None,
            "name_field": districts.name_field if districts else None,
            "cells_without_district": no_district,
        },
        "verification_status_note": "All cells are emitted as 'unverified'; field verification is recorded by the backend.",
        "inputs": {
            "state_boundary": {"file": region.source.name, "sha256": region.sha256, "synthetic": region.synthetic,
                               "area_km2": round(region.area_km2, 1)},
            "district_boundaries": (
                {"file": districts.source.name, "sha256": districts.sha256, "synthetic": districts.synthetic,
                 "district_count": len(districts.districts)} if districts else None
            ),
            "firms_window": [_file_meta(r) for r in firms_results],
            "firms_history": [_file_meta(r) for r in history_results],
            "cell_evidence": (
                {"file": evidence_table.path.name, "sha256": evidence_table.sha256,
                 "synthetic": evidence_table.synthetic, "columns": evidence_table.columns_used}
                if evidence_table else None
            ),
        },
        "detections": {
            "valid_unique": len(all_dets),
            "duplicates_removed": dupes,
            "removed_by_quality_filters": dict(filtered.removed),
            "outside_analysis_window": outside_window,
            "in_window": len(window),
            "assigned_to_cells": status.get("assigned", 0),
            "outside_region": status.get("outside_region", 0),
            "in_dropped_sliver": status.get("in_dropped_sliver", 0),
            "historical_used": None if history is None else len(history),
            "historical_duplicates_removed": history_dupes if history_results else None,
            "rejected_rows": len(rejections),
        },
        "scoring": config.to_metadata(),
        "risk_level_counts": {k: levels.get(k, 0) for k in ("high", "medium", "low", "unknown")},
        "contract_deviations": deviations,
        "warnings": warnings,
    }

    collection = build_feature_collection(features, metadata)
    errors = validate_feature_collection(collection, allow_unavailable_district=inp.allow_missing_districts)
    if errors:
        raise ContractViolationError(errors)
    return PipelineResult(collection, explanations, rejections, window_assign.assignments, warnings)


def _write_csv(path: Path, rows: list[dict], fieldnames: list[str]) -> None:
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: "" if v is None else v for k, v in row.items()})


def write_outputs(result: PipelineResult, out_dir: str | Path) -> dict[str, Path]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    paths = {
        "geojson": out / "risk_grid.geojson",
        "explanations": out / "score_explanations.csv",
        "assignments": out / "detection_assignments.csv",
        "rejections": out / "rejected_rows.csv",
    }
    write_geojson(paths["geojson"], result.collection)
    if result.explanations:
        _write_csv(paths["explanations"], result.explanations, list(result.explanations[0]))
    assign_rows = [
        {
            "source_file": a.detection.source_file,
            "line": a.detection.row,
            "latitude": a.detection.latitude,
            "longitude": a.detection.longitude,
            "acq_date": a.detection.acq_date.isoformat(),
            "acq_time": a.detection.acq_time,
            "satellite": a.detection.satellite,
            "confidence": a.detection.confidence,
            "cell_id": a.cell_id,
            "status": a.status,
        }
        for a in result.assignments
    ]
    _write_csv(paths["assignments"], assign_rows,
               ["source_file", "line", "latitude", "longitude", "acq_date", "acq_time", "satellite",
                "confidence", "cell_id", "status"])
    _write_csv(paths["rejections"], [{"source_file": r.source_file, "line": r.row, "reason": r.reason}
                                     for r in result.rejections], ["source_file", "line", "reason"])
    return paths
