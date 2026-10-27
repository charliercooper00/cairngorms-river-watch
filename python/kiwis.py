"""Small client for SEPA's KiWIS time-series API.

Two jobs:
  1. get_stage_stations()  -> which river-level gauges exist, and where
  2. get_levels()          -> the 15-minute level readings for one gauge

The parse_* functions are kept separate from the HTTP calls so they can be
tested offline against saved example responses (see tests/).
"""
from __future__ import annotations

import time

import pandas as pd
import requests

import config

# SEPA reference levels returned as station "custom attributes" (ca_sta)
CA_STA_FIELDS = [
    "sepa_median_annual_minimum_level",
    "sepa_median_annual_maximum_level",
    "sepa_maximum_level",
    "sepa_maximum_level_timestamp",
]

STATION_FIELDS = [
    "station_no",
    "station_name",
    "catchment_name",
    "station_latitude",
    "station_longitude",
    "ts_id",
    "ts_path",
    "ts_unitsymbol",
]


class KiwisError(RuntimeError):
    pass


_session = requests.Session()
_session.headers.update({"User-Agent": config.USER_AGENT})


def _get(params: dict):
    """Send one request to KiWIS and return the decoded JSON."""
    query = {**config.BASE_PARAMS, **params}
    response = _session.get(config.BASE_URL, params=query, timeout=config.REQUEST_TIMEOUT_SECONDS)
    time.sleep(config.REQUEST_PAUSE_SECONDS)
    if response.status_code != 200:
        raise KiwisError(f"HTTP {response.status_code}: {response.text[:300]}")
    payload = response.json()
    # KiWIS reports errors as a JSON object rather than an HTTP error code
    if isinstance(payload, dict) and payload.get("type") == "error":
        raise KiwisError(payload.get("message", str(payload)))
    return payload


# --------------------------------------------------------------------------
# Stations
# --------------------------------------------------------------------------
def parse_station_list(payload) -> pd.DataFrame:
    """KiWIS list format: first row is the header, the rest are data rows.

    Custom attributes (ca_sta) may come back either as extra columns or as a
    nested dict / list-of-dicts in a 'ca_sta' column, so both are handled.
    """
    if not payload or len(payload) < 2:
        return pd.DataFrame(columns=STATION_FIELDS + CA_STA_FIELDS)

    header, rows = payload[0], payload[1:]
    df = pd.DataFrame(rows, columns=header)

    if "ca_sta" in df.columns:
        def flatten(cell):
            if isinstance(cell, list):
                cell = cell[0] if cell else {}
            return cell if isinstance(cell, dict) else {}

        extra = pd.DataFrame([flatten(c) for c in df["ca_sta"]], index=df.index)
        df = pd.concat([df.drop(columns="ca_sta"), extra], axis=1)

    for col in STATION_FIELDS + CA_STA_FIELDS:
        if col not in df.columns:
            df[col] = None

    numeric = ["station_latitude", "station_longitude"] + CA_STA_FIELDS[:3]
    for col in numeric:
        df[col] = pd.to_numeric(df[col], errors="coerce")

    return df[STATION_FIELDS + CA_STA_FIELDS]


def filter_to_bbox(df: pd.DataFrame, bbox: dict) -> pd.DataFrame:
    inside = (
        df["station_latitude"].between(bbox["lat_min"], bbox["lat_max"])
        & df["station_longitude"].between(bbox["lon_min"], bbox["lon_max"])
    )
    return df[inside].reset_index(drop=True)


def get_stage_stations(bbox: dict = config.BBOX) -> pd.DataFrame:
    """All 15-minute river-level series inside the bounding box."""
    params = {
        "request": "getTimeseriesList",
        "ts_path": config.STAGE_TS_PATH,
        "returnfields": ",".join(STATION_FIELDS + ["ca_sta"]),
        "ca_sta_returnfields": ",".join(CA_STA_FIELDS),
    }
    try:
        payload = _get(params)
    except KiwisError:
        # If the reference levels aren't available, still get the stations
        params["returnfields"] = ",".join(STATION_FIELDS)
        params.pop("ca_sta_returnfields")
        payload = _get(params)

    return filter_to_bbox(parse_station_list(payload), bbox)


# --------------------------------------------------------------------------
# Level readings
# --------------------------------------------------------------------------
def parse_values(payload) -> pd.DataFrame:
    """getTimeseriesValues returns a list with one object per series:
    {"ts_id": ..., "columns": "Timestamp,Value,Quality Code", "data": [[...], ...]}
    """
    frames = []
    for series in payload or []:
        data = series.get("data") or []
        if not data:
            continue
        columns = [c.strip() for c in series.get("columns", "Timestamp,Value,Quality Code").split(",")]
        df = pd.DataFrame(data, columns=columns)
        df["ts_id"] = str(series.get("ts_id"))
        frames.append(df)

    if not frames:
        return pd.DataFrame(columns=["ts_id", "timestamp_utc", "level", "quality_code"])

    df = pd.concat(frames, ignore_index=True)
    df["timestamp_utc"] = (
        pd.to_datetime(df["Timestamp"], utc=True, format="ISO8601")
        .dt.strftime("%Y-%m-%d %H:%M:%S")
    )
    df["level"] = pd.to_numeric(df["Value"], errors="coerce")
    df["quality_code"] = pd.to_numeric(df.get("Quality Code"), errors="coerce").astype("Int64")
    return df[["ts_id", "timestamp_utc", "level", "quality_code"]]


def get_levels(ts_id: str, since_utc: str) -> pd.DataFrame:
    """Readings for one series from `since_utc` (ISO date or datetime) to now."""
    payload = _get({
        "request": "getTimeseriesValues",
        "ts_id": ts_id,
        "from": since_utc,
        "returnfields": "Timestamp,Value,Quality Code",
    })
    return parse_values(payload)
