#!/usr/bin/env Rscript
# export_2018_governor.R — Export 2018 GA Governor results from ALARM RDS
#
# The ALARM GA_cd_2020_map.rds already has VTD-level 2018 Governor results
# in columns gov_18_dem_abr (Abrams/dem) and gov_18_rep_kem (Kemp/rep).
# This script exports them to parquet using RDH column naming so that
# melt_election_vtd() in pg_loaders.py can parse them automatically.
#
# Output column names follow RDH convention: {prefix}{YY}{OFFICE}{PARTY}{CAND}
#   G18GOVDABR = General 2018 Governor Democrat Abrams
#   G18GOVRKEM = General 2018 Governor Republican Kemp
#
# Usage (from fdp/ directory):
#   Rscript scripts/export_2018_governor.R
#   Rscript scripts/export_2018_governor.R --rds /path/to/GA_cd_2020_map.rds

library(arrow)

# ── Paths ──────────────────────────────────────────────────────────────────────
args <- commandArgs(trailingOnly = TRUE)
rds_arg <- NULL
for (i in seq_along(args)) {
    if (args[i] == "--rds" && i < length(args)) rds_arg <- args[i + 1]
}

# Default RDS location — check a few common paths
rds_candidates <- c(
    rds_arg,
    file.path(Sys.getenv("HOME"), "codebox/fgdp/fdensemble/dataverse_files/GA_cd_2020/GA_cd_2020_map.rds"),
    "../fdensemble/dataverse_files/GA_cd_2020/GA_cd_2020_map.rds",
    "data/raw/GA_cd_2020_map.rds"
)

rds_path <- NULL
for (p in rds_candidates) {
    if (!is.null(p) && file.exists(p)) {
        rds_path <- p
        break
    }
}

if (is.null(rds_path)) {
    cat("ERROR: GA_cd_2020_map.rds not found. Tried:\n")
    for (p in rds_candidates[!is.null(rds_candidates)]) cat("  ", p, "\n")
    cat("Use: Rscript scripts/export_2018_governor.R --rds /path/to/GA_cd_2020_map.rds\n")
    quit(status = 1)
}

out_dir  <- file.path(dirname(dirname(normalizePath(sys.frame(0)$ofile %||% "scripts/"))),
                      "data/repos/main/vtd")
# Simpler path derivation for Rscript invocation
script_dir <- tryCatch(
    dirname(normalizePath(commandArgs(FALSE)[4])),
    error = function(e) "scripts"
)
out_dir <- file.path(dirname(script_dir), "data/repos/main/vtd")
dir.create(out_dir, recursive = TRUE, showWarnings = FALSE)
out_path <- file.path(out_dir, "vtd_elections_2018_governor.parquet")

# ── Load ALARM map ─────────────────────────────────────────────────────────────
cat(sprintf("Loading ALARM map from: %s\n", rds_path))
map <- readRDS(rds_path)

cat(sprintf("  %d VTDs loaded\n", nrow(map)))

# Verify columns exist
required_cols <- c("GEOID", "gov_18_dem_abr", "gov_18_rep_kem")
missing <- required_cols[!required_cols %in% colnames(map)]
if (length(missing) > 0) {
    cat("ERROR: missing columns:", paste(missing, collapse = ", "), "\n")
    cat("Available columns:", paste(head(colnames(map), 20), collapse = ", "), "\n")
    quit(status = 1)
}

# ── Build output dataframe ─────────────────────────────────────────────────────
# Rename to RDH format so melt_election_vtd() parses them automatically:
#   G18GOVDABR  = General 2018 Governor Democrat Abrams
#   G18GOVRKEM  = General 2018 Governor Republican Kemp
df <- data.frame(
    GEOID20    = as.character(map$GEOID),
    G18GOVDABR = as.integer(map$gov_18_dem_abr),
    G18GOVRKEM = as.integer(map$gov_18_rep_kem),
    stringsAsFactors = FALSE
)

# Sanity check — remove any NAs
n_na <- sum(is.na(df$G18GOVDABR) | is.na(df$G18GOVRKEM))
if (n_na > 0) {
    cat(sprintf("  WARNING: %d rows with NA votes — replacing with 0\n", n_na))
    df$G18GOVDABR[is.na(df$G18GOVDABR)] <- 0L
    df$G18GOVRKEM[is.na(df$G18GOVRKEM)] <- 0L
}

# ── Vote total check vs GA SOS certified results ───────────────────────────────
# 2018 Governor certified totals (GA SOS):
#   Kemp:   1,978,408
#   Abrams: 1,923,685
sos_abrams <- 1923685L
sos_kemp   <- 1978408L

got_abrams <- sum(df$G18GOVDABR)
got_kemp   <- sum(df$G18GOVRKEM)

pct_abrams <- abs(got_abrams - sos_abrams) / sos_abrams * 100
pct_kemp   <- abs(got_kemp   - sos_kemp)   / sos_kemp   * 100

flag <- function(pct) if (pct < 0.5) "✓" else "⚠"

cat("\nVote-total check vs GA SOS certified results:\n")
cat(sprintf("  %s gov_abrams: %s vs %s (%.2f%% diff)\n",
            flag(pct_abrams),
            format(got_abrams, big.mark=","),
            format(sos_abrams, big.mark=","),
            pct_abrams))
cat(sprintf("  %s gov_kemp:   %s vs %s (%.2f%% diff)\n",
            flag(pct_kemp),
            format(got_kemp, big.mark=","),
            format(sos_kemp, big.mark=","),
            pct_kemp))

# ── Write parquet ──────────────────────────────────────────────────────────────
write_parquet(df, out_path)
cat(sprintf("\n✓ Saved: %s\n", out_path))
cat(sprintf("  %d VTDs  ×  %d columns\n", nrow(df), ncol(df)))
cat(sprintf("  Columns: %s\n", paste(colnames(df), collapse=", ")))
cat("\nNext step:\n")
cat("  uv run python scripts/load_missing_elections.py\n")
