"""
migrate_data.py — One-time migration of data files from all 4 apps into the
Fair Districts Data Platform (fdp) canonical repo.

Sources scanned:
  fdex/data/               → boundaries + demographics
  map-compare/public/data/ → boundaries (deduped against fdex)
  lrdb/public/assets/      → lrdb GeoJSONs + update_helper CSVs
  fdga-chain/data/graphs/  → GerryChain dual-graph JSON
  fdga-chain/data/ensembles/ → ensemble parquets, meta, stability JSON

Files are routed to fdp/data/repos/main/ based on filename patterns.
Existing destination files are NOT overwritten by default (use --overwrite).

Usage:
    uv run python scripts/migrate_data.py              # dry run by default
    uv run python scripts/migrate_data.py --execute    # actually copy files
    uv run python scripts/migrate_data.py --execute --overwrite
    uv run python scripts/migrate_data.py --execute --validate  # run quality checks after
    uv run python scripts/migrate_data.py --apps-root ~/codebox  # if running from elsewhere
"""

from __future__ import annotations

import argparse
import hashlib
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

@dataclass
class TransferRule:
    """Maps source glob patterns to a destination directory within the repo."""
    src_dir: str            # relative to apps_root (e.g. "fdex/data")
    pattern: str            # glob pattern
    dest_subdir: str        # relative to fdp repo root (e.g. "boundaries/congress")
    rename: dict[str, str] = field(default_factory=dict)  # old_name → new_name


def build_rules(apps_root: Path) -> list[TransferRule]:
    """Build the full set of transfer rules."""
    return [
        # ── Boundary GeoJSONs ───────────────────────────────────────────────
        # Congressional (from fdex — authoritative source; map-compare has same files)
        TransferRule("fdex/data", "congress_*.geojson",  "boundaries/congress"),
        TransferRule("fdex/data", "enacted_congress*.geojson", "boundaries/congress"),
        # House
        TransferRule("fdex/data", "house_*.geojson",    "boundaries/house"),
        TransferRule("fdex/data", "enacted_house*.geojson", "boundaries/house"),
        # Senate
        TransferRule("fdex/data", "senate_*.geojson",   "boundaries/senate"),
        TransferRule("fdex/data", "enacted_senate*.geojson", "boundaries/senate"),
        # Reference layers
        TransferRule("fdex/data", "county.geojson",     "boundaries/reference"),
        TransferRule("fdex/data", "places_*.geojson",   "boundaries/reference"),

        # map-compare may have additional GeoJSONs not in fdex — copy with dedup
        TransferRule("map-compare/public/data", "congress_*.geojson", "boundaries/congress"),
        TransferRule("map-compare/public/data", "house_*.geojson",    "boundaries/house"),
        TransferRule("map-compare/public/data", "senate_*.geojson",   "boundaries/senate"),
        TransferRule("map-compare/public/data", "county.geojson",     "boundaries/reference"),
        TransferRule("map-compare/public/data", "places_*.geojson",   "boundaries/reference"),

        # ── Demographics ────────────────────────────────────────────────────
        TransferRule("fdex/data/demographics", "congress.json", "demographics"),
        TransferRule("fdex/data/demographics", "house.json",    "demographics"),
        TransferRule("fdex/data/demographics", "senate.json",   "demographics"),

        # ── LRDB ────────────────────────────────────────────────────────────
        TransferRule("lrdb/public/assets", "lrdb_web_*.geojson",             "lrdb"),
        TransferRule("lrdb/public/assets", "cc_sb_districts*.geojson",       "lrdb"),
        TransferRule("lrdb/public/assets/update_helper", "*.csv",            "lrdb/update_helper"),

        # ── GerryChain graphs ───────────────────────────────────────────────
        TransferRule("fdga-chain/data/graphs",    "ga_*.json",               "graphs"),

        # ── GerryChain ensembles ────────────────────────────────────────────
        TransferRule("fdga-chain/data/ensembles", "*_ensemble.parquet",      "ensembles"),
        TransferRule("fdga-chain/data/ensembles", "*_meta.json",             "ensembles"),
        TransferRule("fdga-chain/data/ensembles", "*_stability.json",        "ensembles"),

        # ── Election parquets (fdga project, if present) ────────────────────
        TransferRule("fdga/data/parquet",         "dim_elections.parquet",   "elections"),
        TransferRule("fdga/data/parquet",         "dim_swings.parquet",      "elections"),
    ]


# ---------------------------------------------------------------------------
# File identity helpers
# ---------------------------------------------------------------------------

def _md5(path: Path, chunk: int = 1 << 20) -> str:
    h = hashlib.md5()
    with path.open("rb") as f:
        while True:
            data = f.read(chunk)
            if not data:
                break
            h.update(data)
    return h.hexdigest()


def _same_content(a: Path, b: Path) -> bool:
    if a.stat().st_size != b.stat().st_size:
        return False
    return _md5(a) == _md5(b)


# ---------------------------------------------------------------------------
# Migration engine
# ---------------------------------------------------------------------------

@dataclass
class CopyResult:
    src: Path
    dest: Path
    status: str   # "copied" | "skipped_exists" | "skipped_identical" | "overwritten" | "src_missing"
    note: str = ""


def migrate(
    apps_root: Path,
    fdp_root: Path,
    execute: bool,
    overwrite: bool,
    verbose: bool,
) -> list[CopyResult]:
    repo_root = fdp_root / "data" / "repos" / "main"
    rules = build_rules(apps_root)
    results: list[CopyResult] = []

    for rule in rules:
        src_dir = apps_root / rule.src_dir
        if not src_dir.exists():
            if verbose:
                print(f"  [skip dir] {rule.src_dir}/ — not found")
            continue

        matches = sorted(src_dir.glob(rule.pattern))
        if not matches and verbose:
            print(f"  [no files] {rule.src_dir}/{rule.pattern}")

        for src in matches:
            if not src.is_file():
                continue

            name = rule.rename.get(src.name, src.name)
            dest_dir = repo_root / rule.dest_subdir
            dest = dest_dir / name

            if not execute:
                # Dry-run: just report what would happen
                status = "would_copy"
                if dest.exists():
                    status = "would_skip" if _same_content(src, dest) else "would_overwrite"
                results.append(CopyResult(src, dest, status))
                continue

            dest_dir.mkdir(parents=True, exist_ok=True)

            if dest.exists():
                if _same_content(src, dest):
                    results.append(CopyResult(src, dest, "skipped_identical"))
                    continue
                if not overwrite:
                    results.append(CopyResult(src, dest, "skipped_exists",
                        note="use --overwrite to replace"))
                    continue
                shutil.copy2(src, dest)
                results.append(CopyResult(src, dest, "overwritten"))
            else:
                shutil.copy2(src, dest)
                results.append(CopyResult(src, dest, "copied"))

    return results


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

STATUS_ICONS = {
    "copied":           "✓",
    "overwritten":      "↺",
    "skipped_identical": "=",
    "skipped_exists":   "!",
    "would_copy":       "→",
    "would_overwrite":  "~",
    "would_skip":       "=",
    "src_missing":      "✗",
}

STATUS_LABELS = {
    "copied":            "copied",
    "overwritten":       "overwritten",
    "skipped_identical": "already identical",
    "skipped_exists":    "skipped (different version exists, use --overwrite)",
    "would_copy":        "would copy",
    "would_overwrite":   "would overwrite (different version exists)",
    "would_skip":        "already identical",
}


def print_report(results: list[CopyResult], execute: bool) -> None:
    from collections import Counter
    counts: Counter = Counter(r.status for r in results)

    # Group by destination subdirectory for readable output
    # Find common repo root by looking for data/repos/main anchor
    by_destdir: dict[str, list[CopyResult]] = {}
    for r in results:
        # Walk up until we find the fdp root (parent of 'data/')
        p = r.dest.parent
        while p.parent.name != "data" or p.parent.parent.name != "": # fallback
            candidate = p
            # Find 'data/repos/main' anchor
            parts = r.dest.parts
            try:
                idx = next(i for i, part in enumerate(parts) if part == "main" and
                           parts[i-1] == "repos" and parts[i-2] == "data")
                key = str(Path(*parts[idx+1:-1])) if idx + 1 < len(parts) - 1 else parts[idx]
            except (StopIteration, IndexError):
                key = str(r.dest.parent.name)
            break
        else:
            key = str(r.dest.parent.name)
        # Simpler: always use the path relative to 'main/'
        parts = r.dest.parts
        try:
            idx = next(i for i, part in enumerate(parts)
                       if part == "main" and i >= 2 and parts[i-1] == "repos" and parts[i-2] == "data")
            key = "/".join(parts[idx + 1: -1]) or parts[idx]
        except StopIteration:
            key = str(r.dest.parent.name)
        by_destdir.setdefault(key, []).append(r)

    print()
    print("=" * 72)
    print(f"  FDP DATA MIGRATION — {'EXECUTE' if execute else 'DRY RUN'}")
    print("=" * 72)

    for dest_dir, items in sorted(by_destdir.items()):
        print(f"\n  {dest_dir}/")
        for r in items:
            icon = STATUS_ICONS.get(r.status, "?")
            note = f"  ({r.note})" if r.note else ""
            print(f"    {icon}  {r.src.name}{note}")

    print()
    print("-" * 72)
    for status, count in sorted(counts.items()):
        label = STATUS_LABELS.get(status, status)
        print(f"  {STATUS_ICONS.get(status, '?')}  {count:3d}  {label}")
    total = len(results)
    print(f"       {total}  total files evaluated")
    print("-" * 72)

    if not execute:
        print()
        print("  This was a DRY RUN. No files were copied.")
        print("  Re-run with --execute to perform the migration.")
    else:
        copied = counts.get("copied", 0) + counts.get("overwritten", 0)
        skipped = counts.get("skipped_identical", 0) + counts.get("skipped_exists", 0)
        print()
        print(f"  Migration complete: {copied} file(s) written, {skipped} skipped.")


# ---------------------------------------------------------------------------
# Post-migration validation
# ---------------------------------------------------------------------------

def run_validation(fdp_root: Path) -> None:
    print("\n" + "=" * 72)
    print("  RUNNING VALIDATION")
    print("=" * 72)
    try:
        sys.path.insert(0, str(fdp_root))
        from fdp.platform import DataPlatform
        from fdp.quality.checks import check_crs, check_geometry_validity, QualityReport
        import geopandas as gpd

        p = DataPlatform(fdp_root=str(fdp_root))
        entries = p.catalog.list(category="boundaries")

        if not entries:
            print("  No boundary files to validate.")
            return

        errors = 0
        for entry in entries:
            try:
                gdf = gpd.read_file(entry.abs_path)
                report = QualityReport()
                check_crs(gdf, report)
                check_geometry_validity(gdf, report)
                if report.has_errors:
                    print(f"  FAIL  {entry.rel_path}: {report.summary}")
                    errors += 1
                else:
                    print(f"  OK    {entry.rel_path}")
            except Exception as e:
                print(f"  ERR   {entry.rel_path}: {e}")
                errors += 1

        print(f"\n  {len(entries) - errors}/{len(entries)} boundary files passed validation.")
        if errors:
            print(f"  {errors} file(s) have issues. Run: fdp validate --category boundaries")
    except ImportError:
        print("  fdp not importable from this environment — skipping validation.")
        print("  Run manually: cd fdp && uv run fdp validate")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Actually copy files (default: dry run only)",
    )
    ap.add_argument(
        "--overwrite",
        action="store_true",
        default=False,
        help="Overwrite destination files that already exist with different content",
    )
    ap.add_argument(
        "--validate",
        action="store_true",
        default=False,
        help="Run quality checks on boundary files after migration",
    )
    ap.add_argument(
        "--apps-root",
        default=None,
        help="Directory containing all app folders (default: parent of fdp/)",
    )
    ap.add_argument(
        "--fdp-root",
        default=None,
        help="fdp platform root directory (default: directory of this script's parent)",
    )
    ap.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Print info about skipped directories and empty globs",
    )
    args = ap.parse_args()

    script_dir = Path(__file__).resolve().parent
    fdp_root = Path(args.fdp_root) if args.fdp_root else script_dir.parent
    apps_root = Path(args.apps_root) if args.apps_root else fdp_root.parent

    print(f"Apps root : {apps_root}")
    print(f"FDP root  : {fdp_root}")
    print(f"Repo root : {fdp_root / 'data' / 'repos' / 'main'}")

    results = migrate(
        apps_root=apps_root,
        fdp_root=fdp_root,
        execute=args.execute,
        overwrite=args.overwrite,
        verbose=args.verbose,
    )

    print_report(results, execute=args.execute)

    if args.validate and args.execute:
        run_validation(fdp_root)

    # Exit non-zero if there were skipped conflicts (different version exists)
    conflicts = sum(1 for r in results if r.status == "skipped_exists")
    if conflicts:
        print(f"\n  WARNING: {conflicts} file(s) were skipped due to version conflicts.")
        print("  Re-run with --overwrite to replace them.")
        sys.exit(2)


if __name__ == "__main__":
    main()
