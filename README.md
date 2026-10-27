# Cairngorms River Watch

A small end-to-end data pipeline and dashboard for checking river levels around the Cairngorms before heading out on the hill.

Built with Claude as a coding assistant. I ran and validated the pipeline, did the data QC (identifying sensor glitches and non-river gauges) and am extending it myself.

```
SEPA Time Series API  ──►  Python ingest  ──►  SQLite  ──►  R Shiny dashboard
  (15-min river stage)     (requests, pandas)   (SQL views)   (leaflet map, trends, CSV export)
```

- **Python** (`python/`): finds every SEPA river-level gauge inside a bounding box, then fetches only *new* 15-minute readings on each run. A failed station is logged and doesn't stop the run.
- **SQLite** (`sql/schema.sql`): tables for `stations`, `readings` and a `fetch_log` of each run. A composite primary key (station + timestamp) prevents duplicate readings.
  - `readings_clean` view: removes single-reading sensor spikes using `LAG`/`LEAD` window functions. Raw data is kept untouched.
  - `latest_status` view: each station's latest level, 3-hour trend, and a status band (Low / Normal / High / Very high) relative to SEPA's median annual minimum and maximum.
- **R Shiny** (`app/`): a map coloured by status, a level plot with reference lines, summary boxes, a station table and CSV download.
- **Tests** (`tests/`): offline pytest tests against saved API responses. They cover parsing, timezone handling, bounding-box filtering, de-duplication, spike filtering and the status logic.

**Data QC notes:** loch and reservoir gauges (Loch Vaa, Lochindorb, Spey Dam) are excluded because their levels aren't comparable to river stage. Single-reading dropouts (e.g. a level falling to 0 m and recovering within 30 minutes) are filtered. Rises that happen in several neighbouring catchments at once are treated as real events.

> Gauge levels are a rough guide only. Burns you cross on the hill can rise much faster than the main rivers.

Data: [SEPA Time Series Data Service](https://timeseriesdoc.sepa.org.uk/api-documentation/) (open data).

---

## Setup

```bash
pip install -r requirements.txt
```
```r
install.packages(c("shiny", "bslib", "leaflet", "ggplot2", "dplyr", "DBI", "RSQLite"))
```

## Usage

```bash
python3 python/update.py --days 30     # first run: backfill 30 days
python3 python/update.py               # later runs: fetch only new readings
python3 python/make_demo_data.py       # optional: synthetic data, no internet needed
pytest                                  # run the tests
```

Then in R, from the project folder:
```r
shiny::runApp("app")
```
The app uses `data/rivers.sqlite` if it exists, otherwise `data/demo.sqlite`.

## Configuration

Settings live in `python/config.py`: the bounding box, the stations to exclude, and the request pacing.

## Roadmap

- [ ] Rainfall gauges, to show catchment response time
- [ ] Analysis queries (time above typical maximum, daily peaks)
- [ ] Migrate to PostgreSQL / PostGIS
- [ ] Scheduled hourly updates
- [ ] Deploy the dashboard to shinyapps.io
- [ ] Short-term level forecast (random forest on recent rainfall and level)

## Project structure

```
python/   config.py · kiwis.py (API client) · db.py (database) · update.py (pipeline) · make_demo_data.py
sql/      schema.sql (tables and views)
app/      app.R (Shiny UI and server) · R/helpers.R (queries, plot, labels)
tests/    test_pipeline.py and fixtures/ (sample API responses)
data/     SQLite databases (not tracked)
```
