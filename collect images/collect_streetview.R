# collect_streetview.R
# ══════════════════════════════════════════════════════════════════════════════
# Google Street View Image Collector — St. Louis Housing Study
# ══════════════════════════════════════════════════════════════════════════════
# Pulls street-level images for residential parcels in St. Louis using the
# Google Street View Static API. Each parcel gets multiple images at
# different camera angles to capture the full building exterior.
#
# SETUP
# -----
# Install dependencies (run once in your R console):
#   install.packages(c("httr2", "sf", "dplyr", "readr", "fs", "cli", "magick"))
#
# Get a Google Street View Static API key:
#   https://console.cloud.google.com
#   → Enable "Street View Static API" and "Geocoding API"
#   → Create an API key under Credentials
#   Free: $200/month credit (~28,500 images free per month)
#
# Prepare your parcel data:
#   City:   https://www.stlouis-mo.gov/data/  (search "parcels")
#   County: https://stlcountygis.maps.arcgis.com
#   You need: parcel_id + either lat/lng columns OR an address column.
#
# OUTPUT
# ------
# images/streetview/
#   {parcel_id}/
#     {parcel_id}_h090.jpg    ← facing the house head-on
#     {parcel_id}_h135.jpg    ← 45° right
#     {parcel_id}_h045.jpg    ← 45° left

library(httr2)
library(sf)
library(dplyr)
library(readr)
library(fs)
library(cli)
library(magick)

# ── Configuration ─────────────────────────────────────────────────────────────

GOOGLE_API_KEY <- "YOUR_GOOGLE_API_KEY_HERE"

# Path to your parcel data (.csv or .shp)
PARCEL_FILE <- "stl_parcels.csv"

# Column names — adjust to match your actual file headers
COL_PARCEL_ID  <- "parcel_id"
COL_LAT        <- "latitude"
COL_LNG        <- "longitude"
COL_ADDRESS    <- "address"
COL_PROP_TYPE  <- "prop_type"   # Set to "" to skip residential filtering

# Residential property type values (case-insensitive substring match)
# Set to character(0) to keep all parcels
RESIDENTIAL_TYPES <- c("single family", "single-family", "residential", "sfr")

# How many parcels to process (set to Inf to process all)
# Start small to confirm everything works before a full run
MAX_PARCELS <- 100L

# Camera heading offsets relative to computed bearing toward the house.
# 3 shots per parcel balances coverage vs. API cost.
# Add 90 for a 4th side-view shot.
HEADING_OFFSETS <- c(0, 45, -45)

# Street View image parameters
IMG_WIDTH  <- 640L
IMG_HEIGHT <- 640L
IMG_FOV    <- 90L    # Field of view in degrees (60–90 works well for houses)
IMG_PITCH  <- -5L    # Tilt down slightly to capture full building height

OUTPUT_DIR    <- fs::path("images", "streetview")
REQUEST_DELAY <- 0.3  # Seconds between API calls

# ── Parcel loading ─────────────────────────────────────────────────────────────

load_parcels <- function(filepath) {
  path <- fs::path(filepath)

  if (!fs::file_exists(path)) {
    cli::cli_abort(c(
      "Parcel file not found: {filepath}",
      "i" = "Download from:",
      "*" = "City: {.url https://www.stlouis-mo.gov/data/}",
      "*" = "County: {.url https://stlcountygis.maps.arcgis.com}"
    ))
  }

  ext <- tolower(fs::path_ext(filepath))

  if (ext == "shp") {
    gdf <- sf::st_read(filepath, quiet = TRUE) |>
      sf::st_transform(4326)    # Ensure WGS84

    # Extract centroid coordinates if lat/lng columns don't exist
    if (!COL_LAT %in% names(gdf) || !COL_LNG %in% names(gdf)) {
      centroids <- sf::st_centroid(gdf) |> sf::st_coordinates()
      gdf[[COL_LNG]] <- centroids[, "X"]
      gdf[[COL_LAT]] <- centroids[, "Y"]
    }
    sf::st_drop_geometry(gdf)

  } else {
    readr::read_csv(filepath, col_types = readr::cols(.default = "c"), show_col_types = FALSE)
  }
}

filter_residential <- function(df) {
  if (nchar(COL_PROP_TYPE) == 0 || !COL_PROP_TYPE %in% names(df) ||
      length(RESIDENTIAL_TYPES) == 0) {
    return(df)
  }
  pattern  <- paste(RESIDENTIAL_TYPES, collapse = "|")
  filtered <- df |>
    dplyr::filter(stringr::str_detect(
      tolower(.data[[COL_PROP_TYPE]]),
      pattern
    ))
  cli::cli_alert_info(
    "Filtered to {nrow(filtered):,} residential parcels (from {nrow(df):,} total)"
  )
  filtered
}

# ── Geocoding ──────────────────────────────────────────────────────────────────

geocode_address <- function(address) {
  # Convert a street address to c(lat, lng). Returns NULL on failure.
  tryCatch({
    resp <- request("https://maps.googleapis.com/maps/api/geocode/json") |>
      req_url_query(
        address = paste0(address, ", St. Louis, MO"),
        key     = GOOGLE_API_KEY
      ) |>
      req_timeout(10) |>
      req_perform()

    results <- resp |> resp_body_json() |> purrr::pluck("results")
    if (length(results) > 0) {
      loc <- results[[1]]$geometry$location
      return(c(lat = loc$lat, lng = loc$lng))
    }
    NULL
  }, error = function(e) NULL)
}

# ── Street View metadata ───────────────────────────────────────────────────────

check_streetview_availability <- function(lat, lng) {
  # Check if Street View imagery exists near this point.
  # Returns metadata list if available, NULL otherwise.
  # This call is FREE — metadata requests don't count toward image quota.
  tryCatch({
    resp <- request("https://maps.googleapis.com/maps/api/streetview/metadata") |>
      req_url_query(
        location = sprintf("%.6f,%.6f", lat, lng),
        radius   = 50,
        key      = GOOGLE_API_KEY,
        source   = "outdoor"
      ) |>
      req_timeout(10) |>
      req_perform()

    data <- resp |> resp_body_json()
    if (identical(data$status, "OK")) data else NULL
  }, error = function(e) NULL)
}

# ── Heading calculation ────────────────────────────────────────────────────────

compute_heading <- function(parcel_lat, parcel_lng, camera_lat, camera_lng) {
  # Compute compass bearing from camera position pointing toward the parcel.
  # Returns degrees from North (0–360).
  d_lng <- (parcel_lng - camera_lng) * pi / 180
  p_lat <- parcel_lat * pi / 180
  c_lat <- camera_lat * pi / 180

  x <- sin(d_lng) * cos(p_lat)
  y <- cos(c_lat) * sin(p_lat) - sin(c_lat) * cos(p_lat) * cos(d_lng)

  (atan2(x, y) * 180 / pi + 360) %% 360
}

# ── Image download ─────────────────────────────────────────────────────────────

fetch_streetview_image <- function(lat, lng, heading, save_path) {
  # Download a single Street View image. Returns TRUE on success.
  tryCatch({
    resp <- request("https://maps.googleapis.com/maps/api/streetview") |>
      req_url_query(
        location = sprintf("%.6f,%.6f", lat, lng),
        size     = sprintf("%dx%d", IMG_WIDTH, IMG_HEIGHT),
        heading  = round(heading, 1),
        fov      = IMG_FOV,
        pitch    = IMG_PITCH,
        source   = "outdoor",
        key      = GOOGLE_API_KEY
      ) |>
      req_timeout(15) |>
      req_perform()

    raw <- resp |> resp_body_raw()

    # Google returns a small grey placeholder (~5KB) for missing imagery.
    # Reject anything suspiciously small.
    if (length(raw) < 6000L) return(FALSE)

    img <- magick::image_read(raw)
    magick::image_write(img, path = save_path, format = "jpeg", quality = 92)
    TRUE

  }, error = function(e) FALSE)
}

# ── Per-parcel processing ──────────────────────────────────────────────────────

process_parcel <- function(row, output_dir) {
  parcel_id  <- as.character(row[[COL_PARCEL_ID]])
  parcel_dir <- fs::path(output_dir, parcel_id)

  # Skip if already fully collected
  existing <- if (fs::dir_exists(parcel_dir)) {
    length(fs::dir_ls(parcel_dir, glob = "*.jpg"))
  } else 0L

  if (existing >= length(HEADING_OFFSETS)) return("skipped")

  fs::dir_create(parcel_dir)

  # Get coordinates
  lat <- suppressWarnings(as.numeric(row[[COL_LAT]]))
  lng <- suppressWarnings(as.numeric(row[[COL_LNG]]))

  if (is.na(lat) || is.na(lng)) {
    if (COL_ADDRESS %in% names(row) && nchar(row[[COL_ADDRESS]]) > 0) {
      coords <- geocode_address(row[[COL_ADDRESS]])
      if (!is.null(coords)) {
        lat <- coords["lat"]
        lng <- coords["lng"]
      }
      Sys.sleep(REQUEST_DELAY)
    }
  }

  if (is.na(lat) || is.na(lng)) return("failed_no_coords")

  # Check Street View availability (free metadata call)
  metadata <- check_streetview_availability(lat, lng)
  if (is.null(metadata)) {
    writeLines(
      sprintf("No Street View imagery within 50m of %.6f,%.6f", lat, lng),
      fs::path(parcel_dir, "NO_IMAGERY.txt")
    )
    return("failed_no_imagery")
  }

  cam_lat      <- metadata$location$lat
  cam_lng      <- metadata$location$lng
  base_heading <- compute_heading(lat, lng, cam_lat, cam_lng)

  # Download at each heading offset
  saved <- 0L
  for (offset in HEADING_OFFSETS) {
    heading    <- (base_heading + offset) %% 360
    label      <- sprintf("h%03d", round(heading))
    save_path  <- fs::path(parcel_dir, sprintf("%s_%s.jpg", parcel_id, label))

    if (fs::file_exists(save_path)) { saved <- saved + 1L; next }

    ok <- fetch_streetview_image(cam_lat, cam_lng, heading, save_path)
    if (ok) saved <- saved + 1L
    Sys.sleep(REQUEST_DELAY)
  }

  if (saved > 0L) "success" else "failed_no_images"
}

# ── Main ──────────────────────────────────────────────────────────────────────

main_collect_streetview <- function() {
  cli::cli_h1("Street View Image Collector — St. Louis Housing Study")

  if (GOOGLE_API_KEY == "YOUR_GOOGLE_API_KEY_HERE") {
    cli::cli_abort(c(
      "Google API key not set.",
      "i" = "Get one at: {.url https://console.cloud.google.com}",
      "i" = "Enable 'Street View Static API' and 'Geocoding API'."
    ))
  }

  # Load and filter parcels
  cli::cli_h2("Loading parcels")
  df <- load_parcels(PARCEL_FILE) |> filter_residential()

  if (is.finite(MAX_PARCELS) && nrow(df) > MAX_PARCELS) {
    df <- df |> dplyr::slice_head(n = MAX_PARCELS)
    cli::cli_alert_info("Processing first {MAX_PARCELS} parcels (MAX_PARCELS limit)")
  }

  n_parcels   <- nrow(df)
  n_calls_est <- n_parcels * length(HEADING_OFFSETS)
  cost_est    <- max(0, n_calls_est - 28500) / 1000 * 7

  cli::cli_text("Parcels to process:  {n_parcels:,}")
  cli::cli_text("Images per parcel:   {length(HEADING_OFFSETS)}")
  cli::cli_text("Est. API calls:      {n_calls_est:,}")
  cli::cli_text("Est. cost (USD):     ${round(cost_est, 2)} (after free tier)")

  fs::dir_create(OUTPUT_DIR)

  results <- vector("character", n_parcels)
  cli::cli_progress_bar("Processing parcels", total = n_parcels)

  for (i in seq_len(n_parcels)) {
    results[i] <- tryCatch(
      process_parcel(df[i, ], OUTPUT_DIR),
      error = function(e) "error"
    )
    cli::cli_progress_update()
  }

  cli::cli_progress_done()

  # Summary
  cli::cli_h2("Summary")
  tbl <- table(results)
  cli::cli_text("Parcels with images:     {sum(results == 'success'):,}")
  cli::cli_text("Parcels skipped (done):  {sum(results == 'skipped'):,}")
  cli::cli_text("No imagery available:    {sum(results == 'failed_no_imagery'):,}")
  cli::cli_text("No coordinates found:    {sum(results == 'failed_no_coords'):,}")

  total_imgs <- length(fs::dir_ls(OUTPUT_DIR, glob = "*.jpg", recurse = TRUE))
  cli::cli_text("Total images saved:      {total_imgs:,}")
  cli::cli_text("Output folder:           {fs::path_abs(OUTPUT_DIR)}")

  cli::cli_h2("Next steps")
  cli::cli_bullets(c(
    "1" = "Spot-check ~20 parcel folders to confirm image quality",
    "2" = "Review parcels with NO_IMAGERY.txt for manual follow-up",
    "3" = "Run upload_to_roboflow.R to push images into your project"
  ))
}

# Run it
main_collect_streetview()
