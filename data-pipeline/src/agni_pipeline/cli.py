"""Command-line interface: ``agni-pipeline run | demo | validate | fetch-firms | prepare-boundaries | prepare-cropland``."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

from .boundary import load_districts, load_region
from .contract import serialize_geojson, validate_feature_collection
from .cropland import VERSIONS, prepare_cropland
from .errors import ContractViolationError, PipelineError
from .firms_fetch import DEFAULT_ENV_FILE, MAX_DAY_RANGE, NRT_SOURCES, VALID_SOURCES, BBox, fetch_firms, read_map_key
from .grid import GridSpec, generate_grid
from .pipeline import PipelineInputs, PipelineResult, run_pipeline, write_outputs
from .prepare_boundaries import prepare_boundary
from .reconcile import format_funnel

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
    if result.funnel:
        print("Detection funnel (window files; every row is accounted for):")
        for line in format_funnel(result.funnel).splitlines():
            print(f"  {line}")
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


def _cmd_fetch_firms(args) -> int:
    if args.bbox:
        bbox = BBox.parse(args.bbox)
    elif args.boundary:
        bbox = BBox.around(load_region(args.boundary).geometry_wgs84.bounds)
    else:
        raise PipelineError("give --boundary (bbox is derived from it) or an explicit --bbox west,south,east,north")
    sources = tuple(args.source) if args.source else NRT_SOURCES
    files, manifest = fetch_firms(
        out_dir=args.output_dir,
        bbox=bbox,
        day_range=args.days,
        start_date=args.start_date,
        sources=sources,
        map_key=read_map_key(args.env_file),
    )
    first, last = manifest["acq_date_range"]
    print(f"FIRMS {', '.join(sources)} | bbox {bbox.as_param()} | acq_date {first} .. {last} (UTC)")
    for f in files:
        print(f"  {f.source:<18}{f.rows:>6} rows  {f.path}")
    print(f"  manifest          {args.output_dir / 'manifest.json'}")
    print(f"Next: agni-pipeline run ... --analysis-date {last} --window-days {args.days}")
    print("Data from NASA FIRMS; credit FIRMS wherever results are shown.")
    return 0


def _cmd_prepare_boundaries(args) -> int:
    prepared = prepare_boundary(
        args.input, args.output, field=args.field, value=args.value, label_field=args.label_field
    )
    print(f"{prepared.path}: {prepared.features} feature(s) where {args.field} == {args.value!r}, "
          f"reprojected {prepared.source_crs} -> EPSG:4326")
    if args.kind == "state":
        region = load_region(prepared.path)
        print(f"  area {region.area_km2:,.0f} km2")
        for warning in region.warnings:
            print(f"WARNING: {warning}")
    else:
        print(f"  {len(prepared.values)} {args.label_field} value(s): {', '.join(prepared.values)}")
        if args.expect_count is not None and len(prepared.values) != args.expect_count:
            print(f"WARNING: expected {args.expect_count} districts, found {len(prepared.values)}; the source may "
                  "predate a boundary change. Areas of missing districts are counted under their parent district.")
        if args.state:
            for warning in load_districts(prepared.path, args.label_field, load_region(args.state)).warnings:
                print(f"WARNING: {warning}")
    return 0


def _cmd_prepare_cropland(args) -> int:
    region = load_region(args.boundary)
    # Same boundary and cell size as `run`, so the cell_id values match the risk grid.
    grid = generate_grid(region, GridSpec(args.cell_size_m, id_prefix="SYNTH-PB" if region.synthetic else "PB"))
    if args.grid:
        ids = {f["properties"]["cell_id"] for f in json.loads(args.grid.read_text(encoding="utf-8"))["features"]}
        mine = {c.cell_id for c in grid.cells}
        if ids != mine:
            raise PipelineError(f"{args.grid.name}: cell_id values differ from this grid ({len(ids - mine)} only in "
                                f"the risk grid, {len(mine - ids)} only here); check --boundary and --cell-size-m")
    prepared = prepare_cropland(region=region, grid=grid, output=args.output, tiles_dir=args.tiles_dir,
                                version=args.version, download=not args.no_download)
    values = sorted(c.fraction for c in prepared.cover if c.fraction is not None)
    print(f"ESA WorldCover {VERSIONS[args.version]} {args.version}, class 40 (general cropland, not paddy-specific)")
    print(f"  tiles     {', '.join(p.name for p in prepared.tiles)}")
    print(f"  cells     {len(values)} of {len(prepared.cover)} with a value"
          + (f"; cell_id values match {args.grid.name}" if args.grid else ""))
    if values:
        mid = len(values) // 2
        median = values[mid] if len(values) % 2 else (values[mid - 1] + values[mid]) / 2
        print(f"  fraction  min {values[0]:.4f}  median {median:.4f}  mean {sum(values) / len(values):.4f}  "
              f"max {values[-1]:.4f}")
    print(f"  csv       {prepared.csv_path}")
    print(f"  metadata  {prepared.metadata_path}")
    print("Use with: agni-pipeline run ... --cell-evidence " + str(prepared.csv_path))
    print("ESA WorldCover is CC BY 4.0; credit it wherever results are shown.")
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

    fetch = sub.add_parser("fetch-firms", help="download VIIRS detections from the NASA FIRMS Area API")
    fetch.add_argument("--output-dir", type=Path, required=True, help="folder for <SOURCE>.csv files and manifest.json")
    fetch.add_argument("--boundary", type=Path, metavar="GEOJSON", help="WGS84 state boundary; the request bbox is derived from it")
    fetch.add_argument("--bbox", metavar="W,S,E,N", help="explicit bounding box instead of --boundary")
    fetch.add_argument("--days", type=int, default=MAX_DAY_RANGE, help=f"day range 1-{MAX_DAY_RANGE} (default {MAX_DAY_RANGE})")
    fetch.add_argument("--start-date", type=_date, metavar="YYYY-MM-DD",
                       help="first UTC day to fetch; without it the range ends today")
    fetch.add_argument("--source", action="append", choices=VALID_SOURCES,
                       help="FIRMS source (repeatable; default: the three VIIRS NRT sources)")
    fetch.add_argument("--env-file", type=Path, default=DEFAULT_ENV_FILE,
                       help="file holding FIRMS_MAP_KEY=... if the variable is not set (default: repo .env.local)")
    fetch.set_defaults(func=_cmd_fetch_firms)

    prep = sub.add_parser("prepare-boundaries", help="extract and reproject an authoritative boundary file to WGS84")
    prep.add_argument("input", type=Path, help="boundary GeoJSON, or a .zip containing exactly one")
    prep.add_argument("--output", type=Path, required=True, help="WGS84 GeoJSON to write")
    prep.add_argument("--kind", choices=("state", "districts"), required=True)
    prep.add_argument("--field", default="stcode", help="property to filter on (default: stcode)")
    prep.add_argument("--value", required=True, help='value to keep, e.g. "03" for Punjab in Survey of India files')
    prep.add_argument("--label-field", default="district", help="district name property (default: district)")
    prep.add_argument("--expect-count", type=int, help="warn if the number of districts differs")
    prep.add_argument("--state", type=Path, metavar="GEOJSON", help="prepared state boundary, to check district coverage")
    prep.set_defaults(func=_cmd_prepare_boundaries)
    crop = sub.add_parser("prepare-cropland",
                          help="per-cell cropland fraction (ESA WorldCover class 40) for --cell-evidence")
    crop.add_argument("--boundary", type=Path, required=True, metavar="GEOJSON",
                      help="the state boundary used for `run` (WGS84)")
    crop.add_argument("--cell-size-m", type=int, default=5000, help="grid cell size used for `run` (default 5000)")
    crop.add_argument("--output", type=Path, required=True, metavar="CSV", help="cell_id,cropland_fraction CSV to write")
    crop.add_argument("--tiles-dir", type=Path, default=Path("data") / "landcover" / "worldcover",
                      help="tile store; tiles go in <dir>/<version>/ (default data/landcover/worldcover)")
    crop.add_argument("--version", choices=sorted(VERSIONS), default="v200",
                      help="WorldCover release: v200 = 2021 (default), v100 = 2020")
    crop.add_argument("--grid", type=Path, metavar="GEOJSON",
                      help="risk_grid.geojson whose cell_id values must match exactly")
    crop.add_argument("--no-download", action="store_true", help="fail instead of downloading missing tiles")
    crop.set_defaults(func=_cmd_prepare_cropland)

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
