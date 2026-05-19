# upload_to_roboflow.R
# ══════════════════════════════════════════════════════════════════════════════
# RoboFlow Uploader — St. Louis Housing Study
# ══════════════════════════════════════════════════════════════════════════════
# Uploads collected images to a RoboFlow project for annotation.
#
# Two upload modes:
#   A) Street View images (from collect_streetview.R)
#      → Uploaded UNLABELED, ready for manual annotation in RoboFlow
#   B) Global scraped images (from collect_images.R)
#      → Uploaded with CLASS LABELS pre-assigned from folder names
#
# SETUP
# -----
# Install dependencies (run once):
#   install.packages(c("httr2", "fs", "cli", "dplyr", "purrr", "jsonlite"))
#
# Create a RoboFlow project:
#   https://app.roboflow.com → New Project
#   Type: Image Classification  (binary: repair needed / not needed)
#      OR Object Detection       (if you want bounding boxes)
#   Name: e.g. "stl-housing-repair"
#
# Get your credentials:
#   API key:         roboflow.com → Settings → API Keys → Private key
#   Workspace slug:  shown in URL → app.roboflow.com/{workspace}/
#   Project slug:    shown in URL → app.roboflow.com/{workspace}/{project}/
#
# AFTER UPLOADING
# ---------------
# 1. Annotate Street View images:
#    https://app.roboflow.com/{workspace}/{project}/annotate
#    Use Label Assist (AI pre-labeling) to speed this up significantly.
# 2. Check class balance in the Dataset Health tab.
# 3. Click Generate to create a versioned, split dataset.
# 4. Export in folder/classification format for PyTorch model training.

library(httr2)
library(fs)
library(cli)
library(dplyr)
library(purrr)
library(jsonlite)

# ── Configuration ─────────────────────────────────────────────────────────────

ROBOFLOW_API_KEY   <- "YOUR_ROBOFLOW_PRIVATE_API_KEY"
ROBOFLOW_WORKSPACE <- "your-workspace-slug"    # e.g. "umsl-housing-lab"
ROBOFLOW_PROJECT   <- "your-project-slug"      # e.g. "stl-housing-repair"

STREETVIEW_DIR <- fs::path("images", "streetview")
GLOBAL_DIR     <- fs::path("images")

UPLOAD_STREETVIEW <- TRUE
UPLOAD_GLOBAL     <- TRUE

REQUEST_DELAY <- 0.3   # Seconds between uploads — don't go below 0.2
MAX_IMAGES    <- Inf   # Set to e.g. 50 for a test run, Inf for all

# Folder names to skip when scanning the global images directory
SKIP_FOLDERS <- c("streetview")

# File tracking which images have already been uploaded (supports resuming)
UPLOAD_LOG <- fs::path("roboflow_upload_log.json")

# ── Upload log ────────────────────────────────────────────────────────────────

load_upload_log <- function() {
  if (fs::file_exists(UPLOAD_LOG)) {
    tryCatch(
      jsonlite::read_json(UPLOAD_LOG) |> unlist() |> as.character(),
      error = function(e) character(0)
    )
  } else {
    character(0)
  }
}

save_upload_log <- function(uploaded) {
  jsonlite::write_json(as.list(sort(uploaded)), UPLOAD_LOG, pretty = TRUE)
}

# ── Single image upload ───────────────────────────────────────────────────────

upload_image <- function(image_path, label = NULL, batch_name = NULL,
                         split = "train", retries = 1L) {
  # Upload one image to RoboFlow. Returns TRUE on success.
  url <- sprintf(
    "https://api.roboflow.com/dataset/%s/upload?api_key=%s&workspace=%s",
    ROBOFLOW_PROJECT, ROBOFLOW_API_KEY, ROBOFLOW_WORKSPACE
  )

  query_params <- list(split = split)
  if (!is.null(label) && nchar(label) > 0) query_params$annotation <- label
  if (!is.null(batch_name))               query_params$batch       <- batch_name

  req <- request(url) |>
    req_url_query(!!!query_params) |>
    req_body_multipart(
      file = curl::form_file(as.character(image_path), type = "image/jpeg")
    ) |>
    req_timeout(30)

  tryCatch({
    resp <- req_perform(req)
    data <- resp |> resp_body_json()

    if (isTRUE(data$success) || isTRUE(data$duplicate)) return(TRUE)

    cli::cli_alert_warning("Upload failed for {fs::path_file(image_path)}: {data}")
    FALSE

  }, error = function(e) {
    # Handle rate limiting with a single retry
    if (grepl("429", conditionMessage(e)) && retries > 0L) {
      cli::cli_alert_warning("Rate limited — waiting 10 seconds...")
      Sys.sleep(10)
      return(upload_image(image_path, label, batch_name, split, retries - 1L))
    }
    cli::cli_alert_warning("Error uploading {fs::path_file(image_path)}: {e$message}")
    FALSE
  })
}

# ── Scenario A: Street View (unlabeled) ───────────────────────────────────────

upload_streetview_images <- function(uploaded) {
  if (!fs::dir_exists(STREETVIEW_DIR)) {
    cli::cli_alert_warning(
      "Street View directory not found: {STREETVIEW_DIR}. Run collect_streetview.R first."
    )
    return(list(uploaded = uploaded, success = 0L, fail = 0L))
  }

  # Collect all images grouped by parcel
  all_images <- fs::dir_ls(STREETVIEW_DIR, glob = "*.jpg", recurse = TRUE) |>
    tibble::tibble(path = _) |>
    dplyr::mutate(
      parcel_id = fs::path_file(fs::path_dir(path))
    )

  pending <- all_images |>
    dplyr::filter(!path %in% uploaded) |>
    dplyr::slice_head(n = min(MAX_IMAGES, dplyr::n()))

  cli::cli_h3("Street View images")
  cli::cli_text("{nrow(all_images)} total, {nrow(pending)} pending upload")

  success <- 0L
  fail    <- 0L

  cli::cli_progress_bar("Uploading Street View", total = nrow(pending))

  for (i in seq_len(nrow(pending))) {
    row      <- pending[i, ]
    img_path <- row$path

    ok <- upload_image(
      image_path = img_path,
      label      = NULL,    # No label — annotate manually in RoboFlow
      batch_name = sprintf("streetview_%s", row$parcel_id),
      split      = "train"
    )

    if (ok) {
      success  <- success + 1L
      uploaded <- c(uploaded, img_path)
    } else {
      fail <- fail + 1L
    }

    # Save progress every 50 images
    if ((success + fail) %% 50L == 0L) save_upload_log(uploaded)

    cli::cli_progress_update()
    Sys.sleep(REQUEST_DELAY)
  }

  cli::cli_progress_done()
  list(uploaded = uploaded, success = success, fail = fail)
}

# ── Scenario B: Global images (pre-labeled by folder) ─────────────────────────

upload_global_images <- function(uploaded) {
  if (!fs::dir_exists(GLOBAL_DIR)) {
    cli::cli_alert_warning(
      "Global images directory not found: {GLOBAL_DIR}. Run collect_images.R first."
    )
    return(list(uploaded = uploaded, success = 0L, fail = 0L))
  }

  # Each subfolder name becomes the class label
  category_dirs <- fs::dir_ls(GLOBAL_DIR, type = "directory") |>
    purrr::keep(~ !fs::path_file(.x) %in% SKIP_FOLDERS)

  all_images <- purrr::map_dfr(category_dirs, function(cat_dir) {
    fs::dir_ls(cat_dir, glob = "*.jpg") |>
      tibble::tibble(path = _) |>
      dplyr::mutate(label = fs::path_file(cat_dir))
  })

  pending <- all_images |>
    dplyr::filter(!path %in% uploaded) |>
    dplyr::slice_head(n = min(MAX_IMAGES, dplyr::n()))

  cli::cli_h3("Global images")
  cli::cli_text("{nrow(all_images)} total, {nrow(pending)} pending upload")

  # Show category breakdown
  pending |>
    dplyr::count(label) |>
    purrr::pwalk(function(label, n) cli::cli_text("  {label}: {n} images"))

  success <- 0L
  fail    <- 0L

  cli::cli_progress_bar("Uploading global images", total = nrow(pending))

  for (i in seq_len(nrow(pending))) {
    row      <- pending[i, ]
    img_path <- row$path

    ok <- upload_image(
      image_path = img_path,
      label      = row$label,
      batch_name = sprintf("global_%s", row$label),
      split      = "train"
    )

    if (ok) {
      success  <- success + 1L
      uploaded <- c(uploaded, img_path)
    } else {
      fail <- fail + 1L
    }

    if ((success + fail) %% 50L == 0L) save_upload_log(uploaded)

    cli::cli_progress_update()
    Sys.sleep(REQUEST_DELAY)
  }

  cli::cli_progress_done()
  list(uploaded = uploaded, success = success, fail = fail)
}

# ── Dataset health check ──────────────────────────────────────────────────────

check_dataset_health <- function() {
  url <- sprintf(
    "https://api.roboflow.com/%s/%s?api_key=%s",
    ROBOFLOW_WORKSPACE, ROBOFLOW_PROJECT, ROBOFLOW_API_KEY
  )

  tryCatch({
    resp    <- request(url) |> req_timeout(10) |> req_perform()
    project <- resp |> resp_body_json() |> purrr::pluck("project")

    cli::cli_rule("RoboFlow dataset health")
    cli::cli_text("Project:      {project$name}")
    cli::cli_text("Total images: {project$images %||% '—'}")

    splits <- project$splits %||% list()
    if (length(splits) > 0) {
      cli::cli_text("Splits:")
      purrr::iwalk(splits, ~ cli::cli_text("  {.y}: {.x}"))
    }

    classes <- project$classes %||% list()
    if (length(classes) > 0) {
      cli::cli_text("Classes:")
      counts    <- purrr::map_int(classes, ~ .x$count %||% 0L)
      max_count <- max(counts, 1L)
      purrr::walk(classes, function(cls) {
        n    <- cls$count %||% 0L
        bar  <- strrep("█", round(20 * n / max_count))
        warn <- if (n < max_count * 0.5) " ⚠ imbalanced" else ""
        cli::cli_text("  {cls$name}: {n}  {bar}{warn}")
      })
    }

    unannotated <- project$unannotated %||% 0L
    if (unannotated > 0L) {
      cli::cli_alert_warning("{unannotated} images still need annotation")
      cli::cli_text(
        "Annotate at: {.url https://app.roboflow.com/{ROBOFLOW_WORKSPACE}/{ROBOFLOW_PROJECT}/annotate}"
      )
    }

  }, error = function(e) {
    cli::cli_alert_warning("Could not fetch dataset stats: {e$message}")
  })
}

# ── Main ──────────────────────────────────────────────────────────────────────

`%||%` <- function(x, y) if (is.null(x) || length(x) == 0) y else x

main_upload <- function() {
  cli::cli_h1("RoboFlow Uploader — St. Louis Housing Study")

  if (ROBOFLOW_API_KEY == "YOUR_ROBOFLOW_PRIVATE_API_KEY") {
    cli::cli_abort(c(
      "RoboFlow API key not set.",
      "i" = "Get it at: {.url https://roboflow.com} → Settings → API Keys"
    ))
  }

  uploaded <- load_upload_log()
  cli::cli_alert_info("Upload log: {length(uploaded)} images already uploaded.")

  total_success <- 0L
  total_fail    <- 0L

  if (UPLOAD_STREETVIEW) {
    result        <- upload_streetview_images(uploaded)
    uploaded      <- result$uploaded
    total_success <- total_success + result$success
    total_fail    <- total_fail    + result$fail
    save_upload_log(uploaded)
    cli::cli_alert_success("Street View: {result$success} uploaded, {result$fail} failed")
  }

  if (UPLOAD_GLOBAL) {
    result        <- upload_global_images(uploaded)
    uploaded      <- result$uploaded
    total_success <- total_success + result$success
    total_fail    <- total_fail    + result$fail
    save_upload_log(uploaded)
    cli::cli_alert_success("Global images: {result$success} uploaded, {result$fail} failed")
  }

  cli::cli_rule()
  cli::cli_text("Upload complete: {total_success} succeeded, {total_fail} failed")
  cli::cli_text("Log saved to: {UPLOAD_LOG}")

  check_dataset_health()

  cli::cli_h2("Next steps")
  cli::cli_bullets(c(
    "1" = "Annotate Street View images in RoboFlow:",
    " " = "{.url https://app.roboflow.com/{ROBOFLOW_WORKSPACE}/{ROBOFLOW_PROJECT}/annotate}",
    "2" = "Use Label Assist (AI pre-labeling) to speed up annotation",
    "3" = "Check class balance in the Dataset Health tab",
    "4" = "Generate a versioned dataset when annotation is complete",
    "5" = "Export as folder/classification format for PyTorch model training"
  ))
}

# Run it
main_upload()
