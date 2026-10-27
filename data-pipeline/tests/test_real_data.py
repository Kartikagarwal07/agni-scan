"""Real-data tooling: FIRMS fetch, boundary preparation, detection funnel. All offline."""

import datetime as dt
import json
import zipfile

import pytest
from pyproj import Transformer

from agni_pipeline.boundary import load_districts, load_region
from agni_pipeline.cli import main
from agni_pipeline.errors import PipelineError
from agni_pipeline.firms_fetch import NRT_SOURCES, BBox, date_range, fetch_firms, read_map_key, request_url
from agni_pipeline.pipeline import PipelineInputs, run_pipeline
from agni_pipeline.prepare_boundaries import prepare_boundary
from agni_pipeline.reconcile import STAGES

from conftest import NRT_HEADER, nrt_row

KEY = "0123456789abcdef0123456789abcdef"
NOW = dt.datetime(2026, 10, 27, 6, 0, tzinfo=dt.timezone.utc)


def fake_opener(responses):
    """Returns (status, body) per source and records requested URLs."""
    calls = []

    def opener(url, timeout):
        calls.append(url)
        source = url.split("/")[7]
        return responses[source]

    opener.calls = calls
    return opener


# --- FIRMS fetch ---------------------------------------------------------------------------------


def test_request_urls_and_date_ranges_follow_the_area_api():
    bbox = BBox(73.82, 29.49, 76.99, 32.57)
    assert request_url(KEY, "VIIRS_SNPP_NRT", bbox, 5, None).endswith(f"/{KEY}/VIIRS_SNPP_NRT/73.82,29.49,76.99,32.57/5")
    assert request_url(KEY, "VIIRS_SNPP_NRT", bbox, 4, dt.date(2026, 10, 23)).endswith("/4/2026-10-23")
    # Without DATE the range ends today; with DATE it starts on DATE.
    assert date_range(5, None, dt.date(2026, 10, 27)) == (dt.date(2026, 10, 23), dt.date(2026, 10, 27))
    assert date_range(4, dt.date(2026, 10, 23), dt.date(2026, 10, 27)) == (dt.date(2026, 10, 23), dt.date(2026, 10, 26))


def test_bbox_around_pads_and_rounds_outward():
    # Punjab's real bounds -> the bbox used for the 2026-10-27 fetch.
    assert BBox.around((73.8797, 29.5421, 76.9391, 32.5129)) == BBox(73.82, 29.49, 76.99, 32.57)
    # A padded edge already on the 0.01 degree grid stays where it is.
    assert BBox.around((74.0, 30.0, 76.0, 32.0)) == BBox(73.95, 29.95, 76.05, 32.05)
    with pytest.raises(PipelineError, match="invalid bounding box"):
        BBox(77, 29, 73, 32)
    with pytest.raises(PipelineError, match="four numbers"):
        BBox.parse("73,29,77")


def test_fetch_writes_csvs_and_a_manifest_without_the_key(tmp_path):
    body = (NRT_HEADER + "\n" + nrt_row(30.8, 75.9) + "\n" + nrt_row(30.81, 75.91)).encode()  # no trailing newline, like FIRMS
    opener = fake_opener({s: (200, body) for s in NRT_SOURCES})
    files, manifest = fetch_firms(out_dir=tmp_path, bbox=BBox(73.82, 29.49, 76.99, 32.57), day_range=4,
                                  start_date=dt.date(2026, 10, 23), map_key=KEY, opener=opener, now=NOW)
    assert [f.source for f in files] == list(NRT_SOURCES)
    assert all(f.rows == 2 for f in files), "row count must not depend on a trailing newline"
    assert len(opener.calls) == 3 and all(KEY in u for u in opener.calls)
    text = (tmp_path / "manifest.json").read_text()
    assert KEY not in text, "the MAP_KEY must never be written to disk"
    saved = json.loads(text)
    assert saved["acq_date_range"] == ["2026-10-23", "2026-10-26"]
    assert saved["files"][0]["request"].startswith("https://firms.modaps.eosdis.nasa.gov/api/area/csv/<MAP_KEY>/")
    assert len(saved["files"][0]["sha256"]) == 64
    assert (tmp_path / "VIIRS_SNPP_NRT.csv").read_bytes() == body


@pytest.mark.parametrize(
    "status, body, message",
    [
        (400, b"Invalid MAP_KEY.", "HTTP 400: Invalid MAP_KEY."),
        (400, b"Invalid source.", "HTTP 400: Invalid source."),
        (200, b"<html>maintenance</html>", "HTTP 200: <html>maintenance</html>"),
        (500, b"", "HTTP 500: empty response"),
        (400, f"Key {KEY} is disabled".encode(), "HTTP 400: Key <MAP_KEY> is disabled"),
    ],
)
def test_fetch_reports_firms_errors_without_leaking_the_key(tmp_path, status, body, message):
    opener = fake_opener({s: (status, body) for s in NRT_SOURCES})
    with pytest.raises(PipelineError) as exc:
        fetch_firms(out_dir=tmp_path, bbox=BBox(73, 29, 77, 33), day_range=1, map_key=KEY, opener=opener, now=NOW)
    assert message in str(exc.value)
    assert KEY not in str(exc.value)


def test_fetch_validates_arguments(tmp_path):
    with pytest.raises(PipelineError, match="day range must be 1-5"):
        fetch_firms(out_dir=tmp_path, bbox=BBox(73, 29, 77, 33), day_range=9, map_key=KEY, opener=fake_opener({}))
    with pytest.raises(PipelineError, match="unknown FIRMS source"):
        fetch_firms(out_dir=tmp_path, bbox=BBox(73, 29, 77, 33), day_range=1, sources=("MODIS_NRT",), map_key=KEY,
                    opener=fake_opener({}))


def test_map_key_from_environment_or_env_file(tmp_path, monkeypatch):
    monkeypatch.delenv("FIRMS_MAP_KEY", raising=False)
    env = tmp_path / ".env.local"
    env.write_text(f"# comment\nDATABASE_URL=\nFIRMS_MAP_KEY=\"{KEY}\"\n")
    assert read_map_key(env) == KEY
    monkeypatch.setenv("FIRMS_MAP_KEY", "ffffffffffffffffffffffffffffffff")
    assert read_map_key(env) == "ffffffffffffffffffffffffffffffff", "the environment wins over the file"
    monkeypatch.delenv("FIRMS_MAP_KEY")
    with pytest.raises(PipelineError, match="FIRMS_MAP_KEY is not set"):
        read_map_key(tmp_path / "missing.env")
    env.write_text("FIRMS_MAP_KEY=not a key!\n")
    with pytest.raises(PipelineError, match="does not look like"):
        read_map_key(env)


# --- boundary preparation -------------------------------------------------------------------------

_TO_7755 = Transformer.from_crs("EPSG:4326", "EPSG:7755", always_xy=True)


def _projected_rect(lon0, lat0, lon1, lat1):
    ring = [(lon0, lat0), (lon1, lat0), (lon1, lat1), (lon0, lat1), (lon0, lat0)]
    return [[[list(_TO_7755.transform(x, y)) for x, y in ring]]]


def _soi_like(features):
    """A small all-India-style file in EPSG:7755, shaped like the Survey of India / NWIC downloads."""
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": "urn:ogc:def:crs:EPSG::7755"}},
        "features": [
            {"type": "Feature", "properties": props, "geometry": {"type": "MultiPolygon", "coordinates": coords}}
            for props, coords in features
        ],
    }


@pytest.fixture
def soi_files(tmp_path):
    states = _soi_like([
        ({"state_name": "Punjab", "stcode": "03", "src_agency": "Survey of India (SOI)"}, _projected_rect(75.70, 30.70, 76.10, 31.10)),
        ({"state_name": "Haryana", "stcode": "06", "src_agency": "Survey of India (SOI)"}, _projected_rect(76.20, 29.50, 76.60, 30.00)),
    ])
    districts = _soi_like([
        ({"state_name": "Punjab", "stcode": "03", "district": "West", "src_agency": "Survey of India (SOI)"}, _projected_rect(75.70, 30.70, 75.90, 31.10)),
        ({"state_name": "Punjab", "stcode": "03", "district": "East", "src_agency": "Survey of India (SOI)"}, _projected_rect(75.90, 30.70, 76.10, 31.10)),
        ({"state_name": "Haryana", "stcode": "06", "district": "Other", "src_agency": "Survey of India (SOI)"}, _projected_rect(76.20, 29.50, 76.60, 30.00)),
    ])
    paths = {}
    for name, data in (("state", states), ("district", districts)):
        geo = tmp_path / f"{name}_NWIC.GeoJSON"
        geo.write_text(json.dumps(data))
        archive = tmp_path / f"{name}_nwic_geojson.zip"
        with zipfile.ZipFile(archive, "w") as zf:
            zf.write(geo, geo.name)
        paths[name] = archive
    return paths


def test_prepare_extracts_one_state_and_reprojects_to_wgs84(tmp_path, soi_files):
    out = tmp_path / "out" / "state.geojson"
    prepared = prepare_boundary(soi_files["state"], out, field="stcode", value="03")
    assert prepared.features == 1 and prepared.source_crs == "EPSG:7755"
    data = json.loads(out.read_text(encoding="utf-8"))
    assert "crs" not in data, "RFC 7946 output has no crs member"
    assert data["source"]["src_agency"] == ["Survey of India (SOI)"]
    assert data["source"]["file"] == "state_nwic_geojson.zip!state_NWIC.GeoJSON"
    lon, lat = data["features"][0]["geometry"]["coordinates"][0][0][0]
    assert lon == pytest.approx(75.70, abs=1e-6) and lat == pytest.approx(30.70, abs=1e-6)
    region = load_region(out)  # the pipeline's own validator accepts it
    assert region.geometry_wgs84.bounds == pytest.approx((75.70, 30.70, 76.10, 31.10), abs=1e-6)


def test_prepared_districts_cover_the_prepared_state(tmp_path, soi_files):
    state = prepare_boundary(soi_files["state"], tmp_path / "s.geojson", field="stcode", value="03").path
    districts = prepare_boundary(soi_files["district"], tmp_path / "d.geojson", field="stcode", value="03", label_field="district")
    assert districts.values == ["East", "West"]
    loaded = load_districts(districts.path, "district", load_region(state))
    assert loaded.warnings == [] and len(loaded.districts) == 2


def test_prepare_rejects_bad_inputs(tmp_path, soi_files):
    from agni_pipeline.errors import BoundaryError

    with pytest.raises(BoundaryError, match="no feature has stcode == '99'"):
        prepare_boundary(soi_files["state"], tmp_path / "x.geojson", field="stcode", value="99")
    two = tmp_path / "two.zip"
    with zipfile.ZipFile(two, "w") as zf:
        zf.writestr("a.geojson", "{}")
        zf.writestr("b.geojson", "{}")
    with pytest.raises(BoundaryError, match="exactly one .geojson"):
        prepare_boundary(two, tmp_path / "x.geojson", field="stcode", value="03")
    odd = tmp_path / "odd.geojson"
    odd.write_text(json.dumps({"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": "local grid"}}, "features": []}))
    with pytest.raises(BoundaryError, match="unsupported crs"):
        prepare_boundary(odd, tmp_path / "x.geojson", field="stcode", value="03")


def test_cli_prepare_boundaries_warns_about_missing_districts(tmp_path, soi_files, capsys):
    state = tmp_path / "s.geojson"
    assert main(["prepare-boundaries", str(soi_files["state"]), "--output", str(state), "--kind", "state", "--value", "03"]) == 0
    assert main(["prepare-boundaries", str(soi_files["district"]), "--output", str(tmp_path / "d.geojson"), "--kind", "districts",
                 "--value", "03", "--expect-count", "3", "--state", str(state)]) == 0
    out = capsys.readouterr().out
    assert "reprojected EPSG:7755 -> EPSG:4326" in out
    assert "expected 3 districts, found 2" in out


# --- detection funnel -----------------------------------------------------------------------------


def test_funnel_accounts_for_every_row(fixtures_dir, write_firms):
    rows = [
        nrt_row(30.80, 75.95, date="2026-10-24"),             # assigned
        nrt_row(30.80, 75.95, date="2026-10-24"),             # duplicate of the row above
        nrt_row(30.85, 75.95, date="2026-10-24", conf="l"),   # low confidence
        nrt_row(30.80, 75.95, date="2026-09-01"),             # outside the window
        nrt_row(30.80, 75.40, date="2026-10-24"),             # outside the region
        nrt_row("abc", 75.95),                                # rejected (invalid)
    ]
    path = write_firms(rows)
    result = run_pipeline(PipelineInputs(
        firms_paths=[path], boundary_path=fixtures_dir / "synthetic_state_boundary.geojson",
        districts_path=fixtures_dir / "synthetic_districts.geojson", analysis_date=dt.date(2026, 10, 26), window_days=7,
    ))
    (row, total) = result.funnel
    expected = {"rows_read": 6, "rejected_invalid": 1, "valid": 5, "duplicates": 1, "removed_low_confidence": 1,
                "outside_window": 1, "outside_region": 1, "assigned": 1}
    for stage in STAGES:
        assert row.counts.get(stage, 0) == expected.get(stage, 0), stage
    assert total.source_file == "TOTAL" and total.counts == row.counts


def test_funnel_matches_metadata_on_the_demo_inputs():
    from agni_pipeline.cli import demo_inputs

    result = run_pipeline(demo_inputs())
    total = result.funnel[-1].counts
    d = result.metadata["detections"]
    assert total["assigned"] == d["assigned_to_cells"]
    assert total["outside_region"] == d["outside_region"]
    assert total["duplicates"] == d["duplicates_removed"]
    assert total["removed_low_confidence"] == d["removed_by_quality_filters"].get("confidence_below_nominal", 0)
    assert total["outside_window"] == d["outside_analysis_window"]
