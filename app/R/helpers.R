# Helper functions for the dashboard. Shiny loads everything in app/R/
# automatically, so app.R can use these directly.

STATUS_LEVELS <- c("Low", "Normal", "High", "Very high", "Unknown")

STATUS_COLOURS <- c(
  "Low"       = "#8c96a8",
  "Normal"    = "#2a9d8f",
  "High"      = "#e9a23b",
  "Very high" = "#d1495b",
  "Unknown"   = "#bbbbbb"
)

TREND_ARROWS <- c(Rising = "↑", Falling = "↓", Steady = "→", Unknown = "")

# Use RIVERS_DB if set, else the live database, else the demo one
find_database <- function() {
  candidates <- c(
    Sys.getenv("RIVERS_DB", unset = NA),
    file.path("..", "data", "rivers.sqlite"),
    file.path("..", "data", "demo.sqlite")
  )
  candidates <- candidates[!is.na(candidates) & file.exists(candidates)]
  if (length(candidates) == 0) {
    stop("No database found. Run `python python/update.py` (or make_demo_data.py) first.")
  }
  candidates[[1]]
}

with_db <- function(path, f) {
  con <- DBI::dbConnect(RSQLite::SQLite(), path, flags = RSQLite::SQLITE_RO)
  on.exit(DBI::dbDisconnect(con))
  f(con)
}

get_latest_status <- function(path) {
  with_db(path, function(con) {
    DBI::dbGetQuery(con, "SELECT * FROM latest_status ORDER BY catchment_name, station_name")
  }) |>
    dplyr::mutate(
      status = factor(status, levels = STATUS_LEVELS),
      time   = as.POSIXct(timestamp_utc, tz = "UTC"),
      arrow  = unname(TREND_ARROWS[trend])
    )
}

get_readings <- function(path, station_no, days) {
  with_db(path, function(con) {
    DBI::dbGetQuery(
      con,
      "SELECT r.timestamp_utc, r.level, r.quality_code
         FROM readings_clean r
        WHERE r.station_no = ?
          AND r.timestamp_utc >= datetime(
                (SELECT MAX(timestamp_utc) FROM readings_clean WHERE station_no = ?),
                '-' || ? || ' days')
        ORDER BY r.timestamp_utc",
      params = list(station_no, station_no, as.integer(days))
    )
  }) |>
    dplyr::mutate(time = as.POSIXct(timestamp_utc, tz = "UTC"))
}

get_last_run <- function(path) {
  with_db(path, function(con) {
    DBI::dbGetQuery(con, "SELECT run_at, status FROM fetch_log ORDER BY run_id DESC LIMIT 1")
  })
}

# Plain-English summary for the selected station
describe_station <- function(row) {
  if (nrow(row) == 0) return("")
  pct <- if (is.na(row$pct_typical_range)) "" else
    sprintf(" (%s%% of its typical annual range)", row$pct_typical_range)
  sprintf(
    "%s is at %.2f m%s and is %s (%+.2f m in 3 h). Status: %s.",
    row$station_name, row$level, pct, tolower(row$trend),
    ifelse(is.na(row$change_3h), 0, row$change_3h), row$status
  )
}

plot_levels <- function(readings, station) {
  p <- ggplot2::ggplot(readings, ggplot2::aes(time, level)) +
    ggplot2::geom_line(colour = "#264653", linewidth = 0.6) +
    ggplot2::labs(x = NULL, y = "River level (m)") +
    ggplot2::theme_minimal(base_size = 13)

  refs <- c("Median annual min" = station$median_annual_min,
            "Median annual max" = station$median_annual_max)
  refs <- refs[!is.na(refs)]
  if (length(refs) > 0) {
    p <- p +
      ggplot2::geom_hline(yintercept = refs, linetype = "dashed", colour = "grey50") +
      ggplot2::annotate("text", x = min(readings$time), y = refs, label = names(refs),
                        hjust = 0, vjust = -0.4, size = 3.2, colour = "grey40")
  }
  p
}
