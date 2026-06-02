#!/usr/bin/env Rscript
#
# Export ALARM GA_cd_2020 ensemble plan assignments to parquet.
#
# Reads GA_cd_2020_map.rds and GA_cd_2020_plans.rds (no redist package needed —
# the plan matrix is accessed directly via attr()).
#
# Output: fdp/data/repos/main/ensemble/ga_congress_2020_alarm_5001_plans.parquet
#   Columns: plan_id, draw, geoid, geo_level, state, district, chamber
#   Rows:    5001 draws × 2698 VTDs = 13,487,698
#
# Usage (from fdp/ in WSL):
#   Rscript scripts/export_ensemble_plans.R

library(arrow)

# ── Paths ──────────────────────────────────────────────────────────────────────

ALARM_DIR  <- file.path(Sys.getenv("HOME"),
                        "codebox/fgdp/fdensemble/dataverse_files/GA_cd_2020")
MAP_FILE   <- file.path(ALARM_DIR, "GA_cd_2020_map.rds")
PLANS_FILE <- file.path(ALARM_DIR, "GA_cd_2020_plans.rds")

FDP_ROOT <- file.path(Sys.getenv("HOME"), "codebox/fgdp/fdp")
OUT_DIR  <- file.path(FDP_ROOT, "data/repos/main/ensemble")
OUT_FILE <- file.path(OUT_DIR, "ga_congress_2020_alarm_5001_plans.parquet")

# ── Load ───────────────────────────────────────────────────────────────────────

cat("Loading map:", MAP_FILE, "\n")
map <- readRDS(MAP_FILE)
cat("  Map rows:", nrow(map), "\n")
cat("  GEOID sample:", as.character(map$GEOID[1]), "\n")

cat("Loading plans:", PLANS_FILE, "\n")
plans <- readRDS(PLANS_FILE)

# Extract plan matrix: rows = VTDs, cols = draws
plan_mat <- attr(plans, "plans")
n_vtds   <- nrow(plan_mat)   # 2698
n_draws  <- ncol(plan_mat)   # 5001

cat("  Plan matrix:", n_vtds, "VTDs x", n_draws, "draws\n")
cat("  District range:", min(plan_mat), "-", max(plan_mat), "\n")

stopifnot(n_vtds == nrow(map))

# ── Build long-format data frame (vectorised, no loop) ─────────────────────────

cat("\nBuilding long-format assignment table (~", n_vtds * n_draws, "rows)...\n")

# Column-major: as.vector goes down col 1 (draw 1), then col 2 (draw 2), etc.
result <- data.frame(
  plan_id   = "ga_congress_2020_alarm_5001",
  draw      = rep(seq_len(n_draws), each = n_vtds),
  geoid     = rep(as.character(map$GEOID), times = n_draws),
  geo_level = "vtd",
  state     = "GA",
  district  = as.integer(as.vector(plan_mat)),
  chamber   = "congress",
  stringsAsFactors = FALSE
)

cat("  Built:", nrow(result), "rows x", ncol(result), "columns\n")

# Sanity check: draw 1 = enacted plan; should have 14 distinct districts
enacted_districts <- length(unique(result$district[result$draw == 1]))
cat("  Draw 1 (enacted) districts:", enacted_districts, "(expected 14)\n")

# ── Write parquet ──────────────────────────────────────────────────────────────

dir.create(OUT_DIR, recursive = TRUE, showWarnings = FALSE)
cat("\nWriting parquet:", OUT_FILE, "\n")
write_parquet(result, OUT_FILE, compression = "zstd")

file_mb <- file.size(OUT_FILE) / 1024 / 1024
cat("  Done:", round(file_mb, 1), "MB\n")
cat("\nNext step: load into Supabase via\n")
cat("  uv run python scripts/load_ensemble_plans.py\n")
