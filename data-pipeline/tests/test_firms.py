import datetime as dt
import re

import pytest

from agni_pipeline.errors import InputValidationError
from agni_pipeline.firms import apply_quality_filters, deduplicate, load_firms_csv

from conftest import NRT_HEADER, nrt_row


def test_loads_synthetic_nrt_fixture(fixtures_dir):
    res = load_firms_csv(fixtures_dir / "synthetic_firms_viirs_window.csv")
    assert res.synthetic is True
    assert res.total_rows == 13
    assert res.rejections == []
    assert len(res.detections) == 13
    first = res.detections[0]
    assert (first.latitude, first.longitude) == (30.8012, 75.9503)
    assert first.acq_date == dt.date(2026, 10, 21)
    assert first.confidence == "nominal"
    # acq_time "56" (leading zeros dropped) is normalised to HHMM.
    assert any(d.acq_time == "0056" for d in res.detections)


def test_loads_uppercase_archive_variant_with_type(fixtures_dir):
    res = load_firms_csv(fixtures_dir / "synthetic_firms_viirs_history.csv")
    assert res.rejections == []
    assert {d.fire_type for d in res.detections} == {0, 2}
    assert res.synthetic is True


def test_unlabelled_file_is_not_synthetic(write_firms):
    res = load_firms_csv(write_firms([nrt_row(30.8, 75.9)]))
    assert res.synthetic is False


def test_bom_and_whitespace_in_header(write_text):
    path = write_text("bom.csv", "﻿ Latitude , LONGITUDE ,acq_date\n30.8,75.9,2026-10-24\n")
    res = load_firms_csv(path)
    assert len(res.detections) == 1 and res.rejections == []


def test_missing_required_column_is_a_structural_error(write_firms):
    path = write_firms(["30.8,330.0,2026-10-24"], header="latitude,bright_ti4,acq_date")
    with pytest.raises(InputValidationError, match="missing required column.*longitude"):
        load_firms_csv(path)


def test_duplicate_header_after_case_folding(write_firms):
    with pytest.raises(InputValidationError, match="duplicate column"):
        load_firms_csv(write_firms(["30.8,30.8,75.9,2026-10-24"], header="latitude,LATITUDE,longitude,acq_date"))


def test_empty_file(write_text):
    with pytest.raises(InputValidationError, match="empty"):
        load_firms_csv(write_text("empty.csv", ""))


def test_missing_file(tmp_path):
    with pytest.raises(InputValidationError, match="not found"):
        load_firms_csv(tmp_path / "nope.csv")


@pytest.mark.parametrize(
    "row, message",
    [
        (nrt_row("abc", 75.9), "latitude 'abc' is not a number"),
        (nrt_row(95.0, 75.9), r"latitude 95.0 outside \[-90, 90\]"),
        (nrt_row(30.8, 200.0), r"longitude 200.0 outside \[-180, 180\]"),
        (nrt_row(30.8, "nan"), "not finite"),
        (nrt_row("", 75.9), "required field 'latitude' is empty"),
        (nrt_row(30.8, 75.9, date="2026-13-01"), "not a valid calendar date"),
        (nrt_row(30.8, 75.9, date="26/10/2026"), "not YYYY-MM-DD"),
        (nrt_row(30.8, 75.9, date=""), "required field 'acq_date' is empty"),
        (nrt_row(30.8, 75.9, time="2460"), "not a valid UTC time"),
        (nrt_row(30.8, 75.9, time="8:12"), "not HHMM"),
        (nrt_row(30.8, 75.9, conf="85"), "MODIS convention"),
        (nrt_row(30.8, 75.9, conf="x"), "not one of l, n, h"),
        (nrt_row(30.8, 75.9, instrument="MODIS"), "not VIIRS"),
        (nrt_row(30.8, 75.9, frp="-1"), "frp -1.0 is negative"),
        ("30.8,75.9,2026-10-24", "has 3 fields, header has 14"),
    ],
)
def test_invalid_rows_are_rejected_with_reason(write_firms, row, message):
    good = nrt_row(30.81, 75.91)
    res = load_firms_csv(write_firms([good, row]))
    assert len(res.detections) == 1
    assert len(res.rejections) == 1
    rej = res.rejections[0]
    assert rej.row == 3  # 1-based file line (header is line 1)
    assert re.search(message, rej.reason), rej.reason


def test_invalid_type_value(write_firms):
    res = load_firms_csv(write_firms(["30.8,75.9,2026-10-24,7"], header="latitude,longitude,acq_date,type"))
    assert "type '7'" in res.rejections[0].reason


def test_spelled_out_confidence_accepted(write_firms):
    res = load_firms_csv(write_firms([nrt_row(30.8, 75.9, conf="High"), nrt_row(30.8, 75.91, conf="low")]))
    assert [d.confidence for d in res.detections] == ["high", "low"]


def test_blank_lines_are_skipped(write_text):
    res = load_firms_csv(write_text("b.csv", "latitude,longitude,acq_date\n\n30.8,75.9,2026-10-24\n,,\n"))
    assert res.total_rows == 1 and len(res.detections) == 1


def test_deduplicate_drops_repeated_pixels(write_firms):
    res = load_firms_csv(write_firms([nrt_row(30.8, 75.9), nrt_row(30.8, 75.9), nrt_row(30.8, 75.9, sat="1")]))
    unique, removed = deduplicate(res.detections)
    assert removed == 1
    assert len(unique) == 2


def test_quality_filters(write_text):
    path = write_text(
        "q.csv",
        "latitude,longitude,acq_date,confidence,type\n"
        "30.8,75.90,2026-10-24,l,0\n"
        "30.8,75.91,2026-10-24,n,0\n"
        "30.8,75.92,2026-10-24,h,2\n"
        "30.8,75.93,2026-10-24,,0\n"
        "30.8,75.94,2026-10-24,h,\n",
    )
    dets = load_firms_csv(path).detections
    res = apply_quality_filters(dets, min_confidence="nominal", exclude_fire_types=[1, 2, 3])
    assert [d.longitude for d in res.kept] == [75.91, 75.94]
    assert res.removed == {
        "confidence_below_nominal": 1,
        "type_2_other_static_land_source": 1,
        "confidence_missing": 1,
    }
    no_filter = apply_quality_filters(dets, min_confidence=None, exclude_fire_types=[])
    assert len(no_filter.kept) == 5


def test_header_constant_matches_fixture(fixtures_dir):
    header = (fixtures_dir / "synthetic_firms_viirs_window.csv").read_text().splitlines()[0]
    assert header.startswith(NRT_HEADER)
