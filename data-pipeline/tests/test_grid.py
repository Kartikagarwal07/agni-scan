import datetime as dt
import random

import pytest
import shapely
from pyproj import Transformer

from agni_pipeline.boundary import load_districts, load_region, project_points
from agni_pipeline.firms import Detection
from agni_pipeline.grid import GridSpec, assign_detections, assign_districts, generate_grid

from conftest import polygon_fc, rect

_to_wgs = Transformer.from_crs("EPSG:32643", "EPSG:4326", always_xy=True)


def det(lat, lon, row=2):
    return Detection("t.csv", row, lat, lon, dt.date(2026, 10, 24), "0812", "nominal", "N", "VIIRS", 5.0, 0)


def lonlat(x, y):
    return _to_wgs.transform(x, y)


@pytest.fixture
def synthetic_region(fixtures_dir):
    return load_region(fixtures_dir / "synthetic_state_boundary.geojson")


def test_index_is_half_open():
    spec = GridSpec(5000)
    assert spec.index_of(10000.0, 20000.0) == (4, 2)
    assert spec.index_of(9999.999, 19999.999) == (3, 1)
    assert spec.cell_id(4, 2) == "PB-5000M-N00004-E00002"
    assert spec.cell_id(4, 2, part=2) == "PB-5000M-N00004-E00002-P2"


@pytest.mark.parametrize("size", [50, 60000, 5000.5])
def test_invalid_cell_size(size):
    with pytest.raises(ValueError):
        GridSpec(size)


def test_cells_are_clipped_and_tile_the_region(synthetic_region):
    grid = generate_grid(synthetic_region, GridSpec(5000))
    area = synthetic_region.geometry_projected
    ids = [c.cell_id for c in grid.cells]
    assert len(ids) == len(set(ids))
    for c in grid.cells:
        assert c.geometry_projected.geom_type == "Polygon"
        assert c.geometry_projected.difference(area).area < 1e-3
        assert c.geometry_projected.area <= 5000 * 5000 + 1e-6
    total = sum(c.geometry_projected.area for c in grid.cells)
    assert total == pytest.approx(area.area, rel=1e-9)
    # No two cells overlap (shared edges only).
    union = shapely.union_all([c.geometry_projected for c in grid.cells])
    assert union.area == pytest.approx(total, rel=1e-9)


def test_split_cells_get_part_suffixes(synthetic_region):
    grid = generate_grid(synthetic_region, GridSpec(5000))
    parts = [c.cell_id for c in grid.cells if c.part is not None]
    assert parts, "the fixture notch should split at least one square into two parts"
    assert all(p.endswith(("-P1", "-P2")) for p in parts)


def test_cell_ids_do_not_depend_on_boundary_extent(write_geojson):
    small = load_region(write_geojson("s.geojson", polygon_fc(rect(75.80, 30.80, 75.95, 30.95))))
    large = load_region(write_geojson("l.geojson", polygon_fc(rect(75.60, 30.60, 76.20, 31.20))))
    spec = GridSpec(5000)
    g_small = {c.cell_id: c for c in generate_grid(small, spec).cells}
    g_large = {c.cell_id: c for c in generate_grid(large, spec).cells}
    interior = [cid for cid, c in g_small.items() if c.geometry_projected.area == pytest.approx(25e6)]
    assert interior
    for cid in interior:
        assert cid in g_large
        assert g_large[cid].geometry_projected.equals(g_small[cid].geometry_projected)


def test_point_on_shared_edge_counted_once(write_geojson):
    region = load_region(write_geojson("r.geojson", polygon_fc(rect(75.70, 30.70, 76.10, 31.10))))
    grid = generate_grid(region, GridSpec(5000))
    cell = next(c for c in grid.cells if c.geometry_projected.area == pytest.approx(25e6))
    minx, miny, maxx, maxy = cell.geometry_projected.bounds
    detections = [
        det(*reversed(lonlat(maxx, (miny + maxy) / 2))),  # shared vertical edge
        det(*reversed(lonlat((minx + maxx) / 2, maxy))),  # shared horizontal edge
        det(*reversed(lonlat(maxx, maxy))),  # shared corner of four cells
    ]
    result = assign_detections(detections, grid, region)
    assert sum(result.counts.values()) == 3
    assert all(a.status == "assigned" for a in result.assignments)


def test_points_inside_outside_and_on_region_boundary(synthetic_region):
    grid = generate_grid(synthetic_region, GridSpec(5000))
    detections = [
        det(30.80, 75.95, row=2),  # inside
        det(30.80, 75.50, row=3),  # outside (west of region)
        det(30.75, 75.70, row=4),  # exactly on a boundary vertex
        det(30.81, 75.8625, row=5),  # inside the notch, i.e. outside the region
    ]
    result = assign_detections(detections, grid, synthetic_region)
    status = [a.status for a in result.assignments]
    assert status == ["assigned", "outside_region", "assigned", "outside_region"]
    assert sum(result.counts.values()) == 2


def test_detections_are_conserved(synthetic_region):
    grid = generate_grid(synthetic_region, GridSpec(1000))
    rng = random.Random(42)
    detections = [det(rng.uniform(30.74, 31.03), rng.uniform(75.69, 76.03), row=i) for i in range(500)]
    result = assign_detections(detections, grid, synthetic_region)
    st = result.status_counts
    assert sum(result.counts.values()) == st["assigned"]
    assert st["assigned"] + st["outside_region"] + st["in_dropped_sliver"] == 500
    # Each assigned point really lies in (or on the edge of) its cell.
    cells = {c.cell_id: c for c in grid.cells}
    for a in result.assignments:
        if a.cell_id:
            x, y = project_points([a.detection.longitude], [a.detection.latitude])
            assert cells[a.cell_id].geometry_projected.buffer(1e-6).covers(shapely.Point(x[0], y[0]))


def test_districts_by_largest_overlap(fixtures_dir, synthetic_region):
    grid = generate_grid(synthetic_region, GridSpec(5000))
    ds = load_districts(fixtures_dir / "synthetic_districts.geojson", "district", synthetic_region)
    assert assign_districts(grid, ds) == 0
    for c in grid.cells:
        assert c.district in ("SYNTHETIC-DISTRICT-WEST", "SYNTHETIC-DISTRICT-EAST")
        assert 0.5 <= c.district_overlap <= 1.0 + 1e-9
    west = next(d for d in ds.districts if d.name.endswith("WEST")).geometry_projected
    for c in grid.cells:
        share = c.geometry_projected.intersection(west).area / c.geometry_projected.area
        expected = "SYNTHETIC-DISTRICT-WEST" if share > 0.5 else "SYNTHETIC-DISTRICT-EAST"
        if abs(share - 0.5) > 1e-6:
            assert c.district == expected


def test_cells_outside_all_districts_stay_unassigned(fixtures_dir, synthetic_region, write_geojson):
    grid = generate_grid(synthetic_region, GridSpec(5000))
    west_only = write_geojson("w.geojson", polygon_fc(rect(75.65, 30.70, 75.80, 31.05), {"district": "W"}))
    ds = load_districts(west_only, "district", synthetic_region)
    missing = assign_districts(grid, ds)
    assert missing > 0
    assert sum(c.district is None for c in grid.cells) == missing
