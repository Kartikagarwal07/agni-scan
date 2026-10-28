import copy
import csv
import datetime as dt
import json

import pytest
from shapely.geometry import LinearRing

from agni_pipeline.cli import main
from agni_pipeline.contract import (
    PROVENANCE_OBSERVED,
    PROVENANCE_SYNTHETIC,
    OPTIONAL_PROPERTIES,
    REQUIRED_PROPERTIES,
    validate_feature_collection,
)
from agni_pipeline.errors import InputValidationError, PipelineError
from agni_pipeline.pipeline import PipelineInputs, run_pipeline, write_outputs

from conftest import nrt_row, polygon_fc, rect


def demo_inputs(fx, **overrides) -> PipelineInputs:
    kwargs = dict(
        firms_paths=[fx / "synthetic_firms_viirs_window.csv"],
        history_paths=[fx / "synthetic_firms_viirs_history.csv"],
        boundary_path=fx / "synthetic_state_boundary.geojson",
        districts_path=fx / "synthetic_districts.geojson",
        cell_evidence_path=fx / "synthetic_cell_evidence.csv",
        analysis_date=dt.date(2026, 10, 26),
        window_days=7,
        cell_size_m=5000,
    )
    kwargs.update(overrides)
    return PipelineInputs(**kwargs)


@pytest.fixture
def demo_result(fixtures_dir):
    return run_pipeline(demo_inputs(fixtures_dir))


# --- contract compliance of generated output -------------------------------------------------


def test_demo_output_conforms_to_contract(demo_result):
    fc = demo_result.collection
    assert validate_feature_collection(fc) == []
    assert fc["type"] == "FeatureCollection" and fc["features"]
    for f in fc["features"]:
        assert f["type"] == "Feature"
        ranked = f["properties"]["risk_score"] is not None
        assert tuple(f["properties"]) == REQUIRED_PROPERTIES + (OPTIONAL_PROPERTIES if ranked else ())
        assert f["id"] == f["properties"]["cell_id"]
        assert f["geometry"]["type"] == "Polygon"
        p = f["properties"]
        assert p["verification_status"] == "unverified"
        assert p["analysis_date"] == "2026-10-26"
        assert isinstance(p["observed_fire_count"], int) and p["observed_fire_count"] >= 0
        assert 0 <= p["evidence_completeness"] <= 1
        assert (p["risk_score"] is None) == (p["risk_level"] == "unknown")
        for ring in f["geometry"]["coordinates"]:
            assert ring[0] == ring[-1] and len(ring) >= 4
            for lon, lat in ring:  # [longitude, latitude] for this region
                assert 75.6 < lon < 76.1 and 30.7 < lat < 31.1
        assert LinearRing(f["geometry"]["coordinates"][0]).is_ccw  # RFC 7946 exterior winding


def test_demo_output_is_labelled_synthetic(demo_result):
    meta = demo_result.metadata
    assert meta["synthetic"] is True
    assert meta["data_provenance"] == PROVENANCE_SYNTHETIC
    assert "NOT real satellite observations" in meta["disclaimer"]
    assert "NOT a probability" in meta["interpretation"]
    assert "Zero detections do not prove zero burning" in meta["interpretation"]
    assert all(f["id"].startswith("SYNTH-PB-") for f in demo_result.collection["features"])


def test_demo_counts_and_bookkeeping(demo_result):
    meta = demo_result.metadata
    d = meta["detections"]
    feats = demo_result.collection["features"]
    assert sum(f["properties"]["observed_fire_count"] for f in feats) == d["assigned_to_cells"] == 9
    assert d["duplicates_removed"] == 1
    assert d["removed_by_quality_filters"] == {"confidence_below_nominal": 1}
    assert d["outside_analysis_window"] == 1
    assert d["outside_region"] == 1
    # history: 21 rows, 1 static-source type 2 removed, 1 inside the window excluded
    assert d["historical_used"] == 19
    assert d["historical_seasons"] == [2024, 2025]
    by_season = d["historical_assigned_by_season"]
    explained = demo_result.explanations
    assert sum(by_season.values()) == sum(e["historical_fire_count"] for e in explained)
    for e in explained:
        parts = dict(x.split(":") for x in e["historical_fire_count_by_season"].split(";"))
        assert list(parts) == ["2024", "2025"]
        assert sum(map(int, parts.values())) == e["historical_fire_count"]
        assert e["historical_seasons_with_fire"] == sum(1 for v in parts.values() if v != "0")
    counts = meta["risk_level_counts"]
    assert sum(counts.values()) == len(feats) == meta["grid"]["cell_count"]
    hot = next(f for f in feats if f["properties"]["observed_fire_count"] == 6)
    assert hot["properties"]["risk_level"] == "high"


def test_output_is_deterministic(fixtures_dir, demo_result):
    again = run_pipeline(demo_inputs(fixtures_dir))
    assert again.collection["features"] == demo_result.collection["features"]


def test_window_only_input_yields_unknown_for_zero_detection_cells(fixtures_dir):
    res = run_pipeline(demo_inputs(fixtures_dir, history_paths=[], cell_evidence_path=None))
    feats = res.collection["features"]
    for f in feats:
        p = f["properties"]
        if p["observed_fire_count"] == 0:
            assert p["risk_score"] is None and p["risk_level"] == "unknown"
        else:
            assert p["risk_score"] is not None
    assert validate_feature_collection(res.collection) == []


def test_history_with_no_rows_before_the_window_is_unavailable(fixtures_dir, write_firms):
    only_in_window = write_firms([nrt_row(30.0, 75.0, date="2026-10-24")], name="hist.csv")
    res = run_pipeline(demo_inputs(fixtures_dir, history_paths=[only_in_window], cell_evidence_path=None))
    assert res.metadata["detections"]["historical_seasons"] == []
    assert any("no rows before the analysis window" in w for w in res.metadata["warnings"])
    zero = [f["properties"] for f in res.collection["features"] if f["properties"]["observed_fire_count"] == 0]
    assert zero and all(p["risk_level"] == "unknown" for p in zero)


def test_history_in_the_window_year_is_flagged_as_partial_season(fixtures_dir, write_firms):
    earlier_this_year = write_firms([nrt_row(30.0, 75.0, date="2026-10-01")], name="hist.csv")
    res = run_pipeline(demo_inputs(fixtures_dir, history_paths=[earlier_this_year], cell_evidence_path=None))
    assert res.metadata["detections"]["historical_seasons"] == [2026]
    assert any("partial season" in w for w in res.metadata["warnings"])


def test_priority_rank_orders_by_score_then_cropland_among_fire_evidence(demo_result):
    rows = [r for r in demo_result.explanations if r["priority_rank"] is not None]
    rows.sort(key=lambda r: r["priority_rank"])
    assert [r["priority_rank"] for r in rows] == list(range(1, len(rows) + 1))
    assert all(r["risk_score"] is not None for r in rows)
    for a, b in zip(rows, rows[1:]):
        assert a["risk_score"] >= b["risk_score"]
        if a["risk_score"] == b["risk_score"] and b["tie_break_value"] is not None:
            assert a["tie_break_value"] is not None and a["tie_break_value"] >= b["tie_break_value"]
    for r in demo_result.explanations:
        has_fire = r["observed_fire_count"] > 0 or bool(r["historical_fire_count"])
        if not has_fire:
            assert r["tie_break_value"] is None
    unscored = [r for r in demo_result.explanations if r["risk_score"] is None]
    assert all(r["priority_rank"] is None for r in unscored)


def test_cropland_does_not_change_any_score(fixtures_dir):
    with_crop = run_pipeline(demo_inputs(fixtures_dir))
    without = run_pipeline(demo_inputs(fixtures_dir, cell_evidence_path=None))
    key = lambda res: [(f["properties"]["risk_score"], f["properties"]["risk_level"],  # noqa: E731
                        f["properties"]["evidence_completeness"]) for f in res.collection["features"]]
    assert key(with_crop) == key(without)


def test_synthetic_output_carries_no_data_credits(demo_result):
    assert demo_result.metadata["attribution"] == []


def test_attribution_credits_each_real_source(tmp_path):
    from agni_pipeline.pipeline import FIRMS_CREDIT, _attribution

    state = tmp_path / "state.geojson"
    state.write_text(json.dumps({"type": "FeatureCollection", "source": {"src_agency": ["Survey of India (SOI)"]},
                                 "features": []}), encoding="utf-8")
    districts = tmp_path / "districts.geojson"
    districts.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    evidence = tmp_path / "cropland.csv"
    evidence.write_text("cell_id,cropland_fraction\n", encoding="utf-8")
    (tmp_path / "cropland.csv.meta.json").write_text(json.dumps({
        "layer": "cropland_fraction", "attribution": "(c) ESA WorldCover project", "product": "ESA WorldCover 10 m 2021 v200",
        "licence": "CC BY 4.0", "source": "https://esa-worldcover.org"}), encoding="utf-8")
    inp = PipelineInputs(firms_paths=[], boundary_path=state, districts_path=districts, cell_evidence_path=evidence,
                         analysis_date=dt.date(2026, 10, 26))
    assert _attribution(inp, synthetic=False) == [
        FIRMS_CREDIT,
        "State and district boundaries: Survey of India (SOI)",
        "Cropland fraction: (c) ESA WorldCover project (ESA WorldCover 10 m 2021 v200, CC BY 4.0, https://esa-worldcover.org)",
    ]
    (tmp_path / "cropland.csv.meta.json").write_text("[]", encoding="utf-8")
    assert _attribution(inp, synthetic=False) == [FIRMS_CREDIT, "State and district boundaries: Survey of India (SOI)"]
    assert _attribution(inp, synthetic=True) == []


def test_write_outputs(tmp_path, demo_result):
    paths = write_outputs(demo_result, tmp_path / "out")
    fc = json.loads(paths["geojson"].read_text(encoding="utf-8"))
    assert validate_feature_collection(fc) == []
    with open(paths["explanations"], newline="") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == len(fc["features"])
    assert {"observed_detections_value", "cropland_fraction_value", "score_reason"} <= set(rows[0])
    with open(paths["assignments"], newline="") as fh:
        assert len(list(csv.DictReader(fh))) == demo_result.metadata["detections"]["in_window"]


# --- provenance, districts, strictness ---------------------------------------------------------


def _unlabelled_copy(fx, tmp_path):
    """Strip synthetic markers to simulate a real-data run (data is still synthetic, test only)."""
    rows = (fx / "synthetic_firms_viirs_window.csv").read_text().splitlines()
    firms = tmp_path / "firms.csv"
    firms.write_text("\n".join(r.rsplit(",", 1)[0] for r in rows) + "\n")
    out = {"firms": firms}
    for name in ("synthetic_state_boundary.geojson", "synthetic_districts.geojson"):
        data = json.loads((fx / name).read_text())
        data.pop("agni_scan_synthetic")
        for f in data["features"]:
            f["properties"].pop("synthetic")
        path = tmp_path / name.replace("synthetic_", "")
        path.write_text(json.dumps(data))
        out[name] = path
    return out


def test_unlabelled_inputs_are_marked_as_processed_observations(fixtures_dir, tmp_path):
    p = _unlabelled_copy(fixtures_dir, tmp_path)
    inputs = demo_inputs(fixtures_dir, firms_paths=[p["firms"]], history_paths=[], cell_evidence_path=None,
                         boundary_path=p["synthetic_state_boundary.geojson"],
                         districts_path=p["synthetic_districts.geojson"])
    res = run_pipeline(inputs)
    assert res.metadata["synthetic"] is False
    assert res.metadata["data_provenance"] == PROVENANCE_OBSERVED
    assert all(f["id"].startswith("PB-") for f in res.collection["features"])
    assert any("reference Punjab area" in w for w in res.metadata["warnings"])

    forced = run_pipeline(PipelineInputs(**{**inputs.__dict__, "declare_synthetic": True}))
    assert forced.metadata["data_provenance"] == PROVENANCE_SYNTHETIC


def test_any_synthetic_input_marks_output_synthetic(fixtures_dir, tmp_path):
    p = _unlabelled_copy(fixtures_dir, tmp_path)
    # Real-looking boundaries but a synthetic FIRMS file -> synthetic output.
    res = run_pipeline(demo_inputs(fixtures_dir, history_paths=[], cell_evidence_path=None,
                                   boundary_path=p["synthetic_state_boundary.geojson"],
                                   districts_path=p["synthetic_districts.geojson"]))
    assert res.metadata["synthetic"] is True


def test_districts_are_required_by_default(fixtures_dir):
    with pytest.raises(PipelineError, match="District boundaries are required"):
        run_pipeline(demo_inputs(fixtures_dir, districts_path=None))


def test_allow_missing_districts_is_flagged_as_contract_deviation(fixtures_dir):
    res = run_pipeline(demo_inputs(fixtures_dir, districts_path=None, allow_missing_districts=True))
    assert {f["properties"]["district"] for f in res.collection["features"]} == {"UNAVAILABLE"}
    assert res.metadata["contract_deviations"]
    # Strict contract validation still reports the deviation.
    assert any("UNAVAILABLE" in e for e in validate_feature_collection(res.collection))


def test_partial_district_coverage_fails(fixtures_dir, tmp_path):
    west = tmp_path / "west.geojson"
    west.write_text(json.dumps(polygon_fc(rect(75.65, 30.70, 75.80, 31.05), {"district": "W", "synthetic": True})))
    with pytest.raises(PipelineError, match="overlap no supplied district boundary"):
        run_pipeline(demo_inputs(fixtures_dir, districts_path=west))


def test_strict_mode_rejects_bad_rows(fixtures_dir, write_firms):
    bad = write_firms([nrt_row(30.80, 75.95, date="2026-10-24"), nrt_row("abc", 75.95)])
    res = run_pipeline(demo_inputs(fixtures_dir, firms_paths=[bad]))
    assert len(res.rejections) == 1 and res.metadata["detections"]["rejected_rows"] == 1
    with pytest.raises(InputValidationError, match="line 3: latitude 'abc'"):
        run_pipeline(demo_inputs(fixtures_dir, firms_paths=[bad], strict=True))


def test_missing_window_days_are_warned(fixtures_dir, write_firms):
    sparse = write_firms([nrt_row(30.80, 75.95, date="2026-10-26")])
    res = run_pipeline(demo_inputs(fixtures_dir, firms_paths=[sparse]))
    assert any("No FIRMS records at all for 6 day(s)" in w for w in res.metadata["warnings"])


def test_invalid_cell_evidence_value(fixtures_dir, write_text):
    bad = write_text("ev.csv", "cell_id,cropland_fraction\nX,1.5\n")
    with pytest.raises(InputValidationError, match=r"must be within \[0, 1\]"):
        run_pipeline(demo_inputs(fixtures_dir, cell_evidence_path=bad))


# --- the validator itself ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "mutate, message",
    [
        (lambda f: f.__setitem__("id", "OTHER"), "must equal properties.cell_id"),
        (lambda f: f["geometry"].__setitem__("type", "MultiPolygon"), "must be a Polygon"),
        (lambda f: f["geometry"]["coordinates"][0].pop(), "not closed"),
        (lambda f: f["geometry"].__setitem__("coordinates", [[[lat, lon] for lon, lat in f["geometry"]["coordinates"][0]]]),
         "longitude, latitude"),
        (lambda f: f["properties"].update(risk_score=0, risk_level="unknown"), "inconsistent"),
        (lambda f: f["properties"].update(risk_score=120, risk_level="high"), "0-100"),
        (lambda f: f["properties"].update(risk_level="severe"), "risk_level 'severe'"),
        (lambda f: f["properties"].update(observed_fire_count=True), "integer"),
        (lambda f: f["properties"].update(observed_fire_count=-1), "integer"),
        (lambda f: f["properties"].update(evidence_completeness=1.5), "0-1"),
        (lambda f: f["properties"].update(verification_status="done"), "verification_status"),
        (lambda f: f["properties"].update(analysis_date="2026-02-30"), "YYYY-MM-DD"),
        (lambda f: f["properties"].update(extra=1), "not in the contract"),
        (lambda f: f["properties"].pop("district"), "missing properties"),
        (lambda f: f["properties"].update(district=""), "district must be"),
    ],
)
def test_validator_detects_violations(demo_result, mutate, message):
    fc = copy.deepcopy(demo_result.collection)
    mutate(fc["features"][0])
    errors = validate_feature_collection(fc)
    assert any(message in e for e in errors), errors


def _ranked(fc):
    return sorted((f for f in fc["features"] if "priority_rank" in f["properties"]),
                  key=lambda f: f["properties"]["priority_rank"])


@pytest.mark.parametrize(
    "rank, message",
    [(0, "positive integer"), (-3, "positive integer"), (1.5, "positive integer"), (True, "positive integer"),
     ("1", "positive integer"), (None, "positive integer")],
)
def test_validator_checks_priority_rank_type(demo_result, rank, message):
    fc = copy.deepcopy(demo_result.collection)
    _ranked(fc)[0]["properties"]["priority_rank"] = rank
    assert any(message in e for e in validate_feature_collection(fc))


def test_validator_checks_priority_rank_consistency(demo_result):
    fc = copy.deepcopy(demo_result.collection)
    first, second = _ranked(fc)[:2]
    assert first["properties"]["risk_score"] > second["properties"]["risk_score"]
    second["properties"]["priority_rank"] = 1
    assert any("duplicate priority_rank" in e for e in validate_feature_collection(fc))

    fc = copy.deepcopy(demo_result.collection)
    first, second = _ranked(fc)[:2]
    first["properties"]["priority_rank"], second["properties"]["priority_rank"] = 2, 1
    assert any("ranks must follow risk_score" in e for e in validate_feature_collection(fc))

    fc = copy.deepcopy(demo_result.collection)
    _ranked(fc)[-1]["properties"].update(risk_score=None, risk_level="unknown")
    assert any("without a risk_score" in e for e in validate_feature_collection(fc))

    fc = copy.deepcopy(demo_result.collection)
    for f in fc["features"]:
        f["properties"].pop("priority_rank", None)
    assert validate_feature_collection(fc) == []  # the field is optional


def test_geojson_priority_rank_matches_explanations_and_leaves_scores_alone(demo_result):
    by_id = {r["cell_id"]: r for r in demo_result.explanations}
    for f in demo_result.collection["features"]:
        p, row = f["properties"], by_id[f["id"]]
        assert p.get("priority_rank") == row["priority_rank"]
        assert (p["risk_score"], p["risk_level"], p["evidence_completeness"]) == (
            row["risk_score"], row["risk_level"], row["evidence_completeness"])
    ranks = [f["properties"]["priority_rank"] for f in _ranked(demo_result.collection)]
    assert ranks == list(range(1, len(ranks) + 1))


def test_validator_metadata_rules(demo_result):
    fc = copy.deepcopy(demo_result.collection)
    fc["features"].append(copy.deepcopy(fc["features"][0]))
    assert any("duplicate cell_id" in e for e in validate_feature_collection(fc))

    fc = copy.deepcopy(demo_result.collection)
    del fc["metadata"]
    assert any("rule 7" in e for e in validate_feature_collection(fc))
    assert validate_feature_collection(fc, require_metadata=False) == []

    fc = copy.deepcopy(demo_result.collection)
    fc["features"][0]["id"] = fc["features"][0]["properties"]["cell_id"] = "PB-1"
    assert any("must start with 'SYNTH-'" in e for e in validate_feature_collection(fc))


def test_contract_example_validates_without_metadata():
    example = {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature", "id": "PB-001",
            "geometry": {"type": "Polygon", "coordinates": [[[75.80, 30.90], [75.81, 30.90], [75.81, 30.91],
                                                             [75.80, 30.91], [75.80, 30.90]]]},
            "properties": {"cell_id": "PB-001", "district": "Ludhiana", "risk_score": 82, "risk_level": "high",
                           "observed_fire_count": 0, "evidence_completeness": 0.75,
                           "verification_status": "unverified", "analysis_date": "2026-10-26"},
        }],
    }
    assert validate_feature_collection(example, require_metadata=False) == []


# --- CLI ---------------------------------------------------------------------------------------


def test_cli_demo_and_validate(tmp_path, capsys):
    assert main(["demo", "--output-dir", str(tmp_path)]) == 0
    out = capsys.readouterr().out
    assert "SYNTHETIC DEMONSTRATION DATA - NOT REAL SATELLITE EVIDENCE" in out
    assert "Contract check  : PASSED" in out
    assert main(["validate", str(tmp_path / "risk_grid.geojson")]) == 0


def test_cli_run_reports_errors(fixtures_dir, tmp_path, write_firms, capsys):
    bad = write_firms(["30.8,2026-10-24"], header="latitude,acq_date")
    code = main(["run", "--firms", str(bad), "--boundary", str(fixtures_dir / "synthetic_state_boundary.geojson"),
                 "--districts", str(fixtures_dir / "synthetic_districts.geojson"),
                 "--analysis-date", "2026-10-26", "--output-dir", str(tmp_path / "o")])
    assert code == 1
    assert "missing required column(s) longitude" in capsys.readouterr().err


def test_cli_run_success(fixtures_dir, tmp_path, capsys):
    code = main(["run", "--firms", str(fixtures_dir / "synthetic_firms_viirs_window.csv"),
                 "--boundary", str(fixtures_dir / "synthetic_state_boundary.geojson"),
                 "--districts", str(fixtures_dir / "synthetic_districts.geojson"),
                 "--analysis-date", "2026-10-26", "--window-days", "7", "--cell-size-m", "2000",
                 "--output-dir", str(tmp_path / "o")])
    assert code == 0
    fc = json.loads((tmp_path / "o" / "risk_grid.geojson").read_text(encoding="utf-8"))
    assert fc["metadata"]["grid"]["cell_size_m"] == 2000
    assert validate_feature_collection(fc) == []


def test_cli_rejects_bad_date(capsys):
    with pytest.raises(SystemExit):
        main(["run", "--firms", "x.csv", "--boundary", "b.geojson", "--analysis-date", "26-10-2026",
              "--output-dir", "o"])
    assert "not a YYYY-MM-DD date" in capsys.readouterr().err


def test_cli_validate_reports_violations(tmp_path, capsys):
    path = tmp_path / "bad.geojson"
    path.write_text(json.dumps({"type": "FeatureCollection", "features": [{"type": "Feature"}]}))
    assert main(["validate", str(path)]) == 1
    assert "violates DATA_CONTRACT.md" in capsys.readouterr().err


# --- deterministic reference demo (demo/risk_grid.geojson) -------------------------------------


def test_committed_reference_demo_is_current_and_valid():
    from agni_pipeline.cli import DEMO_INDENT, REFERENCE_DEMO, demo_inputs
    from agni_pipeline.contract import serialize_geojson

    reference = REFERENCE_DEMO / "risk_grid.geojson"
    fresh = serialize_geojson(run_pipeline(demo_inputs()).collection, DEMO_INDENT)
    assert reference.read_bytes() == fresh.encode("utf-8"), "run `agni-pipeline demo --output-dir demo`"
    fc = json.loads(fresh)
    assert validate_feature_collection(fc) == []
    assert fc["metadata"]["deterministic"] is True and fc["metadata"]["generated_at"] is None
    assert fc["metadata"]["synthetic"] is True
    levels = {f["properties"]["risk_level"] for f in fc["features"]}
    assert levels == {"low", "medium", "high", "unknown"}


def test_non_deterministic_runs_record_a_timestamp(demo_result):
    assert demo_result.metadata["deterministic"] is False
    assert demo_result.metadata["generated_at"].endswith("Z")


def test_demo_check_detects_stale_reference(tmp_path, monkeypatch, capsys):
    import agni_pipeline.cli as cli

    monkeypatch.setattr(cli, "REFERENCE_DEMO", tmp_path)
    assert main(["demo", "--check"]) == 1
    assert "reference demo not found" in capsys.readouterr().err
    assert main(["demo", "--output-dir", str(tmp_path)]) == 0
    assert main(["demo", "--check"]) == 0
    (tmp_path / "risk_grid.geojson").write_text("{}\n")
    assert main(["demo", "--check"]) == 1
    assert "out of date" in capsys.readouterr().err
