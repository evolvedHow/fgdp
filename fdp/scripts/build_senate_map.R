#!/usr/bin/env Rscript
# build_senate_map.R — Build redist_map for Georgia State Senate (56 districts)
#
# Usage (from anywhere):
#   Rscript fdp/scripts/build_senate_map.R
#
# Inputs (relative to repo root):
#   fdensemble/input_data/ga_pl2020_vtd.zip         — 2020 Census VTD shapefile (2698 VTDs)
#   fdga-chain/data/raw/Senate-2023 shape file.shp  — enacted Senate districts
#
# Output:
#   fdensemble/dataverse_files/GA_ss_2020/GA_ss_2020_map.rds  — redist_map object
#
# After building, upload to Modal volume:
#   modal volume put fdga-chain-data \
#       fdensemble/dataverse_files/GA_ss_2020/GA_ss_2020_map.rds \
#       /maps/GA_ss_2020_map.rds
#
# redist_map schema (matches GA_cd_2020_map.rds conventions):
#   GEOID         TEXT    — 11-char VTD identifier (Census GEOID20)
#   COUNTYFP20    TEXT    — 3-char county FIPS
#   pop           INT     — total population (P0010001)
#   SDIST         INT     — enacted Senate district (1–56)
#   adj           LIST    — rook adjacency list (built by redist_map)
#   pseudo_county INT     — integer county index for SMC county constraint

suppressPackageStartupMessages({
  library(sf)
  library(redist)
  library(dplyr)
})

# ── Resolve repo root ─────────────────────────────────────────────────────────
# Script lives at fdp/scripts/build_senate_map.R → repo root is two levels up.
script_args <- commandArgs(trailingOnly = FALSE)
file_idx    <- grep("^--file=", script_args)
if (length(file_idx) > 0) {
  script_file <- sub("^--file=", "", script_args[file_idx])
} else {
  script_file <- "fdp/scripts/build_senate_map.R"
}
repo_root <- normalizePath(file.path(dirname(script_file), "..", ".."), mustWork = TRUE)
cat(sprintf("[build_senate_map] Repo root: %s\n", repo_root))

vtd_zip    <- file.path(repo_root, "fdensemble", "input_data", "ga_pl2020_vtd.zip")
senate_shp <- file.path(repo_root, "fdga-chain", "data", "raw", "Senate-2023 shape file.shp")
out_dir    <- file.path(repo_root, "fdensemble", "dataverse_files", "GA_ss_2020")
out_rds    <- file.path(out_dir, "GA_ss_2020_map.rds")

if (!file.exists(vtd_zip))    stop("VTD zip not found: ", vtd_zip)
if (!file.exists(senate_shp)) stop("Senate shapefile not found: ", senate_shp)

# ── Step 1: Load VTD shapefile ────────────────────────────────────────────────
cat("[1/5] Loading VTD shapefile…\n")
vtd <- st_read(paste0("zip://", vtd_zip), quiet = TRUE)

vtd$GEOID      <- as.character(vtd$GEOID20)
vtd$COUNTYFP20 <- as.character(vtd$COUNTYFP20)
vtd$pop        <- as.integer(vtd$P0010001)

if (!isTRUE(st_crs(vtd)$epsg == 4326L)) {
  vtd <- st_transform(vtd, 4326)
}

cat(sprintf("  %d VTDs | total pop: %s\n",
            nrow(vtd), format(sum(vtd$pop, na.rm = TRUE), big.mark = ",")))
cat(sprintf("  GEOID sample: %s\n", vtd$GEOID[1]))

# ── Step 2: Load enacted Senate district shapefile ────────────────────────────
cat("[2/5] Loading Senate district shapefile…\n")
senate <- st_read(senate_shp, quiet = TRUE)

if (!"DISTRICT" %in% names(senate)) {
  stop("Expected 'DISTRICT' column. Available: ", paste(names(senate), collapse = ", "))
}
senate$SDIST <- as.integer(senate$DISTRICT)
senate <- st_transform(senate, 4326)

cat(sprintf("  %d districts | SDIST range: %d–%d\n",
            nrow(senate), min(senate$SDIST, na.rm = TRUE), max(senate$SDIST, na.rm = TRUE)))

# ── Step 3: Largest-overlap join (VTD → Senate district) ─────────────────────
# Same method as build_graph.py: intersect each VTD with all districts,
# compute intersection area, assign each VTD to the district it overlaps most.
# This handles VTDs that straddle district boundaries.
cat("[3/5] Joining VTDs → Senate districts (largest-overlap intersection)…\n")
proj_crs    <- "EPSG:32617"    # UTM zone 17N — area-accurate for Georgia
vtd_proj    <- st_transform(vtd[, c("GEOID", "geometry")],     proj_crs)
senate_proj <- st_transform(senate[, c("SDIST", "geometry")],  proj_crs)

suppressWarnings({
  overlay <- st_intersection(vtd_proj, senate_proj)
})
overlay$area <- as.numeric(st_area(overlay))

best_match <- overlay |>
  st_drop_geometry() |>
  group_by(GEOID) |>
  slice_max(area, n = 1, with_ties = FALSE) |>
  ungroup() |>
  select(GEOID, SDIST)

vtd <- vtd |>
  left_join(best_match, by = "GEOID") |>
  mutate(SDIST = coalesce(as.integer(SDIST), 0L))

n_assigned <- sum(vtd$SDIST > 0)
n_missing  <- nrow(vtd) - n_assigned
cat(sprintf("  %d/%d VTDs assigned\n", n_assigned, nrow(vtd)))
if (n_missing > 0) {
  unassigned <- vtd$GEOID[vtd$SDIST == 0]
  warning(sprintf("%d VTDs unassigned (SDIST=0): %s%s",
                  n_missing,
                  paste(head(unassigned, 5), collapse = ", "),
                  if (n_missing > 5) "…" else ""))
}

# ── Step 4: Build redist_map ──────────────────────────────────────────────────
cat("[4/5] Building redist_map (ndists=56, pop_tol=0.05)…\n")

map_data <- vtd |>
  select(GEOID, COUNTYFP20, pop, SDIST, geometry)

map <- redist_map(
  map_data,
  existing_plan = "SDIST",
  pop_col       = "pop",
  pop_tol       = 0.05,
  ndists        = 56L
)

# pseudo_county: sequential integer index by county FIPS.
# Used as the `counties` argument to redist_smc() to enforce the county
# constraint (splits are penalised by the SMC sampler).
map$pseudo_county <- as.integer(factor(map$COUNTYFP20))

n_counties  <- length(unique(map$pseudo_county))
n_districts <- length(unique(map$SDIST[map$SDIST > 0]))
cat(sprintf("  %d VTDs | %d counties | %d districts with VTDs | adj built\n",
            nrow(map), n_counties, n_districts))

# ── Step 5: Save ──────────────────────────────────────────────────────────────
cat(sprintf("[5/5] Saving → %s\n", out_rds))
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
saveRDS(map, out_rds)

size_kb <- file.info(out_rds)$size / 1024
cat(sprintf("  Done. %.0f kB\n\n", size_kb))

cat("[build_senate_map] Complete.\n")
cat("Next steps:\n")
cat("  1. Upload to Modal:\n")
cat("       modal volume put fdga-chain-data \\\n")
cat("           fdensemble/dataverse_files/GA_ss_2020/GA_ss_2020_map.rds \\\n")
cat("           /maps/GA_ss_2020_map.rds\n")
cat("  2. Run ensemble on Modal:\n")
cat("       cd fdga-chain\n")
cat("       uv run python scripts/run_alarm_ensemble.py \\\n")
cat("           --run-name senate_alarm_v1 \\\n")
cat("           --config ../fdp/configs/benchmarks/ga_senate_2026_alarm.yml \\\n")
cat("           --modal\n")
