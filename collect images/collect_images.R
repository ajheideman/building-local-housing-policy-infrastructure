# collect_images.R
# ══════════════════════════════════════════════════════════════════════════════
# Housing Repair Image Collector — Global Images via Bing
# ══════════════════════════════════════════════════════════════════════════════
# Searches Bing Image Search API for housing condition photos and downloads
# them into labeled folders for use as global training data (Model 1).
#
# SETUP
# -----
# Install dependencies (run once in your R console):
#   install.packages(c("httr2", "fs", "cli", "purrr", "digest", "magick"))
#
# Get a free Bing Search API key:
#   https://portal.azure.com → Create resource → "Bing Search v7"
#   Free tier: 1,000 transactions/month
#
# Set your API key below, then source this file or run it section by section.
#
# OUTPUT
# ------
# images/
#   roof_damage/
#     roof_damage_0001.jpg
#     ...
#   facade_deterioration/
#   structural_sagging/
#   window_damage/
#   no_repair_needed/      ← negative examples, equally important

library(httr2)
library(fs)
library(cli)
library(purrr)
library(digest)

# ── Configuration ─────────────────────────────────────────────────────────────

BING_API_KEY        <- "YOUR_BING_API_KEY_HERE"
OUTPUT_DIR          <- fs::path("images")
IMAGES_PER_CATEGORY <- 200L      # 200 × 5 categories = 1,000 total
MIN_PIXELS          <- 200L      # Discard images smaller than this
REQUEST_DELAY       <- 0.5       # Seconds between API calls

# Search queries per category.
# Multiple queries increase variety — Bing returns max 150 results per query.
CATEGORIES <- list(
  roof_damage = c(
    "residential roof damage missing shingles",
    "house roof deterioration sagging",
    "damaged roof residential home exterior"
  ),
  facade_deterioration = c(
    "house exterior paint peeling deterioration",
    "residential building facade crumbling bricks",
    "home siding damage rotting wood exterior"
  ),
  structural_sagging = c(
    "house structural sagging porch deterioration",
    "residential home foundation problems exterior visible",
    "sagging roof line house exterior"
  ),
  window_damage = c(
    "broken windows boarded up house",
    "residential window deterioration damaged frame",
    "house window damage repair needed exterior"
  ),
  no_repair_needed = c(
    "well maintained residential house exterior",
    "good condition single family home",
    "new house exterior well kept"
  )
)

# ── Bing image search ──────────────────────────────────────────────────────────

search_bing <- function(query, count = 50L, offset = 0L) {
  # Returns a list of image result objects from Bing.
  # count: max 150 per call (Bing API limit).
  tryCatch({
    resp <- request("https://api.bing.microsoft.com/v7.0/images/search") |>
      req_headers("Ocp-Apim-Subscription-Key" = BING_API_KEY) |>
      req_url_query(
        q          = query,
        count      = min(count, 150L),
        offset     = offset,
        imageType  = "Photo",
        safeSearch = "Moderate",
        aspect     = "Square"
      ) |>
      req_timeout(10) |>
      req_perform()

    resp |> resp_body_json() |> purrr::pluck("value", .default = list())
  }, error = function(e) {
    cli::cli_alert_warning("Bing API error: {e$message}")
    list()
  })
}

# ── Image download and validation ─────────────────────────────────────────────

load_hashes <- function(category_dir) {
  # Load set of MD5 hashes for already-downloaded images (for deduplication).
  hash_file <- fs::path(category_dir, ".hashes")
  if (fs::file_exists(hash_file)) {
    readLines(hash_file, warn = FALSE)
  } else {
    character(0)
  }
}

save_hash <- function(category_dir, hash) {
  hash_file <- fs::path(category_dir, ".hashes")
  write(hash, hash_file, append = TRUE)
}

download_image <- function(url, save_path, category_dir, existing_hashes, min_pixels) {
  # Download, validate, and deduplicate a single image.
  # Returns TRUE if saved successfully.
  tryCatch({
    resp <- request(url) |>
      req_timeout(8) |>
      req_perform()

    raw_bytes <- resp |> resp_body_raw()

    # Deduplicate by MD5
    img_hash <- digest::digest(raw_bytes, algo = "md5", serialize = FALSE)
    if (img_hash %in% existing_hashes) return(FALSE)

    # Validate using magick (checks it's a real image and meets size minimum)
    img <- magick::image_read(raw_bytes)
    info <- magick::image_info(img)
    if (info$width < min_pixels || info$height < min_pixels) return(FALSE)

    # Save as JPEG
    magick::image_write(img, path = save_path, format = "jpeg", quality = 90)
    save_hash(category_dir, img_hash)
    TRUE

  }, error = function(e) FALSE)
}

# ── Per-category collection ───────────────────────────────────────────────────

collect_category <- function(category_name, queries, target, output_dir, min_pixels) {
  cat_dir <- fs::path(output_dir, category_name)
  fs::dir_create(cat_dir)

  existing_count <- length(fs::dir_ls(cat_dir, glob = "*.jpg"))
  needed         <- target - existing_count

  if (needed <= 0) {
    cli::cli_alert_success("{category_name}: already have {existing_count} images.")
    return(invisible(NULL))
  }

  cli::cli_alert_info("{category_name}: have {existing_count}, collecting {needed} more.")
  existing_hashes <- load_hashes(cat_dir)

  collected <- 0L
  counter   <- existing_count + 1L

  for (query in queries) {
    if (collected >= needed) break

    offset <- 0L
    while (collected < needed && offset < 300L) {
      results <- search_bing(query, count = min(50L, needed - collected), offset = offset)
      if (length(results) == 0) break

      for (result in results) {
        if (collected >= needed) break
        url <- result[["contentUrl"]] %||% ""
        if (nchar(url) == 0) next

        fname     <- fs::path(cat_dir, sprintf("%s_%04d.jpg", category_name, counter))
        saved     <- download_image(url, fname, cat_dir, existing_hashes, min_pixels)

        if (saved) {
          collected       <- collected + 1L
          counter         <- counter + 1L
          existing_hashes <- c(existing_hashes, digest::digest(fname, algo = "md5"))
        }
        Sys.sleep(REQUEST_DELAY)
      }
      offset <- offset + 50L
    }
  }

  total <- length(fs::dir_ls(cat_dir, glob = "*.jpg"))
  cli::cli_alert_success("{category_name}: done. Total: {total} images.")
}

# ── RoboFlow Universe check ───────────────────────────────────────────────────

check_roboflow_universe <- function(roboflow_api_key = "") {
  # Prints matching datasets from RoboFlow Universe.
  # These may already be annotated, saving you Phase 2 work.
  if (nchar(roboflow_api_key) == 0) {
    cli::cli_alert_info(c(
      "RoboFlow API key not provided — skipping Universe search.\n",
      "Search manually at: {.url https://universe.roboflow.com}\n",
      "Try: 'roof damage', 'building damage', 'house condition'"
    ))
    return(invisible(NULL))
  }

  search_terms <- c("roof damage", "building damage", "house exterior", "housing condition")
  cli::cli_h2("Searching RoboFlow Universe for existing datasets")

  for (term in search_terms) {
    tryCatch({
      resp <- request("https://api.roboflow.com/dataset/search") |>
        req_url_query(api_key = roboflow_api_key, q = term, type = "image") |>
        req_timeout(10) |>
        req_perform()

      datasets <- resp |> resp_body_json() |> purrr::pluck("datasets", .default = list())
      if (length(datasets) > 0) {
        cli::cli_text("Results for '{term}':")
        for (ds in utils::head(datasets, 3)) {
          cli::cli_bullets(c(
            "*" = "{ds$name} ({ds$images %||% '?'} images) — {ds$url %||% ''}"
          ))
        }
      }
    }, error = function(e) {
      cli::cli_alert_warning("RoboFlow search error for '{term}': {e$message}")
    })
  }
}

# ── Main ──────────────────────────────────────────────────────────────────────

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0) y else x

main_collect_images <- function(roboflow_api_key = "") {
  cli::cli_h1("Housing Repair Image Collector")

  # Step 1: check RoboFlow Universe for existing datasets
  check_roboflow_universe(roboflow_api_key)

  # Step 2: collect via Bing
  if (BING_API_KEY == "YOUR_BING_API_KEY_HERE") {
    cli::cli_alert_danger(c(
      "Bing API key not set. ",
      "Get a free key at: {.url https://portal.azure.com} ",
      "then set BING_API_KEY at the top of this script."
    ))
    return(invisible(NULL))
  }

  cli::cli_h2("Collecting images via Bing Image Search")
  cli::cli_text("Target: {IMAGES_PER_CATEGORY} images per category")
  cli::cli_text("Output: {fs::path_abs(OUTPUT_DIR)}")

  fs::dir_create(OUTPUT_DIR)

  purrr::iwalk(CATEGORIES, function(queries, category_name) {
    collect_category(
      category_name = category_name,
      queries       = queries,
      target        = IMAGES_PER_CATEGORY,
      output_dir    = OUTPUT_DIR,
      min_pixels    = MIN_PIXELS
    )
  })

  # Summary
  cli::cli_h2("Summary")
  total <- 0L
  purrr::walk(names(CATEGORIES), function(cat) {
    n <- length(fs::dir_ls(fs::path(OUTPUT_DIR, cat), glob = "*.jpg"))
    total <<- total + n
    status <- if (n >= IMAGES_PER_CATEGORY) cli::col_green("✓") else cli::col_yellow(sprintf("⚠ only %d", n))
    cli::cli_text("{status} {cat}: {n} images")
  })
  cli::cli_text("Total: {total} images in {fs::path_abs(OUTPUT_DIR)}")
  cli::cli_alert_info("Next: run collect_streetview.R, then upload_to_roboflow.R")
}

# Run it
main_collect_images(roboflow_api_key = "")  # Optionally pass your RoboFlow key
