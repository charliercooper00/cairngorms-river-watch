"""Build data/demo.sqlite with made-up readings so the dashboard can be tried
without calling the API. Station locations are approximate; all values are
synthetic. Run:  python python/make_demo_data.py
"""
import math
import random
from datetime import datetime, timedelta, timezone

import pandas as pd

import config
import db

DEMO_STATIONS = [
    # station_no, name, catchment, lat, lon, median annual min, median annual max
    ("D001", "Dee at Braemar (demo)",        "Dee",   57.006, -3.398, 0.35, 1.80),
    ("D002", "Dee at Linn of Dee (demo)",    "Dee",   56.988, -3.540, 0.30, 1.60),
    ("D003", "Clunie Water (demo)",          "Dee",   56.975, -3.405, 0.20, 1.10),
    ("D004", "Feshie at Feshiebridge (demo)", "Spey", 57.115, -3.893, 0.25, 1.70),
    ("D005", "Spey at Kinrara (demo)",       "Spey",  57.150, -3.850, 0.40, 2.20),
    ("D006", "Avon at Tomintoul (demo)",     "Spey",  57.250, -3.380, 0.30, 1.50),
    ("D007", "Don at Corgarff (demo)",       "Don",   57.180, -3.250, 0.20, 1.20),
    ("D008", "Tilt at Blair Atholl (demo)",  "Tay",   56.770, -3.840, 0.25, 1.40),
]


def main():
    path = config.PROJECT_ROOT / "data" / "demo.sqlite"
    if path.exists():
        path.unlink()
    con = db.connect(path)

    stations = pd.DataFrame(
        [
            {
                "station_no": s[0], "station_name": s[1], "catchment_name": s[2],
                "station_latitude": s[3], "station_longitude": s[4],
                "ts_id": f"demo-{s[0]}", "ts_path": None, "ts_unitsymbol": "m",
                "sepa_median_annual_minimum_level": s[5],
                "sepa_median_annual_maximum_level": s[6],
                "sepa_maximum_level": s[6] * 1.6, "sepa_maximum_level_timestamp": None,
            }
            for s in DEMO_STATIONS
        ]
    )
    db.upsert_stations(con, stations)

    random.seed(42)
    end = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    times = [end - timedelta(minutes=15 * i) for i in range(30 * 96)][::-1]   # 30 days

    # A recent storm for some stations so the demo shows a range of statuses
    recent_storm = {"D001": 25, "D002": 15, "D003": 5, "D004": 40, "D007": None, "D008": None}
    dry = {"D007"}

    for s in DEMO_STATIONS:
        lo, hi = s[5], s[6]
        storms = [random.randint(0, len(times) - 300) for _ in range(4)]
        if recent_storm.get(s[0]) is not None:
            storms.append(len(times) - recent_storm[s[0]])
        base = lo - 0.05 if s[0] in dry else lo + 0.3 * (hi - lo)
        rows, level = [], base
        for i, t in enumerate(times):
            spate = sum((hi - lo) * 1.0 * math.exp(-((i - k) / 40) ** 2) * (1 if i >= k - 10 else 0.2)
                        for k in storms)
            level = 0.9 * level + 0.1 * (base + spate) + random.gauss(0, 0.005)
            rows.append({"timestamp_utc": t.strftime("%Y-%m-%d %H:%M:%S"),
                         "level": round(level, 3), "quality_code": 50})
        db.insert_readings(con, s[0], pd.DataFrame(rows))

    db.log_run(con, len(DEMO_STATIONS), len(times) * len(DEMO_STATIONS), "ok", "demo data")
    print(f"Demo database written to {path}")


if __name__ == "__main__":
    main()
