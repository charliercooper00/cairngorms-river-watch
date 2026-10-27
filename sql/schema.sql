-- Cairngorms River Watch: database schema (SQLite)
-- All timestamps are stored as UTC text 'YYYY-MM-DD HH:MM:SS' so SQLite's
-- date functions and plain string comparisons both work.

PRAGMA foreign_keys = ON;

-- One row per river-level gauging station
CREATE TABLE IF NOT EXISTS stations (
    station_no          TEXT PRIMARY KEY,
    station_name        TEXT NOT NULL,
    catchment_name      TEXT,
    latitude            REAL NOT NULL,
    longitude           REAL NOT NULL,
    ts_id               TEXT NOT NULL UNIQUE,   -- SEPA time-series id for 15-min stage
    ts_path             TEXT,
    unit                TEXT,
    median_annual_min   REAL,                   -- SEPA reference levels (m)
    median_annual_max   REAL,
    record_max          REAL,
    record_max_time     TEXT,
    updated_at          TEXT NOT NULL
);

-- 15-minute river level readings (long format)
CREATE TABLE IF NOT EXISTS readings (
    station_no      TEXT NOT NULL REFERENCES stations(station_no),
    timestamp_utc   TEXT NOT NULL,
    level           REAL,
    quality_code    INTEGER,
    PRIMARY KEY (station_no, timestamp_utc)     -- stops duplicate rows on re-runs
);

CREATE INDEX IF NOT EXISTS idx_readings_time ON readings (timestamp_utc);

-- Audit trail of each pipeline run
CREATE TABLE IF NOT EXISTS fetch_log (
    run_id          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at          TEXT NOT NULL,
    stations        INTEGER,
    rows_inserted   INTEGER,
    status          TEXT NOT NULL,              -- 'ok' / 'partial' / 'error'
    message         TEXT
);

DROP VIEW IF EXISTS latest_status;
DROP VIEW IF EXISTS readings_clean;

-- Readings with single-reading sensor spikes removed. A reading is a spike if
-- it jumps more than 0.3 m from the reading before AND jumps back more than
-- 0.3 m to the reading after (e.g. 0.87 -> 0.00 -> 0.50 in 30 minutes).
-- Raw data stays untouched in `readings`; this view is what the app uses.
CREATE VIEW readings_clean AS
WITH neighbours AS (
    SELECT station_no, timestamp_utc, level, quality_code,
           LAG(level)  OVER w AS prev_level,
           LEAD(level) OVER w AS next_level
    FROM readings
    WHERE level IS NOT NULL
    WINDOW w AS (PARTITION BY station_no ORDER BY timestamp_utc)
)
SELECT station_no, timestamp_utc, level, quality_code
FROM neighbours
WHERE NOT (
    prev_level IS NOT NULL AND next_level IS NOT NULL
    AND ABS(level - prev_level) > 0.3
    AND ABS(next_level - level) > 0.3
    AND (level - prev_level) * (next_level - level) < 0     -- up then down, or down then up
);

-- Latest reading per station, with 3-hour trend and a status relative to
-- SEPA's median annual minimum / maximum levels.
CREATE VIEW latest_status AS
WITH ranked AS (
    SELECT r.*,
           ROW_NUMBER() OVER (PARTITION BY station_no ORDER BY timestamp_utc DESC) AS rn
    FROM readings_clean r
),
latest AS (
    SELECT station_no, timestamp_utc, level, quality_code
    FROM ranked
    WHERE rn = 1
),
with_trend AS (
    SELECT l.*,
           (SELECT r2.level
              FROM readings_clean r2
             WHERE r2.station_no = l.station_no
               AND r2.timestamp_utc <= datetime(l.timestamp_utc, '-3 hours')
             ORDER BY r2.timestamp_utc DESC
             LIMIT 1) AS level_3h_ago
    FROM latest l
)
SELECT s.station_no,
       s.station_name,
       s.catchment_name,
       s.latitude,
       s.longitude,
       t.timestamp_utc,
       t.level,
       s.median_annual_min,
       s.median_annual_max,
       ROUND(t.level - t.level_3h_ago, 3) AS change_3h,
       CASE
           WHEN t.level_3h_ago IS NULL            THEN 'Unknown'
           WHEN t.level - t.level_3h_ago >  0.02  THEN 'Rising'
           WHEN t.level - t.level_3h_ago < -0.02  THEN 'Falling'
           ELSE 'Steady'
       END AS trend,
       CASE
           WHEN s.median_annual_min IS NULL OR s.median_annual_max IS NULL
                OR s.median_annual_max <= s.median_annual_min THEN NULL
           ELSE ROUND(100.0 * (t.level - s.median_annual_min)
                      / (s.median_annual_max - s.median_annual_min), 0)
       END AS pct_typical_range,
       CASE
           WHEN s.median_annual_min IS NULL OR s.median_annual_max IS NULL
                OR s.median_annual_max <= s.median_annual_min THEN 'Unknown'
           WHEN t.level <  s.median_annual_min THEN 'Low'
           WHEN t.level <  s.median_annual_min
                         + 0.5 * (s.median_annual_max - s.median_annual_min) THEN 'Normal'
           WHEN t.level <  s.median_annual_max THEN 'High'
           ELSE 'Very high'
       END AS status
FROM stations s
JOIN with_trend t ON t.station_no = s.station_no;
