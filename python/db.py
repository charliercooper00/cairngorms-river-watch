"""SQLite helpers: create the schema, upsert stations, insert readings."""
from __future__ import annotations

import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pandas as pd

import config


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def connect(db_path: Path = config.DB_PATH) -> sqlite3.Connection:
    db_path = Path(db_path)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(db_path)
    con.execute("PRAGMA foreign_keys = ON")
    con.executescript(config.SCHEMA_PATH.read_text())
    return con


def upsert_stations(con: sqlite3.Connection, stations: pd.DataFrame) -> int:
    """Insert new stations or update existing ones (matched on station_no)."""
    now = utc_now()
    rows = [
        (
            str(r.station_no), r.station_name, r.catchment_name,
            r.station_latitude, r.station_longitude, str(r.ts_id), r.ts_path, r.ts_unitsymbol,
            _num(r.sepa_median_annual_minimum_level), _num(r.sepa_median_annual_maximum_level),
            _num(r.sepa_maximum_level), r.sepa_maximum_level_timestamp, now,
        )
        for r in stations.itertuples(index=False)
    ]
    con.executemany(
        """
        INSERT INTO stations (station_no, station_name, catchment_name, latitude, longitude,
                              ts_id, ts_path, unit, median_annual_min, median_annual_max,
                              record_max, record_max_time, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(station_no) DO UPDATE SET
            station_name      = excluded.station_name,
            catchment_name    = excluded.catchment_name,
            latitude          = excluded.latitude,
            longitude         = excluded.longitude,
            ts_id             = excluded.ts_id,
            ts_path           = excluded.ts_path,
            unit              = excluded.unit,
            median_annual_min = excluded.median_annual_min,
            median_annual_max = excluded.median_annual_max,
            record_max        = excluded.record_max,
            record_max_time   = excluded.record_max_time,
            updated_at        = excluded.updated_at
        """,
        rows,
    )
    con.commit()
    return len(rows)


def remove_stations(con: sqlite3.Connection, names: list[str]) -> int:
    """Delete stations (and their readings) by name. Returns stations removed."""
    if not names:
        return 0
    marks = ",".join("?" * len(names))
    con.execute(
        f"DELETE FROM readings WHERE station_no IN "
        f"(SELECT station_no FROM stations WHERE station_name IN ({marks}))", names)
    removed = con.execute(f"DELETE FROM stations WHERE station_name IN ({marks})", names).rowcount
    con.commit()
    return removed


def stations_need_refresh(con: sqlite3.Connection) -> bool:
    oldest = con.execute("SELECT MIN(updated_at) FROM stations").fetchone()[0]
    if oldest is None:
        return True
    age = datetime.now(timezone.utc) - datetime.strptime(oldest, "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
    return age.days >= config.STATION_REFRESH_DAYS


def list_stations(con: sqlite3.Connection) -> pd.DataFrame:
    return pd.read_sql_query("SELECT station_no, station_name, ts_id FROM stations ORDER BY station_name", con)


def latest_timestamp(con: sqlite3.Connection, station_no: str) -> str | None:
    return con.execute(
        "SELECT MAX(timestamp_utc) FROM readings WHERE station_no = ?", (station_no,)
    ).fetchone()[0]


def insert_readings(con: sqlite3.Connection, station_no: str, readings: pd.DataFrame) -> int:
    """Insert readings, silently skipping any we already have. Returns rows added."""
    before = con.total_changes
    con.executemany(
        "INSERT OR IGNORE INTO readings (station_no, timestamp_utc, level, quality_code) VALUES (?, ?, ?, ?)",
        [
            (station_no, r.timestamp_utc, _num(r.level), None if pd.isna(r.quality_code) else int(r.quality_code))
            for r in readings.itertuples(index=False)
        ],
    )
    con.commit()
    return con.total_changes - before


def log_run(con: sqlite3.Connection, stations: int, rows: int, status: str, message: str = "") -> None:
    con.execute(
        "INSERT INTO fetch_log (run_at, stations, rows_inserted, status, message) VALUES (?, ?, ?, ?, ?)",
        (utc_now(), stations, rows, status, message[:1000]),
    )
    con.commit()


def _num(x):
    return None if x is None or pd.isna(x) else float(x)
