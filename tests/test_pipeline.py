"""Offline tests: run with `pytest` from the project folder."""
import json
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "python"))

import config  # noqa: E402
import db  # noqa: E402
import kiwis  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures"


def load(name):
    return json.loads((FIXTURES / name).read_text())


def test_parse_station_list_flattens_reference_levels():
    df = kiwis.parse_station_list(load("station_list.json"))
    assert len(df) == 3
    upper = df.set_index("station_no").loc["10001"]
    assert upper["sepa_median_annual_minimum_level"] == 0.30
    assert upper["sepa_median_annual_maximum_level"] == 1.90
    # station with an empty ca_sta list still parses, with missing levels
    assert pd.isna(df.set_index("station_no").loc["10003", "sepa_median_annual_maximum_level"])


def test_bbox_filter_drops_stations_outside_cairngorms():
    df = kiwis.filter_to_bbox(kiwis.parse_station_list(load("station_list.json")), config.BBOX)
    assert set(df["station_no"]) == {"10001", "10002"}


def test_parse_values_converts_timezones_to_utc():
    df = kiwis.parse_values(load("values.json"))
    assert list(df["timestamp_utc"]) == [
        "2026-10-26 09:00:00",
        "2026-10-26 09:15:00",   # 10:15 BST -> 09:15 UTC
        "2026-10-26 12:00:00",
    ]
    assert pd.isna(df["level"].iloc[2])


def test_parse_values_handles_empty_response():
    assert kiwis.parse_values([]).empty
    assert kiwis.parse_values([{"ts_id": "1", "data": []}]).empty


def _db_with_station(tmp_path):
    con = db.connect(tmp_path / "test.sqlite")
    stations = kiwis.filter_to_bbox(kiwis.parse_station_list(load("station_list.json")), config.BBOX)
    db.upsert_stations(con, stations)
    return con


def test_reruns_do_not_duplicate_readings(tmp_path):
    con = _db_with_station(tmp_path)
    readings = kiwis.parse_values(load("values.json"))
    assert db.insert_readings(con, "10001", readings) == 3
    assert db.insert_readings(con, "10001", readings) == 0
    assert con.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 3


def test_upsert_updates_rather_than_duplicates(tmp_path):
    con = _db_with_station(tmp_path)
    stations = kiwis.filter_to_bbox(kiwis.parse_station_list(load("station_list.json")), config.BBOX)
    db.upsert_stations(con, stations)
    assert con.execute("SELECT COUNT(*) FROM stations").fetchone()[0] == 2


def test_latest_status_view_classifies_and_trends(tmp_path):
    con = _db_with_station(tmp_path)
    # Example Upper: median annual min 0.30, max 1.90 -> 'High' band is 1.10-1.90
    readings = pd.DataFrame({
        "timestamp_utc": ["2026-10-26 06:00:00", "2026-10-26 09:00:00"],
        "level": [1.00, 1.50],
        "quality_code": [50, 50],
    })
    db.insert_readings(con, "10001", readings)
    row = con.execute(
        "SELECT level, status, trend, change_3h, pct_typical_range FROM latest_status WHERE station_no = '10001'"
    ).fetchone()
    assert row == (1.5, "High", "Rising", 0.5, 75.0)


def test_single_reading_spikes_are_removed_but_real_rises_kept(tmp_path):
    con = _db_with_station(tmp_path)
    readings = pd.DataFrame({
        "timestamp_utc": [f"2026-10-09 {h}" for h in
                          ["15:00:00", "15:15:00", "15:30:00", "15:45:00", "16:00:00", "16:15:00", "16:30:00"]],
        # 0.00 at 15:30 is a sensor dropout; 0.50 -> 0.90 -> 1.30 is a real spate
        "level": [0.48, 0.47, 0.00, 0.50, 0.90, 1.30, 1.35],
        "quality_code": [50] * 7,
    })
    db.insert_readings(con, "10001", readings)
    clean = [r[0] for r in con.execute(
        "SELECT level FROM readings_clean WHERE station_no = '10001' ORDER BY timestamp_utc")]
    assert clean == [0.48, 0.47, 0.50, 0.90, 1.30, 1.35]
    # raw data is kept
    assert con.execute("SELECT COUNT(*) FROM readings").fetchone()[0] == 7


def test_remove_stations_deletes_station_and_readings(tmp_path):
    con = _db_with_station(tmp_path)
    db.insert_readings(con, "10002", kiwis.parse_values(load("values.json")))
    assert db.remove_stations(con, ["Example Spey"]) == 1
    assert con.execute("SELECT COUNT(*) FROM readings WHERE station_no = '10002'").fetchone()[0] == 0
    assert con.execute("SELECT COUNT(*) FROM stations").fetchone()[0] == 1
