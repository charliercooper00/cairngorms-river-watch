"""Project settings. Change the bounding box to watch a different area."""
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_ROOT / "data" / "rivers.sqlite"
SCHEMA_PATH = PROJECT_ROOT / "sql" / "schema.sql"

# SEPA Time Series API (KiWIS). Docs: https://timeseriesdoc.sepa.org.uk/api-documentation/
BASE_URL = "https://timeseries.sepa.org.uk/KiWIS/KiWIS"
BASE_PARAMS = {
    "service": "kisters",
    "type": "queryServices",
    "datasource": "0",
    "format": "json",
}

# 15-minute river stage (level) series at every station
STAGE_TS_PATH = "*/*/SG/15m.Cmd"

# Cairngorms National Park and surrounding glens (WGS84)
BBOX = {
    "lat_min": 56.75,
    "lat_max": 57.45,
    "lon_min": -4.35,
    "lon_max": -2.85,
}

# Be polite to a free public service
REQUEST_PAUSE_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 60
USER_AGENT = "cairngorms-river-watch (personal portfolio project)"

# Re-download the station list if it's older than this
STATION_REFRESH_DAYS = 7

# Gauges to leave out: loch and reservoir levels rather than rivers, so their
# status bands aren't meaningful for river crossings. Matched on station name.
EXCLUDE_STATIONS = [
    "Loch Vaa",
    "Lochindorb Level",
    "Spey Dam",
]
