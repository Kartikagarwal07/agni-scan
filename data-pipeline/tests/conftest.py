"""Shared helpers. Every file these helpers write is SYNTHETIC test data."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures" / "synthetic"

NRT_HEADER = (
    "latitude,longitude,bright_ti4,scan,track,acq_date,acq_time,satellite,instrument,"
    "confidence,version,bright_ti5,frp,daynight"
)


def nrt_row(lat, lon, date="2026-10-24", time="0812", conf="n", sat="N", instrument="VIIRS", frp="5.0"):
    return f"{lat},{lon},330.0,0.39,0.36,{date},{time},{sat},{instrument},{conf},2.0NRT,295.0,{frp},D"


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def write_text(tmp_path):
    def _write(name: str, text: str) -> Path:
        path = tmp_path / name
        path.write_text(text, encoding="utf-8")
        return path

    return _write


@pytest.fixture
def write_firms(write_text):
    def _write(rows: list[str], name="firms.csv", header: str = NRT_HEADER) -> Path:
        return write_text(name, "\n".join([header, *rows]) + "\n")

    return _write


@pytest.fixture
def write_geojson(tmp_path):
    def _write(name: str, data: dict) -> Path:
        path = tmp_path / name
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    return _write


def polygon_fc(rings, properties=None, **extra) -> dict:
    return {
        "type": "FeatureCollection",
        **extra,
        "features": [
            {"type": "Feature", "properties": properties or {}, "geometry": {"type": "Polygon", "coordinates": rings}}
        ],
    }


def rect(lon0, lat0, lon1, lat1):
    return [[[lon0, lat0], [lon1, lat0], [lon1, lat1], [lon0, lat1], [lon0, lat0]]]
