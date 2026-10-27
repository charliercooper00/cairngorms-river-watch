# Cairngorms River Watch - Shiny dashboard
# Run from the project folder:  shiny::runApp("app")

library(shiny)
library(bslib)
library(leaflet)
library(ggplot2)
library(dplyr)

db_path <- find_database()

ui <- page_sidebar(
  title = "Cairngorms River Watch",
  fillable = FALSE,
  theme = bs_theme(bootswatch = "flatly"),

  sidebar = sidebar(
    width = 300,
    selectInput("catchment", "Catchment", choices = "All"),
    selectInput("station", "Station", choices = NULL),
    sliderInput("days", "Days to show", min = 1, max = 30, value = 7),
    downloadButton("download", "Download readings (CSV)"),
    hr(),
    uiOutput("last_updated"),
    actionButton("refresh", "Reload from database", icon = icon("rotate")),
    p(class = "small text-muted mt-3",
      "Status compares the latest level with SEPA's median annual minimum and",
      "maximum at each gauge. A rough guide only: burns you cross on the hill",
      "can rise much faster than the gauged rivers. Data: SEPA.")
  ),

  layout_columns(
    col_widths = c(3, 3, 3, 3),
    value_box("Stations", textOutput("n_stations"), theme = "secondary"),
    value_box("High / very high", textOutput("n_high"), theme = "warning"),
    value_box("Rising now", textOutput("n_rising"), theme = "info"),
    value_box("Latest reading (UTC)", textOutput("latest_time"), textOutput("latest_date"), theme = "light")
  ),
  layout_columns(
    col_widths = c(6, 6),
    card(card_header("Latest levels"), leafletOutput("map", height = 450)),
    card(card_header(textOutput("plot_title")),
         plotOutput("plot", height = 340),
         textOutput("summary"))
  ),
  card(card_header("All stations"), tableOutput("table"))
)

server <- function(input, output, session) {

  reload <- reactiveVal(0)
  observeEvent(input$refresh, reload(reload() + 1))

  latest <- reactive({
    reload()
    get_latest_status(db_path)
  })

  observe({
    updateSelectInput(session, "catchment",
                      choices = c("All", sort(unique(latest()$catchment_name))),
                      selected = isolate(input$catchment))
  })

  filtered <- reactive({
    d <- latest()
    if (!is.null(input$catchment) && input$catchment != "All") {
      d <- filter(d, catchment_name == input$catchment)
    }
    d
  })

  observe({
    d <- filtered()
    current <- isolate(input$station)
    updateSelectInput(session, "station",
                      choices = setNames(d$station_no, d$station_name),
                      selected = if (!is.null(current) && current %in% d$station_no) current else d$station_no[1])
  })

  # Clicking a map marker selects that station
  observeEvent(input$map_marker_click, {
    updateSelectInput(session, "station", selected = input$map_marker_click$id)
  })

  selected <- reactive({
    req(input$station)
    filter(latest(), station_no == input$station)
  })

  readings <- reactive({
    req(input$station)
    reload()
    get_readings(db_path, input$station, input$days)
  })

  # ---- value boxes ----
  output$n_stations  <- renderText(nrow(filtered()))
  output$n_high      <- renderText(sum(filtered()$status %in% c("High", "Very high")))
  output$n_rising    <- renderText(sum(filtered()$trend == "Rising"))
  output$latest_time <- renderText(format(max(filtered()$time), "%H:%M"))
  output$latest_date <- renderText(format(max(filtered()$time), "%d %b %Y"))

  output$last_updated <- renderUI({
    reload()
    run <- get_last_run(db_path)
    if (nrow(run) == 0) return(NULL)
    p(class = "small", strong("Last pipeline run: "), run$run_at, " UTC (", run$status, ")")
  })

  # ---- map ----
  output$map <- renderLeaflet({
    d <- filtered()
    pal <- colorFactor(unname(STATUS_COLOURS), levels = names(STATUS_COLOURS))
    leaflet(d) |>
      addProviderTiles(providers$OpenTopoMap) |>
      addCircleMarkers(
        lng = ~longitude, lat = ~latitude, layerId = ~station_no,
        radius = 9, stroke = TRUE, color = "white", weight = 2,
        fillColor = ~pal(status), fillOpacity = 0.9,
        label = ~sprintf("%s: %.2f m %s (%s)", station_name, level, arrow, status)
      ) |>
      addLegend("bottomright", pal = pal, values = ~status, title = "Status", opacity = 0.9) |>
      fitBounds(min(d$longitude), min(d$latitude), max(d$longitude), max(d$latitude))
  })

  # ---- time series ----
  output$plot_title <- renderText({
    s <- selected()
    if (nrow(s) == 0) "Select a station" else s$station_name
  })

  output$plot <- renderPlot({
    r <- readings()
    validate(need(nrow(r) > 0, "No readings for this station yet."))
    plot_levels(r, selected())
  })

  output$summary <- renderText(describe_station(selected()))

  # ---- table ----
  output$table <- renderTable({
    filtered() |>
      transmute(
        Station   = station_name,
        Catchment = catchment_name,
        `Level (m)` = sprintf("%.2f", level),
        Trend     = paste(arrow, trend),
        `% typical range` = ifelse(is.na(pct_typical_range), "-", paste0(pct_typical_range, "%")),
        Status    = as.character(status),
        `Time (UTC)` = format(time, "%d %b %H:%M")
      )
  })

  # ---- download ----
  output$download <- downloadHandler(
    filename = function() {
      sprintf("%s_last_%sd_levels.csv", gsub("[^A-Za-z0-9]+", "_", selected()$station_name), input$days)
    },
    content = function(file) {
      readings() |>
        mutate(station_no = input$station, station_name = selected()$station_name) |>
        select(station_no, station_name, timestamp_utc, level, quality_code) |>
        write.csv(file, row.names = FALSE)
    }
  )
}

shinyApp(ui, server)
