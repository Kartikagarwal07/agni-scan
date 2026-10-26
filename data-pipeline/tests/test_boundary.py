import pytest

from agni_pipeline.boundary import load_districts, load_region
from agni_pipeline.errors import BoundaryError

from conftest import polygon_fc, rect


def test_loads_synthetic_boundary(fixtures_dir):
    region = load_region(fixtures_dir / "synthetic_state_boundary.geojson")
    assert region.synthetic is True
    assert region.geometry_wgs84.is_valid
    assert 700 < region.area_km2 < 800
    assert region.warnings == []  # area plausibility warning is skipped for synthetic input
    assert len(region.sha256) == 64


@pytest.mark.parametrize("name", ["urn:ogc:def:crs:OGC:1.3:CRS84", "EPSG:4326", "urn:ogc:def:crs:EPSG::4326"])
def test_wgs84_crs_member_accepted(write_geojson, name):
    data = polygon_fc(rect(75.8, 30.8, 75.9, 30.9), crs={"type": "name", "properties": {"name": name}})
    load_region(write_geojson("b.geojson", data))


def test_projected_crs_member_rejected(write_geojson):
    data = polygon_fc(rect(75.8, 30.8, 75.9, 30.9), crs={"type": "name", "properties": {"name": "EPSG:32643"}})
    with pytest.raises(BoundaryError, match="only WGS84"):
        load_region(write_geojson("b.geojson", data))


def test_projected_coordinates_rejected(write_geojson):
    data = polygon_fc([[[400000, 3400000], [405000, 3400000], [405000, 3405000], [400000, 3400000]]])
    with pytest.raises(BoundaryError, match="projected CRS"):
        load_region(write_geojson("b.geojson", data))


def test_swapped_lat_lon_detected(write_geojson):
    swapped = [[[lat, lon] for lon, lat in rect(75.8, 30.8, 75.9, 30.9)[0]]]
    with pytest.raises(BoundaryError, match=r"\[latitude, longitude\]"):
        load_region(write_geojson("b.geojson", polygon_fc(swapped)))


def test_boundary_outside_punjab_rejected(write_geojson):
    with pytest.raises(BoundaryError, match="outside the expected Punjab envelope"):
        load_region(write_geojson("b.geojson", polygon_fc(rect(77.1, 28.5, 77.3, 28.7))))  # Delhi area


def test_invalid_geometry_rejected_or_repaired(write_geojson):
    bowtie = [[[75.8, 30.8], [75.9, 30.9], [75.9, 30.8], [75.8, 30.9], [75.8, 30.8]]]
    path = write_geojson("b.geojson", polygon_fc(bowtie))
    with pytest.raises(BoundaryError, match="invalid geometry.*Self-intersection"):
        load_region(path)
    repaired = load_region(path, repair=True)
    assert repaired.geometry_wgs84.is_valid and repaired.geometry_wgs84.area > 0


def test_non_polygon_geometry_rejected(write_geojson):
    data = {"type": "Feature", "properties": {}, "geometry": {"type": "Point", "coordinates": [75.8, 30.8]}}
    with pytest.raises(BoundaryError, match="not Polygon/MultiPolygon"):
        load_region(write_geojson("b.geojson", data))


def test_not_json(write_text):
    with pytest.raises(BoundaryError, match="not valid JSON"):
        load_region(write_text("b.geojson", "{oops"))


def test_area_warning_for_unlabelled_small_boundary(write_geojson):
    region = load_region(write_geojson("b.geojson", polygon_fc(rect(75.8, 30.8, 75.9, 30.9))))
    assert region.synthetic is False
    assert any("differs from the reference Punjab area" in w for w in region.warnings)


def test_multiple_features_are_dissolved(write_geojson):
    data = polygon_fc(rect(75.8, 30.8, 75.9, 30.9))
    data["features"].append({"type": "Feature", "properties": {},
                             "geometry": {"type": "Polygon", "coordinates": rect(75.9, 30.8, 76.0, 30.9)}})
    region = load_region(write_geojson("b.geojson", data))
    assert region.geometry_wgs84.geom_type == "Polygon"


def test_districts_load_and_validate(fixtures_dir, write_geojson):
    region = load_region(fixtures_dir / "synthetic_state_boundary.geojson")
    ds = load_districts(fixtures_dir / "synthetic_districts.geojson", "district", region)
    assert [d.name for d in ds.districts] == ["SYNTHETIC-DISTRICT-EAST", "SYNTHETIC-DISTRICT-WEST"]
    assert ds.synthetic and ds.warnings == []

    with pytest.raises(BoundaryError, match="property 'DISTRICT' not found"):
        load_districts(fixtures_dir / "synthetic_districts.geojson", "DISTRICT", region)

    partial = write_geojson("d.geojson", polygon_fc(rect(75.65, 30.70, 75.85, 31.05), {"district": "West"}))
    assert "cover only" in load_districts(partial, "district", region).warnings[0]

    blank = write_geojson("d2.geojson", polygon_fc(rect(75.65, 30.70, 75.85, 31.05), {"district": " "}))
    with pytest.raises(BoundaryError, match="empty or not a string"):
        load_districts(blank, "district", region)
