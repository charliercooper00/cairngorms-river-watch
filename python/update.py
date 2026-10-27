"""Pipeline entry point: fetch the latest river levels into SQLite.

Usage (from the project folder):
    python python/update.py                 # normal update
    python python/update.py --days 30       # first run: backfill 30 days
    python python/update.py --refresh-stations
"""
from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone

import config
import db
import kiwis

log = logging.getLogger("update")


def main() -> int:
    parser = argparse.ArgumentParser(description="Update Cairngorms river levels from SEPA")
    parser.add_argument("--days", type=int, default=7,
                        help="how far back to fetch for stations with no data yet (default 7)")
    parser.add_argument("--refresh-stations", action="store_true",
                        help="re-download the station list even if it is recent")
    parser.add_argument("--db", default=str(config.DB_PATH), help="path to the SQLite database")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    con = db.connect(args.db)

    # 1. Station list (cached; refreshed weekly)
    if args.refresh_stations or db.stations_need_refresh(con):
        log.info("Downloading station list from SEPA...")
        stations = kiwis.get_stage_stations()
        stations = stations[~stations["station_name"].isin(config.EXCLUDE_STATIONS)]
        n = db.upsert_stations(con, stations)
        log.info("Stored %d stations inside the bounding box", n)

    removed = db.remove_stations(con, config.EXCLUDE_STATIONS)
    if removed:
        log.info("Removed %d excluded stations (see EXCLUDE_STATIONS in config.py)", removed)

    stations = db.list_stations(con)
    if stations.empty:
        log.error("No stations found - check the bounding box in config.py")
        db.log_run(con, 0, 0, "error", "no stations")
        return 1

    # 2. Readings: fetch only what's new since the last stored timestamp
    default_since = (datetime.now(timezone.utc) - timedelta(days=args.days)).strftime("%Y-%m-%dT%H:%M:%S")
    total, errors, no_data = 0, [], []

    for s in stations.itertuples(index=False):
        last = db.latest_timestamp(con, s.station_no)
        since = last.replace(" ", "T") if last else default_since
        try:
            readings = kiwis.get_levels(s.ts_id, since)
            added = db.insert_readings(con, s.station_no, readings)
            total += added
            log.info("%-30s +%d readings", s.station_name, added)
            if readings.empty and last is None:
                no_data.append(s.station_name)
        except Exception as exc:  # keep going if one station fails
            errors.append(f"{s.station_name}: {exc}")
            log.warning("%s failed: %s", s.station_name, exc)

    status = "ok" if not errors else ("partial" if len(errors) < len(stations) else "error")
    notes = errors + [f"{name}: no data returned (gauge may be offline)" for name in no_data]
    for name in no_data:
        log.warning("%s returned no data - the gauge may be offline", name)
    db.log_run(con, len(stations), total, status, "; ".join(notes))
    log.info("Done: %d new readings across %d stations (%s)", total, len(stations), status)
    con.close()
    return 0 if status != "error" else 1


if __name__ == "__main__":
    raise SystemExit(main())
