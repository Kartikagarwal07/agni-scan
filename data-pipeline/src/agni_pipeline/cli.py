"""Command-line interface: ``agni-pipeline run | validate | demo``."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .contract import serialize_geojson, validate_feature_collection
from .errors import ContractViolationError, PipelineError
from .pipeline import PipelineInputs, PipelineResult, run_pipeline, write_outputs

PIPELINE_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = PIPELINE_ROOT / "fixtures" / "synthetic"
REFERENCE_DEMO = PIPELINE_ROOT / "demo"
# The committed demo is indented so reviewers can read diffs of it.
DEMO_INDENT = 2


def _date(text: str) -> dt.date:
    try:
        if len(text) != 10:
            raise ValueError
        return dt.date.fromisoformat(text)
    except ValueError:
        raise argparse.ArgumentTypeError(f"{text!r} is not a YYYY-MM-DD date") from None


def _add_run_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--firms", type=Path, action="append", required=True, metavar="CSV",
                   help="FIRMS VIIRS CSV for the analysis window (repeat for several satellites/files)")
    p.add_argument("--boundary", type=Path, required=True, metavar="GEOJSON",
                   help="authoritative Punjab state boundary, WGS84 GeoJSON")
    p.add_argument("--districts", type=Path, metavar="GEOJSON",
                   help="authoritative Punjab district boundaries, WGS84 GeoJSON")
    p.add_argument("--district-name-field", default="district", metavar="FIELD",
                   help="district name property in --districts (default: district)")
    p.add_argument("--analysis-date", type=_date, required=True, metavar="YYYY-MM-DD",
                   help="last day (UTC acq_date) of the analysis window")
    p.add_argument("--window-days", type=int, default=7, help="window length in days, ending on --analysis-date (default 7)")
    p.add_argument("--cell-size-m", type=int, default=5000, help="grid cell size in metres (default 5000)")
    p.add_argument("--history-firms", type=Path, action="append", default=[], metavar="CSV",
                   help="optional historical FIRMS VIIRS CSV; only dates before the window are used")
    p.add_argument("--cell-evidence", type=Path, metavar="CSV", help="optional per-cell evidence CSV keyed by cell_id")
    p.add_argument("--config", type=Path, metavar="JSON", help="scoring config (default: built-in)")
    p.add_argument("--synthetic", action="store_true", help="label the output as synthetic demonstration data")
    p.add_argument("--allow-missing-districts", action="store_true",
                   help="write district='UNAVAILABLE' instead of failing (output will NOT conform to the contract)")
    p.add_argument("--repair-geometry", action="store_true", help="repair invalid boundary geometry with make_valid")
    p.add_argument("--strict", action="store_true", help="fail if any FIRMS row is rejected")
    p.add_argument("--output-dir", type=Path, required=True, help="directory for output files")


def _report(result: PipelineResult, paths: dict[str, Path]) -> None:
    m = result.metadata
    label = "SYNTHETIC DEMONSTRATION DATA - NOT REAL SATELLITE EVIDENCE" if m["synthetic"] else m["data_provenance"]
    w = m["analysis_window"]
    d = m["detections"]
    print(f"[{label}]")
    print(f"Analysis window : {w['start_date']} .. {w['end_date']} ({w['days']} days, UTC acq_date)")
    print(f"Grid cells      : {m['grid']['cell_count']} x {m['grid']['cell_size_m']} m ({m['grid']['projected_crs']})")
    print(f"Detections      : {d['in_window']} in window, {d['assigned_to_cells']} assigned, "
          f"{d['outside_region']} outside region, {d['rejected_rows']} rows rejected")
    print("Risk levels     : " + ", ".join(f"{k}={v}" for k, v in m["risk_level_counts"].items()))
    for warning in m["warnings"]:
        print(f"WARNING: {warning}")
    for dev in m["contract_deviations"]:
        print(f"CONTRACT DEVIATION: {dev}")
    print("Contract check  : PASSED (docs/DATA_CONTRACT.md v" + m["contract_version"] + ")")
    for name, path in paths.items():
        if path.exists():
            print(f"  {name:<13}{path}")


def _cmd_run(args) -> int:
    inputs = PipelineInputs(
        firms_paths=args.firms,
        boundary_path=args.boundary,
        analysis_date=args.analysis_date,
        window_days=args.window_days,
        cell_size_m=args.cell_size_m,
        districts_path=args.districts,
        district_name_field=args.district_name_field,
        history_paths=args.history_firms,
        cell_evidence_path=args.cell_evidence,
        config_path=args.config,
        declare_synthetic=args.synthetic,
        allow_missing_districts=args.allow_missing_districts,
        repair_geometry=args.repair_geometry,
        strict=args.strict,
    )
    result = run_pipeline(inputs)
    _report(result, write_outputs(result, args.output_dir))
    return 0


def demo_inputs() -> PipelineInputs:
    """Fixed inputs for the deterministic demo grid committed under demo/.

    No historical file is used, so cells with zero detections and no cropland
    value show up as risk_level "unknown", and all four levels appear.
    """
    if not FIXTURES.is_dir():
        raise PipelineError(f"synthetic fixtures not found at {FIXTURES}")
    return PipelineInputs(
        firms_paths=[FIXTURES / "synthetic_firms_viirs_window.csv"],
        boundary_path=FIXTURES / "synthetic_state_boundary.geojson",
        districts_path=FIXTURES / "synthetic_districts.geojson",
        district_name_field="district",
        cell_evidence_path=FIXTURES / "synthetic_cell_evidence.csv",
        analysis_date=dt.date(2026, 10, 26),
        window_days=7,
        cell_size_m=5000,
        declare_synthetic=True,
        deterministic=True,
    )


def _cmd_demo(args) -> int:
    result = run_pipeline(demo_inputs())
    if args.check:
        reference = REFERENCE_DEMO / "risk_grid.geojson"
        if not reference.is_file():
            raise PipelineError(f"reference demo not found at {reference}; run `agni-pipeline demo --output-dir demo`")
        if reference.read_bytes() != serialize_geojson(result.collection, DEMO_INDENT).encode("utf-8"):
            raise PipelineError(
                f"{reference} is out of date with the pipeline; regenerate it with `agni-pipeline demo --output-dir demo`"
            )
        print(f"{reference}: matches a fresh deterministic run and conforms to docs/DATA_CONTRACT.md")
        return 0
    _report(result, write_outputs(result, args.output_dir, DEMO_INDENT))
    return 0


def _cmd_validate(args) -> int:
    try:
        data = json.loads(args.geojson.read_text(encoding="utf-8-sig"))
    except (OSError, json.JSONDecodeError) as exc:
        raise PipelineError(f"cannot read {args.geojson}: {exc}") from None
    errors = validate_feature_collection(
        data,
        require_metadata=not args.no_require_metadata,
        allow_unavailable_district=args.allow_unavailable_district,
        check_envelope=not args.no_envelope_check,
    )
    if errors:
        raise ContractViolationError(errors)
    print(f"{args.geojson}: conforms to docs/DATA_CONTRACT.md ({len(data['features'])} features)")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agni-pipeline",
        description="AGNI-SCAN geospatial pipeline: FIRMS VIIRS detections -> verification-priority grid GeoJSON.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="process supplied FIRMS and boundary files")
    _add_run_args(run)
    run.set_defaults(func=_cmd_run)

    demo = sub.add_parser("demo", help="deterministic run on the bundled SYNTHETIC fixtures (not real data)")
    demo.add_argument("--output-dir", type=Path, default=Path("output") / "demo")
    demo.add_argument("--check", action="store_true",
                      help="verify the committed demo/risk_grid.geojson equals a fresh run, byte for byte")
    demo.set_defaults(func=_cmd_demo)

    val = sub.add_parser("validate", help="check a GeoJSON file against docs/DATA_CONTRACT.md")
    val.add_argument("geojson", type=Path)
    val.add_argument("--allow-unavailable-district", action="store_true")
    val.add_argument("--no-require-metadata", action="store_true",
                     help="do not require the provenance metadata member (for third-party files)")
    val.add_argument("--no-envelope-check", action="store_true", help="skip the Punjab coordinate-envelope check")
    val.set_defaults(func=_cmd_validate)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return args.func(args)
    except PipelineError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
