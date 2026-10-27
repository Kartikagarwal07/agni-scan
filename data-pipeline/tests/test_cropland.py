"""Cropland-fraction layer from ESA WorldCover tiles, using small synthetic rasters (no network)."""

import json

import pytest

rasterio = pytest.importorskip("rasterio")
import numpy as np  # noqa: E402
from rasterio.features import geometry_mask  # noqa: E402
from rasterio.transform import from_origin  # noqa: E402

from agni_pipeline.boundary import load_region  # noqa: E402
from agni_pipeline.cli import main  # noqa: E402
from agni_pipeline.cropland import (  # noqa: E402
    CROPLAND_CLASS,
    cropland_cover,
    ensure_tiles,
    prepare_cropland,
    tile_filename,
    tile_url,
    tiles_for_bounds,
)
from agni_pipeline.errors import PipelineError  # noqa: E402
from agni_pipeline.evidence import load_cell_evidence  # noqa: E402
from agni_pipeline.grid import GridSpec, generate_grid  # noqa: E402

from conftest import polygon_fc, rect  # noqa: E402

RES = 0.0005  # degrees; coarser than 10 m but the arithmetic is the same


def _tile(path, west=75.0, north=30.1, width=400, height=200):
    """Class 40 west of 75.05 E, class 10 east of it, no data (0) north of 30.06 N."""
    lon = west + (np.arange(width) + 0.5) * RES
    lat = north - (np.arange(height) + 0.5) * RES
    data = np.where(lon[None, :] < 75.05, CROPLAND_CLASS, 10).astype("uint8").repeat(height, axis=0)
    data[lat > 30.06, :] = 0
    path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(path, "w", driver="GTiff", width=width, height=height, count=1, dtype="uint8",
                       crs="EPSG:4326", transform=from_origin(west, north, RES, RES), nodata=0) as dst:
        dst.write(data, 1)
    return path


@pytest.fixture
def region(write_geojson):
    return load_region(write_geojson("state.geojson", polygon_fc(rect(75.0, 30.0, 75.1, 30.09))))


@pytest.fixture
def tiles_dir(tmp_path):
    _tile(tmp_path / "tiles" / "v200" / tile_filename("N30E075", "v200"))
    return tmp_path / "tiles"


def test_tile_names_and_urls():
    assert tiles_for_bounds((73.88, 29.54, 76.94, 32.51)) == ["N27E072", "N27E075", "N30E072", "N30E075"]
    assert tiles_for_bounds((-1.5, -2.0, 1.0, 1.0)) == ["S03W003", "S03E000", "N00W003", "N00E000"]
    assert tile_url("N30E075", "v200") == (
        "https://esa-worldcover.s3.eu-central-1.amazonaws.com/v200/2021/map/ESA_WorldCover_10m_2021_v200_N30E075_Map.tif"
    )


def test_fractions_follow_the_raster_and_are_in_range(region, tiles_dir):
    grid = generate_grid(region, GridSpec(1000))
    cover = cropland_cover(grid, [tiles_dir / "v200" / tile_filename("N30E075", "v200")])
    assert [c.cell_id for c in cover] == [c.cell_id for c in grid.cells]
    known = [c.fraction for c in cover if c.fraction is not None]
    assert known and all(0 <= f <= 1 for f in known)
    assert 1.0 in known and 0.0 in known  # all-cropland cells in the west, none in the east
    assert any(c.fraction is None for c in cover)  # cells entirely in the no-data strip are unavailable


def test_every_pixel_is_counted_once(region, tiles_dir):
    path = tiles_dir / "v200" / tile_filename("N30E075", "v200")
    cover = cropland_cover(generate_grid(region, GridSpec(1000)), [path])
    with rasterio.open(path) as src:
        data = src.read(1)
        inside = geometry_mask([region.geometry_wgs84], out_shape=data.shape, transform=src.transform, invert=True)
    assert sum(c.cropland_pixels for c in cover) == np.count_nonzero(inside & (data == CROPLAND_CLASS))
    assert sum(c.valid_pixels for c in cover) == np.count_nonzero(inside & (data != 0))


def test_prepare_writes_csv_and_provenance(tmp_path, region, tiles_dir):
    grid = generate_grid(region, GridSpec(1000))
    out = tmp_path / "cropland.csv"
    prepared = prepare_cropland(region=region, grid=grid, output=out, tiles_dir=tiles_dir, download=False)
    lines = out.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "cell_id,cropland_fraction" and len(lines) == len(grid.cells) + 1
    table = load_cell_evidence(out, ["cropland_fraction"])
    assert set(table.values) == {c.cell_id for c in grid.cells}
    assert sum(v["cropland_fraction"] is None for v in table.values.values()) == sum(
        c.fraction is None for c in prepared.cover)
    meta = json.loads(prepared.metadata_path.read_text(encoding="utf-8"))
    assert meta["class_used"] == {"value": 40, "name": "Cropland"}
    assert meta["licence"] == "CC BY 4.0" and meta["product_year"] == 2021
    assert "not paddy" in meta["label"].lower()
    assert meta["tiles"][0]["sha256"] and meta["output_sha256"]


def test_tiles_are_downloaded_only_when_missing(tmp_path):
    calls = []

    def fake(url, dest):
        calls.append(url)
        dest.write_bytes(b"tif")

    paths = ensure_tiles(["N30E075"], tmp_path, "v200", downloader=fake)
    assert paths[0].read_bytes() == b"tif" and len(calls) == 1
    ensure_tiles(["N30E075"], tmp_path, "v200", downloader=fake)
    assert len(calls) == 1
    with pytest.raises(PipelineError, match="tile missing"):
        ensure_tiles(["N27E075"], tmp_path, "v200", download=False)

    def broken(url, dest):
        dest.write_bytes(b"partial")
        raise OSError("connection reset")

    with pytest.raises(PipelineError, match="could not download"):
        ensure_tiles(["N27E072"], tmp_path, "v200", downloader=broken)
    assert not list((tmp_path / "v200").glob("*.part"))


def test_cli_checks_cell_ids_against_the_risk_grid(tmp_path, write_geojson, tiles_dir, capsys):
    state = write_geojson("state.geojson", polygon_fc(rect(75.0, 30.0, 75.1, 30.09)))
    region = load_region(state)
    ids = [c.cell_id for c in generate_grid(region, GridSpec(1000)).cells]
    grid = write_geojson("grid.geojson", {"features": [{"properties": {"cell_id": i}} for i in ids]})
    out = tmp_path / "cropland.csv"
    args = ["prepare-cropland", "--boundary", str(state), "--cell-size-m", "1000", "--output", str(out),
            "--tiles-dir", str(tiles_dir), "--no-download"]
    assert main(args + ["--grid", str(grid)]) == 0
    printed = capsys.readouterr().out
    assert "match grid.geojson" in printed and "not paddy-specific" in printed

    wrong = write_geojson("other.geojson", {"features": [{"properties": {"cell_id": i}} for i in ids[1:]]})
    assert main(args + ["--grid", str(wrong)]) != 0
    assert "cell_id values differ" in capsys.readouterr().err
