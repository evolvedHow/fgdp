"""
FDP command-line interface.

Database setup (run once on a new environment)
-----------------------------------------------
  fdp init-db                           Create fdp schema + manifest table in PostgreSQL
  fdp load-pg [--geo vtd] [--replace]   Load registered parquets into PostgreSQL tables

Dataset registry (PostgreSQL-backed)
--------------------------------------
  fdp status                            Show all registered datasets
  fdp ingest election --year 2022 --state GA --type general --file path/to.zip --source RDH
  fdp ingest cvap     --year 2024 --state GA --file path/to.zip --source Census
  fdp aggregate election --year 2022 --state GA [--vtd-zip path/to/ga_pl2020_vtd.zip]
  fdp aggregate cvap     --year 2024 --state GA
  fdp export-alarm --state GA [--out path/to/vtd_combined.parquet]
  fdp export-race  --year 2022 --state GA --race governor
  fdp delete <dataset-id>

Workspace / repo management
----------------------------
  fdp workspace create <name> [--base main] [--desc "..."]
  fdp workspace list
  fdp workspace delete <name>

Catalog / validation
---------------------
  fdp catalog [--app <app>] [--repo <repo>]
  fdp validate [--app <app>] [--repo <repo>] [--category boundaries]
  fdp sync-app <app> --dest <dir>
  fdp export-cdm [--db path] [--repo main]

All manifest commands read DATABASE_URL from the environment:
  export DATABASE_URL=postgresql://fdp:password@localhost:5432/fdp
"""

from __future__ import annotations

import shutil
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()


def _make_platform(app, repo, fdp_root):
    from fdp.platform import DataPlatform
    return DataPlatform(app=app or None, repo=repo or None, fdp_root=fdp_root or None)


# ---------------------------------------------------------------------------
# Root command
# ---------------------------------------------------------------------------

@click.group()
def main():
    """Fair Districts Data Platform CLI."""


# ---------------------------------------------------------------------------
# workspace subcommands
# ---------------------------------------------------------------------------

@main.group()
def workspace():
    """Manage data workspaces."""


@workspace.command("create")
@click.argument("name")
@click.option("--base", default="main", show_default=True, help="Base repo to inherit from")
@click.option("--desc", default="", help="Short description")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def workspace_create(name, base, desc, fdp_root):
    """Create a new private workspace named NAME."""
    p = _make_platform(None, None, fdp_root)
    ws = p.registry.create_workspace(name, base=base, description=desc)
    console.print(f"[green]Created workspace[/] '{name}' at {ws.path}")
    console.print(f"  Base repo : {base}")
    console.print(f"  Activate  : export FDP_WORKSPACE={name}")


@workspace.command("list")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def workspace_list(fdp_root):
    """List all workspaces."""
    p = _make_platform(None, None, fdp_root)
    workspaces = p.registry.list_workspaces()
    if not workspaces:
        console.print("[yellow]No workspaces found.[/]")
        return
    table = Table(title="Workspaces", show_header=True)
    table.add_column("Name", style="cyan")
    table.add_column("Base Repo")
    table.add_column("Description")
    table.add_column("Path")
    for ws in workspaces:
        meta_file = ws.path / "workspace.yml"
        desc = ws.description
        table.add_row(ws.name, ws.base_repo or "", desc, str(ws.path))
    console.print(table)


@workspace.command("delete")
@click.argument("name")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def workspace_delete(name, yes, fdp_root):
    """Delete workspace NAME and all its files."""
    p = _make_platform(None, None, fdp_root)
    ws = p.registry.get(name)
    if not ws.is_workspace:
        console.print(f"[red]'{name}' is a regular repo — cannot delete via CLI.[/]")
        raise SystemExit(1)
    if not yes:
        click.confirm(f"Delete workspace '{name}' at {ws.path}?", abort=True)
    p.registry.delete_workspace(name)
    console.print(f"[green]Deleted workspace[/] '{name}'")


# ---------------------------------------------------------------------------
# catalog command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--app", default=None, help="App name (fdex, fdga_chain, lrdb, map_compare)")
@click.option("--repo", default=None, help="Repo or workspace name")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def catalog(app, repo, fdp_root):
    """Show data catalog for a repo or workspace."""
    p = _make_platform(app, repo, fdp_root)
    p.catalog.print_summary()


# ---------------------------------------------------------------------------
# validate command
# ---------------------------------------------------------------------------

@main.command()
@click.option("--app", default=None)
@click.option("--repo", default=None)
@click.option("--category", default=None, help="Only validate this category (e.g. boundaries)")
@click.option("--halt/--no-halt", default=False, help="Exit on first error")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def validate(app, repo, category, halt, fdp_root):
    """Run data quality checks against all files in a repo."""
    from fdp.platform import DataPlatform
    p = DataPlatform(app=app, repo=repo, fdp_root=fdp_root, halt_on_error=halt)
    entries = p.catalog.list(category=category)

    if not entries:
        console.print("[yellow]No files found to validate.[/]")
        return

    error_count = 0
    for entry in entries:
        try:
            if entry.category == "boundaries":
                gdf = p.boundaries.load(entry.rel_path)
                from fdp.quality.checks import QualityReport, check_crs, check_geometry_validity
                report = QualityReport()
                check_crs(gdf, report)
                check_geometry_validity(gdf, report)
            elif entry.category == "precincts":
                gdf = p.precincts.load(entry.rel_path)
                report = gdf  # validate already ran
            else:
                console.print(f"[dim]  skip  {entry.rel_path}[/]")
                continue

            if hasattr(report, 'has_errors'):
                status = "[red]FAIL[/]" if report.has_errors else "[green]OK[/]"
                console.print(f"  {status}  {entry.rel_path}")
                if report.has_errors:
                    error_count += 1
                    console.print(f"         [red]{report.summary}[/]")
                elif report.has_warnings:
                    console.print(f"         [yellow]{report.summary}[/]")
        except FileNotFoundError:
            pass  # workspace fallback already handled

    if error_count:
        console.print(f"\n[red]{error_count} file(s) failed validation.[/]")
        raise SystemExit(1)
    else:
        console.print("\n[green]All checks passed.[/]")


# ---------------------------------------------------------------------------
# sync-app command
# ---------------------------------------------------------------------------

@main.command("sync-app")
@click.argument("app")
@click.option("--dest", required=True, help="Destination directory (app's data folder)")
@click.option("--repo", default=None)
@click.option("--dry-run", is_flag=True)
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def sync_app(app, dest, repo, dry_run, fdp_root):
    """
    Copy the data files needed by APP into DEST.

    Reads the app's config plan entries and reference layers, resolves each
    file from the active repo (workspace-aware), and copies to DEST.

    Example::

        fdp sync-app fdex --dest ~/codebox/fdex/public/data
    """
    p = _make_platform(app, repo, fdp_root)
    cfg = p.config
    dest_path = Path(dest)
    dest_path.mkdir(parents=True, exist_ok=True)

    to_copy: list[tuple[Path, Path]] = []  # (src, dst)
    seen: set[str] = set()

    def _add(rel: str) -> None:
        if not rel or rel in seen:
            return
        seen.add(rel)
        try:
            src = p.resolve(rel)
            if src.is_file():
                to_copy.append((src, dest_path / src.name))
        except FileNotFoundError:
            console.print(f"[yellow]  MISSING  {rel}[/]")

    def _walk(value, skip_keys: set[str] | None = None) -> None:
        """Recursively collect file-path strings from any config section."""
        if isinstance(value, dict):
            for k, v in value.items():
                if skip_keys and k in skip_keys:
                    continue
                _walk(v)
        elif isinstance(value, list):
            for item in value:
                _walk(item)
        elif isinstance(value, str) and ("/" in value or Path(value).suffix):
            _add(value)

    # Keys that reference generated output dirs, not FDP inputs — skip them.
    _OUTPUT_KEYS = {"graphs_dir", "ensembles_dir", "precinct_source"}

    # Collect plan files
    for chamber, plans in (cfg.get("plans") or {}).items():
        for plan in plans:
            _add(plan.get("file", ""))

    # Collect reference layers and demographics (legacy explicit sections)
    _walk(cfg.get("reference_layers") or {})
    _walk(cfg.get("demographics") or {})

    # Collect everything under the generic data: section
    _walk(cfg.get("data") or {}, skip_keys=_OUTPUT_KEYS)

    if dry_run:
        console.print(f"[cyan]Dry run — {len(to_copy)} file(s) would be copied to {dest_path}[/]")
        for src, dst in to_copy:
            console.print(f"  {src.name}")
        return

    for src, dst in to_copy:
        shutil.copy2(src, dst)
        console.print(f"  [green]copied[/]  {src.name}")

    console.print(f"\n[green]{len(to_copy)} file(s) synced to {dest_path}[/]")


# ---------------------------------------------------------------------------
# export-cdm command
# ---------------------------------------------------------------------------

@main.command("export-cdm")
@click.option("--db", default=None, help="Output DuckDB file (default: data/cdm.duckdb)")
@click.option("--repo", default="main", show_default=True, help="Repo to catalogue")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def export_cdm(db, repo, fdp_root):
    """
    Export the Common Data Model to a DuckDB file for inspection in DBeaver.

    Creates tables: cdm_redistricting_waves, cdm_wave_chambers,
    cdm_boundary_catalog, cdm_plan_catalog, cdm_schema_contracts,
    cdm_displacement_metrics.

    Re-run after adding boundary files or running displacement analysis to
    keep the database in sync.
    """
    import subprocess, sys
    script = Path(__file__).parent.parent / "scripts" / "export_cdm.py"
    args = [sys.executable, str(script)]
    if db:
        args += ["--db", db]
    if repo:
        args += ["--repo", repo]
    subprocess.run(args, check=True)


# ---------------------------------------------------------------------------
# Manifest helpers
# ---------------------------------------------------------------------------

def _make_manifest(db_url: str | None = None):
    """
    Return a DataManifest connected to PostgreSQL.

    Reads DATABASE_URL from the environment if db_url is not supplied.
    Exits with a clean error message if no connection string is available.
    """
    from fdp.manifest import DataManifest
    try:
        return DataManifest(db_url=db_url)
    except RuntimeError as exc:
        console.print(f"[red]Database connection error:[/] {exc}")
        raise SystemExit(1)


def _dtype_to_pg(dtype) -> str:
    """Map a pandas/numpy dtype to a PostgreSQL column type."""
    import pandas as pd
    if pd.api.types.is_bool_dtype(dtype):
        return "BOOLEAN"
    elif pd.api.types.is_integer_dtype(dtype):
        return "BIGINT"
    elif pd.api.types.is_float_dtype(dtype):
        return "DOUBLE PRECISION"
    elif pd.api.types.is_datetime64_any_dtype(dtype):
        return "TIMESTAMPTZ"
    else:
        return "TEXT"


def _fdp_root(fdp_root=None) -> Path:
    import os
    return Path(fdp_root or os.environ.get("FDP_ROOT", str(Path(__file__).parent.parent)))


def _data_root(fdp_root=None) -> Path:
    return _fdp_root(fdp_root) / "data" / "repos" / "main"


def _raw_root(fdp_root=None) -> Path:
    """Root directory for raw source files (original uploaded files, gitignored)."""
    return _fdp_root(fdp_root) / "data" / "raw"


def _copy_to_raw(src: Path, category: str, fdp_root=None) -> Path:
    """
    Copy a raw source file to data/raw/{category}/ preserving original filename.

    Returns the path of the copy.
    """
    dest_dir = _raw_root(fdp_root) / category
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / src.name
    if not dest.exists():
        import shutil
        shutil.copy2(src, dest)
    return dest


# ---------------------------------------------------------------------------
# fdp status
# ---------------------------------------------------------------------------

@main.command("status")
@click.option("--state", default=None, help="Filter by state (e.g. GA)")
@click.option("--category", default=None, help="Filter by category (election, cvap, …)")
@click.option("--geo", default=None, help="Filter by geography (block, vtd, …)")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def status(state, category, geo, fdp_root):
    """Show all registered datasets in the manifest."""
    manifest = _make_manifest()
    entries = manifest.list(state=state, category=category, geography=geo)

    if not entries:
        console.print("[yellow]No datasets registered yet.  Run 'fdp ingest' to add data.[/]")
        return

    table = Table(title=f"FDP Dataset Manifest — {len(entries)} dataset(s)", show_header=True)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Category")
    table.add_column("Geo")
    table.add_column("Vintage", justify="right")
    table.add_column("Type")
    table.add_column("Source")
    table.add_column("Rows", justify="right")
    table.add_column("On disk", justify="center")
    table.add_column("Loaded")

    for e in entries:
        on_disk = "[green]✓[/]" if e.exists else "[red]✗[/]"
        loaded = e.loaded_at[:10] if e.loaded_at else ""
        table.add_row(
            e.id,
            e.category,
            e.geography,
            str(e.vintage) if e.vintage else "",
            e.election_type or "",
            e.source or "(derived)",
            f"{e.row_count:,}" if e.row_count else "",
            on_disk,
            loaded,
        )

    console.print(table)
    console.print(f"\n  Manifest: {manifest.db_path}")


# ---------------------------------------------------------------------------
# fdp delete
# ---------------------------------------------------------------------------

@main.command("delete")
@click.argument("dataset_id")
@click.option("--yes", is_flag=True, help="Skip confirmation prompt")
@click.option("--remove-file", is_flag=True, help="Also delete the output file from disk")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def delete_dataset(dataset_id, yes, remove_file, fdp_root):
    """Remove a dataset from the manifest (and optionally its output file)."""
    manifest = _make_manifest()
    entry = manifest.get(dataset_id)
    if entry is None:
        console.print(f"[red]Dataset '{dataset_id}' not found in manifest.[/]")
        raise SystemExit(1)

    msg = f"Delete manifest entry '{dataset_id}'"
    if remove_file and entry.exists:
        msg += f" and output file {entry.output_file}"
    if not yes:
        click.confirm(msg + "?", abort=True)

    if remove_file and entry.exists:
        Path(entry.output_file).unlink()
        console.print(f"  [red]deleted[/] {entry.output_file}")

    manifest.delete(dataset_id)
    console.print(f"[green]Removed[/] '{dataset_id}' from manifest.")


# ---------------------------------------------------------------------------
# fdp ingest
# ---------------------------------------------------------------------------

@main.group("ingest")
def ingest():
    """Ingest a raw source file into the FDP data store."""


@ingest.command("election")
@click.option("--year",  required=True, type=int,  help="Election year (e.g. 2022)")
@click.option("--state", default="GA", show_default=True)
@click.option("--type",  "election_type", default="general",
              type=click.Choice(["general", "runoff", "special", "primary"]),
              show_default=True)
@click.option("--file",  "raw_file", required=True,
              help="Path to the RDH block-level election zip")
@click.option("--source", default="RDH", show_default=True,
              help="Data provider label (RDH, VEST, …)")
@click.option("--source-url", default=None, help="URL where file was downloaded from")
@click.option("--copy-raw", is_flag=True, default=False,
              help="Copy the raw file to data/raw/elections/ (recommended for provenance)")
@click.option("--out",  "out_path", default=None,
              help="Output parquet path (default: data/repos/main/block/<canonical-name>.parquet)")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def ingest_election(year, state, election_type, raw_file, source, source_url, copy_raw, out_path, fdp_root):
    """
    Ingest an RDH block-level election shapefile zip.

    Extracts election columns (no geometry), writes a compact parquet with a
    canonical filename, and registers the dataset in the manifest.

    Canonical filename pattern:  {state}-{year}-{type}-election-block.parquet
    Example:                     ga-2022-general-election-block.parquet

    Use --copy-raw to archive the original zip to data/raw/elections/ so the
    manifest has a permanent provenance pointer independent of wherever you
    originally downloaded the file.

    Example:
        fdp ingest election --year 2022 --state GA --copy-raw \\
            --file ~/codebox/fgdp/fdensemble/input_data/"Copy of ga_2022_gen_2020_blocks.zip"
    """
    from fdp.ingest.elections import ingest_election_zip
    from fdp.ingest.race_registry import races_present
    from fdp.manifest import DatasetEntry, auto_id, canonical_filename, file_checksum

    raw_path = Path(raw_file).expanduser().resolve()
    if not raw_path.exists():
        console.print(f"[red]File not found:[/] {raw_path}")
        raise SystemExit(1)

    dataset_id = auto_id(state, "election", year, election_type, "block")
    fname = canonical_filename(state, "election", year, election_type, "block")

    # Default output path uses canonical filename
    if out_path is None:
        out_path = _data_root(fdp_root) / "block" / fname
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Ingesting election data[/]")
    console.print(f"  Source  : {raw_path.name}")
    console.print(f"  Dataset : {dataset_id}")
    console.print(f"  Output  : {fname}\n")

    def log(msg): console.print(msg)

    df, election_cols = ingest_election_zip(
        raw_path, year=year, election_type=election_type, log_fn=log
    )

    # Show what races are present
    races = races_present(election_cols, year=year)
    candidate_races = {k: v for k, v in races.items() if k != "amendments"}
    amendments = races.get("amendments", [])
    console.print(f"\n  Races found: {', '.join(sorted(candidate_races)) or 'none detected'}")
    if amendments:
        console.print(f"  Amendments:  {len(amendments)} ballot measure columns (included)")

    df.to_parquet(out_path, index=False)
    console.print(f"  [green]✓[/] Written {len(df):,} blocks → {fname}")

    # Optionally copy raw file to data/raw/elections/
    provenance_path = raw_path
    if copy_raw:
        provenance_path = _copy_to_raw(raw_path, "elections", fdp_root)
        console.print(f"  [green]✓[/] Raw file archived → data/raw/elections/{raw_path.name}")

    console.print("  Computing checksum…")
    checksum = file_checksum(raw_path)

    manifest = _make_manifest()
    manifest.register(DatasetEntry(
        id=dataset_id,
        category="election",
        geography="block",
        vintage=year,
        state=state,
        source=source,
        source_url=source_url,
        election_type=election_type,
        raw_file=str(provenance_path),
        output_file=str(out_path),
        row_count=len(df),
        columns=list(df.columns),
        checksum=checksum,
        notes=f"Races: {', '.join(sorted(candidate_races))}",
    ))
    console.print(f"  [green]✓[/] Registered as '{dataset_id}'")
    console.print(f"\nNext step:  fdp aggregate election --year {year} --state {state}")


@ingest.command("cvap")
@click.option("--year",  required=True, type=int,  help="ACS end year (e.g. 2024)")
@click.option("--state", default="GA", show_default=True)
@click.option("--file",  "raw_file", required=True,
              help="Path to the RDH block-level CVAP CSV zip")
@click.option("--source", default="Census", show_default=True)
@click.option("--source-url", default=None)
@click.option("--copy-raw", is_flag=True, default=False,
              help="Copy the raw file to data/raw/cvap/ for provenance")
@click.option("--out",  "out_path", default=None)
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def ingest_cvap(year, state, raw_file, source, source_url, copy_raw, out_path, fdp_root):
    """
    Ingest an RDH block-level CVAP CSV zip.

    Canonical filename pattern:  {state}-{year}-cvap-block.parquet
    Example:                     ga-2024-cvap-block.parquet

    Example:
        fdp ingest cvap --year 2024 --state GA --copy-raw \\
            --file ~/codebox/fgdp/fdensemble/input_data/ga_cvap_2024_2020_b_csv.zip
    """
    from fdp.ingest.cvap import ingest_cvap_zip
    from fdp.manifest import DatasetEntry, auto_id, canonical_filename, file_checksum

    raw_path = Path(raw_file).expanduser().resolve()
    if not raw_path.exists():
        console.print(f"[red]File not found:[/] {raw_path}")
        raise SystemExit(1)

    dataset_id = auto_id(state, "cvap", year, None, "block")
    fname = canonical_filename(state, "cvap", year, None, "block")

    if out_path is None:
        out_path = _data_root(fdp_root) / "block" / fname
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Ingesting CVAP data[/]")
    console.print(f"  Source  : {raw_path.name}")
    console.print(f"  Dataset : {dataset_id}")
    console.print(f"  Output  : {fname}\n")

    def log(msg): console.print(msg)

    df, cvap_cols = ingest_cvap_zip(raw_path, year=year, log_fn=log)

    df.to_parquet(out_path, index=False)
    console.print(f"\n  [green]✓[/] Written {len(df):,} blocks → {fname}")

    provenance_path = raw_path
    if copy_raw:
        provenance_path = _copy_to_raw(raw_path, "cvap", fdp_root)
        console.print(f"  [green]✓[/] Raw file archived → data/raw/cvap/{raw_path.name}")

    checksum = file_checksum(raw_path)

    manifest = _make_manifest()
    manifest.register(DatasetEntry(
        id=dataset_id,
        category="cvap",
        geography="block",
        vintage=year,
        state=state,
        source=source,
        source_url=source_url,
        raw_file=str(provenance_path),
        output_file=str(out_path),
        row_count=len(df),
        columns=list(df.columns),
        checksum=checksum,
        notes=f"ACS {year-4}–{year} 5-year CVAP, RDH block disaggregation",
    ))
    console.print(f"  [green]✓[/] Registered as '{dataset_id}'")
    console.print(f"\nNext step:  fdp aggregate cvap --year {year} --state {state}")


# ---------------------------------------------------------------------------
# fdp aggregate
# ---------------------------------------------------------------------------

@main.group("aggregate")
def aggregate():
    """Aggregate a block-level dataset to VTD level."""


def _get_or_build_lookup(
    manifest,
    state: str,
    vtd_zip: str | None,
    data_root: Path,
    log_fn,
) -> "pd.DataFrame":
    """Load an existing block→VTD lookup from manifest, or build it fresh."""
    import pandas as pd
    from fdp.manifest import DatasetEntry, auto_id

    lookup_id = f"{state.lower()}_block_vtd_lookup_2020"
    entry = manifest.get(lookup_id)

    if entry and entry.exists:
        log_fn(f"  Loading cached lookup from {entry.output_file}")
        return pd.read_parquet(entry.output_file)

    # Need to build it — vtd_zip is required
    if not vtd_zip:
        # Try to find a block-level election entry that has the raw file with geometry
        block_entries = manifest.list(state=state, category="election", geography="block")
        if not block_entries:
            console.print(
                "[red]No block→VTD lookup cached and no blocks shapefile available.[/]\n"
                "Provide --vtd-zip and ensure a block-level election was previously ingested."
            )
            raise SystemExit(1)
        raw_blocks = Path(block_entries[0].raw_file)
        console.print(f"  [dim]Using {raw_blocks.name} for block geometry[/]")
    else:
        # Find the raw blocks file from manifest
        block_entries = manifest.list(state=state, category="election", geography="block")
        raw_blocks = Path(block_entries[0].raw_file) if block_entries else None

    vtd_zip_path = Path(vtd_zip).expanduser().resolve() if vtd_zip else None
    if vtd_zip_path is None or not vtd_zip_path.exists():
        console.print(f"[red]VTD reference zip not found:[/] {vtd_zip}")
        raise SystemExit(1)

    from fdp.transforms.block_to_vtd import build_lookup
    lookup_path = data_root / "lookups" / f"{lookup_id}.parquet"
    lookup_path.parent.mkdir(parents=True, exist_ok=True)

    log_fn(f"  Building block→VTD lookup (first run, ~3-5 min)…")
    lookup = build_lookup(
        vtd_zip=vtd_zip_path,
        blocks_zip=raw_blocks,
        output_path=lookup_path,
        log_fn=log_fn,
    )

    from fdp.manifest import DatasetEntry
    manifest.register(DatasetEntry(
        id=lookup_id,
        category="lookup",
        geography="block",
        state=state,
        vintage=2020,
        source="derived",
        output_file=str(lookup_path),
        row_count=len(lookup),
        columns=list(lookup.columns),
        derived_from=[block_entries[0].id if block_entries else ""],
        notes="Block→VTD spatial join cache (centroid-in-polygon, UTM 16N)",
    ))
    log_fn(f"  [green]✓[/] Lookup cached → {lookup_path}")
    return lookup


@aggregate.command("election")
@click.option("--year",  required=True, type=int)
@click.option("--state", default="GA", show_default=True)
@click.option("--type",  "election_type", default="general",
              type=click.Choice(["general", "runoff", "special", "primary"]),
              show_default=True)
@click.option("--vtd-zip", default=None,
              help="Path to VTD reference zip (required only on first aggregate call)")
@click.option("--out", "out_path", default=None,
              help="Output parquet path (default: data/repos/main/vtd/<id>.parquet)")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def aggregate_election(year, state, election_type, vtd_zip, out_path, fdp_root):
    """
    Aggregate block-level election data to VTD level.

    Requires a prior 'fdp ingest election' for the same year/state/type.
    Builds the block→VTD lookup on first call (cached for subsequent runs).

    Example:
        fdp aggregate election --year 2022 --state GA \\
            --vtd-zip ~/codebox/fgdp/fdensemble/input_data/ga_pl2020_vtd.zip
    """
    import pandas as pd
    from fdp.manifest import DatasetEntry, auto_id, canonical_filename
    from fdp.transforms.block_to_vtd import aggregate_to_vtd

    manifest = _make_manifest()
    data_root = _data_root(fdp_root)

    block_id = auto_id(state, "election", year, election_type, "block")
    vtd_id   = auto_id(state, "election", year, election_type, "vtd")

    block_entry = manifest.get(block_id)
    if block_entry is None:
        console.print(f"[red]Block-level election not found in manifest: {block_id}[/]")
        console.print(f"Run:  fdp ingest election --year {year} --state {state} --type {election_type} --file <zip>")
        raise SystemExit(1)

    if out_path is None:
        fname = canonical_filename(state, "election", year, election_type, "vtd")
        out_path = data_root / "vtd" / fname
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Aggregating election → VTD[/]")
    console.print(f"  Source  : {block_id}  ({block_entry.row_count:,} blocks)")
    console.print(f"  Output  : {vtd_id}\n")

    def log(msg): console.print(msg)

    lookup = _get_or_build_lookup(manifest, state, vtd_zip, data_root, log)

    blocks_df = pd.read_parquet(block_entry.output_file)
    value_cols = [c for c in blocks_df.columns if c != "GEOID20"]

    console.print(f"  Aggregating {len(blocks_df):,} blocks → VTDs…")
    vtd_df = aggregate_to_vtd(blocks_df, lookup, value_cols)

    vtd_df.to_parquet(out_path, index=False)
    console.print(f"  [green]✓[/] {len(vtd_df):,} VTDs × {len(vtd_df.columns)} cols → {out_path.name}")

    manifest.register(DatasetEntry(
        id=vtd_id,
        category="election",
        geography="vtd",
        vintage=year,
        state=state,
        source="derived",
        election_type=election_type,
        output_file=str(out_path),
        row_count=len(vtd_df),
        columns=list(vtd_df.columns),
        derived_from=[block_id],
        notes=f"Block→VTD aggregation of {block_id}",
    ))
    console.print(f"  [green]✓[/] Registered as '{vtd_id}'")


@aggregate.command("cvap")
@click.option("--year",  required=True, type=int)
@click.option("--state", default="GA", show_default=True)
@click.option("--vtd-zip", default=None,
              help="Path to VTD reference zip (required only on first aggregate call)")
@click.option("--out", "out_path", default=None)
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def aggregate_cvap(year, state, vtd_zip, out_path, fdp_root):
    """
    Aggregate block-level CVAP data to VTD level.

    Requires a prior 'fdp ingest cvap' for the same year/state.

    Example:
        fdp aggregate cvap --year 2024 --state GA
    """
    import pandas as pd
    from fdp.manifest import DatasetEntry, auto_id, canonical_filename
    from fdp.transforms.block_to_vtd import aggregate_to_vtd

    manifest = _make_manifest()
    data_root = _data_root(fdp_root)

    block_id = auto_id(state, "cvap", year, None, "block")
    vtd_id   = auto_id(state, "cvap", year, None, "vtd")

    block_entry = manifest.get(block_id)
    if block_entry is None:
        console.print(f"[red]Block-level CVAP not found: {block_id}[/]")
        console.print(f"Run:  fdp ingest cvap --year {year} --state {state} --file <zip>")
        raise SystemExit(1)

    if out_path is None:
        fname = canonical_filename(state, "cvap", year, None, "vtd")
        out_path = data_root / "vtd" / fname
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    console.print(f"\n[bold]Aggregating CVAP → VTD[/]")
    console.print(f"  Source  : {block_id}  ({block_entry.row_count:,} blocks)")
    console.print(f"  Output  : {vtd_id}\n")

    def log(msg): console.print(msg)

    lookup = _get_or_build_lookup(manifest, state, vtd_zip, data_root, log)

    blocks_df = pd.read_parquet(block_entry.output_file)
    value_cols = [c for c in blocks_df.columns if c != "GEOID20"]

    console.print(f"  Aggregating {len(blocks_df):,} blocks → VTDs…")
    vtd_df = aggregate_to_vtd(blocks_df, lookup, value_cols)

    vtd_df.to_parquet(out_path, index=False)
    console.print(f"  [green]✓[/] {len(vtd_df):,} VTDs × {len(vtd_df.columns)} cols → {out_path.name}")

    manifest.register(DatasetEntry(
        id=vtd_id,
        category="cvap",
        geography="vtd",
        vintage=year,
        state=state,
        source="derived",
        output_file=str(out_path),
        row_count=len(vtd_df),
        columns=list(vtd_df.columns),
        derived_from=[block_id],
        notes=f"Block→VTD aggregation of {block_id}",
    ))
    console.print(f"  [green]✓[/] Registered as '{vtd_id}'")


# ---------------------------------------------------------------------------
# fdp export alarm
# ---------------------------------------------------------------------------

@main.command("export-alarm")
@click.option("--state", default="GA", show_default=True)
@click.option("--out", "out_path", default=None,
              help="Output path (default: data/repos/main/vtd/<state>_alarm_combined.parquet)")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def export_alarm(state, out_path, fdp_root):
    """
    Join all VTD-level election and CVAP datasets into one ALARM-ready parquet.

    The output joins on GEOID20 (11-char VTD identifier) — ready to left_join
    onto GA_cd_2020_map in R:

        vtd <- read_parquet("ga_alarm_combined.parquet")
        map_data <- left_join(GA_cd_2020_map, vtd, by = c("GEOID" = "GEOID20"))

    Example:
        fdp export-alarm --state GA \\
            --out ~/codebox/fgdp/fdensemble/output/vtd/vtd_combined.parquet
    """
    from fdp.exports.alarm import build_combined
    from fdp.manifest import DatasetEntry, auto_id

    manifest = _make_manifest()
    data_root = _data_root(fdp_root)

    # Find all VTD-level election and CVAP entries for this state
    vtd_entries = manifest.list(state=state, geography="vtd")
    vtd_entries = [e for e in vtd_entries if e.category in ("election", "cvap")]

    if not vtd_entries:
        console.print(
            f"[red]No VTD-level datasets found for state={state}.[/]\n"
            "Run 'fdp aggregate election/cvap' first."
        )
        raise SystemExit(1)

    console.print(f"\n[bold]Building ALARM combined VTD parquet[/]")
    console.print(f"  State   : {state}")
    console.print(f"  Sources : {len(vtd_entries)} VTD datasets")
    for e in vtd_entries:
        tag = f"{e.vintage} {e.election_type or ''} {e.category}".strip()
        on_disk = "[green]✓[/]" if e.exists else "[red]missing[/]"
        console.print(f"    {on_disk}  {e.id}  ({tag})")

    missing = [e for e in vtd_entries if not e.exists]
    if missing:
        console.print(f"\n[red]{len(missing)} dataset(s) missing from disk — run aggregation first.[/]")
        raise SystemExit(1)

    if out_path is None:
        out_path = data_root / "vtd" / f"{state.lower()}-alarm-combined-vtd.parquet"
    out_path = Path(out_path)

    def log(msg): console.print(msg)

    combined_id = f"{state.lower()}_alarm_combined"
    combined_df = build_combined(
        vtd_parquets=[Path(e.output_file) for e in vtd_entries],
        output_path=out_path,
        log_fn=log,
    )

    manifest.register(DatasetEntry(
        id=combined_id,
        category="alarm_combined",
        geography="vtd",
        state=state,
        source="derived",
        output_file=str(out_path),
        row_count=len(combined_df),
        columns=list(combined_df.columns),
        derived_from=[e.id for e in vtd_entries],
        notes="Combined ALARM input: all VTD-level elections + CVAP",
    ))
    console.print(f"\n  [green]✓[/] Registered as '{combined_id}'")
    console.print(f"\n[bold green]Done.[/]  R join:")
    console.print(f'  vtd <- read_parquet("{out_path}")')
    console.print('  map_data <- left_join(GA_cd_2020_map, vtd, by = c("GEOID" = "GEOID20"))')


# ---------------------------------------------------------------------------
# fdp export race  — per-race single-topic VTD files
# ---------------------------------------------------------------------------

@main.command("export-race")
@click.option("--year",  required=True, type=int,  help="Election year")
@click.option("--state", default="GA", show_default=True)
@click.option("--race",  required=True,
              help="Race name: governor, senate, president, attorney-general, "
                   "secretary-of-state, lt-governor, cvap")
@click.option("--type",  "election_type", default="general",
              type=click.Choice(["general", "runoff", "special", "primary"]),
              show_default=True)
@click.option("--out", "out_path", default=None,
              help="Output path (default: data/repos/main/vtd/<canonical>.parquet)")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def export_race(year, state, race, election_type, out_path, fdp_root):
    """
    Export a single-race VTD parquet for a specific election year.

    Extracts only the columns for the requested race from the combined
    VTD election parquet, producing a focused, discoverable file.

    Canonical filename pattern:  {state}-{year}-{race}-vtd.parquet
    Examples:
        ga-2022-governor-vtd.parquet
        ga-2024-president-vtd.parquet
        ga-2022-senate-vtd.parquet

    Usage:
        fdp export-race --year 2022 --state GA --race governor
        fdp export-race --year 2024 --state GA --race president
    """
    import pandas as pd
    from fdp.ingest.race_registry import cols_for_race, races_present, _NAME_TO_CODE
    from fdp.manifest import DatasetEntry, auto_id, canonical_filename

    manifest = _make_manifest()
    data_root = _data_root(fdp_root)

    # Handle cvap as a special case
    if race.lower() == "cvap":
        vtd_id = auto_id(state, "cvap", year, None, "vtd")
        entry = manifest.get(vtd_id)
        if entry is None or not entry.exists:
            console.print(f"[red]CVAP VTD not found: {vtd_id}[/]  Run: fdp aggregate cvap --year {year}")
            raise SystemExit(1)
        src_df = pd.read_parquet(entry.output_file)
        race_cols = [c for c in src_df.columns if c != "GEOID20"]
    else:
        vtd_id = auto_id(state, "election", year, election_type, "vtd")
        entry = manifest.get(vtd_id)
        if entry is None or not entry.exists:
            console.print(f"[red]Election VTD not found: {vtd_id}[/]  Run: fdp aggregate election --year {year}")
            raise SystemExit(1)
        src_df = pd.read_parquet(entry.output_file)

        # Find columns for this race
        race_cols = cols_for_race(race, list(src_df.columns), year=year)
        if not race_cols:
            present = races_present(list(src_df.columns), year=year)
            console.print(f"[red]Race '{race}' not found in {vtd_id}[/]")
            console.print(f"  Available races: {', '.join(k for k in present if k != 'amendments')}")
            raise SystemExit(1)

    # Build output
    out_df = src_df[["GEOID20"] + race_cols].copy()

    # Add VAP_MOD if present (useful context)
    if "VAP_MOD" in src_df.columns:
        out_df.insert(1, "VAP_MOD", src_df["VAP_MOD"])

    dataset_id = auto_id(state, "election", year, election_type, "vtd", race=race)
    fname      = canonical_filename(state, "election", year, None, "vtd", race=race)

    if out_path is None:
        out_path = data_root / "vtd" / fname
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    out_df.to_parquet(out_path, index=False)

    console.print(f"\n[bold]Race export[/]: {race} {year} {state} → VTD")
    console.print(f"  Columns : {race_cols}")
    console.print(f"  Rows    : {len(out_df):,} VTDs")
    console.print(f"  File    : {fname}")

    manifest.register(DatasetEntry(
        id=dataset_id,
        category="election",
        geography="vtd",
        vintage=year,
        state=state,
        election_type=election_type,
        source="derived",
        output_file=str(out_path),
        row_count=len(out_df),
        columns=list(out_df.columns),
        derived_from=[vtd_id],
        notes=f"Single-race export: {race}",
    ))
    console.print(f"  [green]✓[/] Registered as '{dataset_id}'")


# ---------------------------------------------------------------------------
# fdp scan — re-discover parquets from disk and register in manifest
# ---------------------------------------------------------------------------

def _parse_canonical_filename(fname: str) -> dict | None:
    """
    Parse a canonical parquet filename into metadata fields.

    Supports patterns produced by canonical_filename():
      ga-2022-general-election-vtd.parquet       → election, type=general
      ga-2024-general-president-election-vtd.parquet → election, race=president
      ga-2022-governor-election-vtd.parquet      → election, race=governor (no type)
      ga-2024-cvap-vtd.parquet                   → cvap
      ga-alarm-combined-vtd.parquet              → alarm_combined

    Returns a dict with keys: state, vintage, category, geography,
    election_type, race  — or None if the filename cannot be parsed.
    """
    from pathlib import Path as _P
    stem = _P(fname).stem   # strip .parquet

    parts = stem.split("-")
    if len(parts) < 3:
        return None

    state = parts[0].upper()
    geo   = parts[-1]

    # Try to parse year from parts[1]; alarm-combined has no year
    try:
        year = int(parts[1])
        middle = parts[2:-1]
    except ValueError:
        year = None
        middle = parts[1:-1]   # e.g. ["alarm", "combined"]

    if not middle:
        return None

    middle_str = "-".join(middle)

    _ELECTION_TYPES = {"general", "runoff", "special", "primary"}

    if middle_str == "cvap":
        return dict(state=state, vintage=year, category="cvap",
                    geography=geo, election_type=None, race=None)

    if middle_str == "alarm-combined":
        return dict(state=state, vintage=None, category="alarm_combined",
                    geography=geo, election_type=None, race=None)

    if middle[-1] == "election":
        qualifiers = middle[:-1]   # everything before "election"
        if not qualifiers:
            return dict(state=state, vintage=year, category="election",
                        geography=geo, election_type=None, race=None)
        if len(qualifiers) == 1:
            q = qualifiers[0]
            if q in _ELECTION_TYPES:
                return dict(state=state, vintage=year, category="election",
                            geography=geo, election_type=q, race=None)
            else:
                return dict(state=state, vintage=year, category="election",
                            geography=geo, election_type=None, race=q)
        if len(qualifiers) == 2:
            # election_type + race, e.g. ["general", "president"]
            etype, race = qualifiers
            if etype in _ELECTION_TYPES:
                return dict(state=state, vintage=year, category="election",
                            geography=geo, election_type=etype, race=race)
        return None

    return None


@main.command("scan")
@click.option("--state", default=None, help="Only scan a specific state (e.g. GA)")
@click.option("--dry-run", is_flag=True,
              help="Show what would be registered without writing anything")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def scan(state, dry_run, fdp_root):
    """
    Scan data/repos/main/ for existing parquets and register them in the manifest.

    Useful after migrating from DuckDB or when setting up a new environment
    where parquet files already exist but the PostgreSQL manifest is empty.

    Parses canonical filenames to infer metadata (state, year, category, geo,
    election type, race).  Reads each parquet for row count and column names.
    Skips files that are already registered unless --dry-run is given.

    Example:
        fdp scan               # register everything found
        fdp scan --dry-run     # preview without writing
        fdp scan --state GA    # only GA files
    """
    import pandas as pd
    from fdp.manifest import DatasetEntry, auto_id

    data_root = _data_root(fdp_root)
    manifest  = _make_manifest()

    # Directories and geo labels to scan
    scan_dirs = [
        (data_root / "vtd",   "vtd"),
        (data_root / "block", "block"),
        (data_root / "lookups", "lookups"),
    ]

    registered = 0
    skipped    = 0
    failed     = 0

    for scan_dir, geo_hint in scan_dirs:
        if not scan_dir.exists():
            continue
        parquets = sorted(scan_dir.glob("*.parquet"))
        if not parquets:
            continue

        console.print(f"\n[bold]Scanning {scan_dir.relative_to(data_root.parent.parent)}/[/]")

        for pq in parquets:
            # --- Special case: lookup cache (uses underscores, not hyphens) ---
            if geo_hint == "lookups":
                # Filename pattern: {state}_block_vtd_lookup_{year}.parquet
                parts = pq.stem.split("_")
                if len(parts) >= 5 and parts[1] == "block" and parts[2] == "vtd":
                    s = parts[0].upper()
                    if state and s != state.upper():
                        continue
                    try:
                        yr = int(parts[-1])
                    except ValueError:
                        yr = 2020
                    dataset_id = f"{s.lower()}_block_vtd_lookup_{yr}"
                    meta = dict(state=s, vintage=yr, category="lookup",
                                geography="block", election_type=None, race=None)
                else:
                    console.print(f"  [dim]skip  {pq.name}  (unrecognised lookup name)[/]")
                    failed += 1
                    continue
            else:
                meta = _parse_canonical_filename(pq.name)
                if meta is None:
                    console.print(f"  [yellow]skip  {pq.name}  (cannot parse filename)[/]")
                    failed += 1
                    continue
                if state and meta["state"] != state.upper():
                    continue
                dataset_id = auto_id(
                    meta["state"], meta["category"], meta["vintage"],
                    meta["election_type"], meta["geography"], meta.get("race"),
                )

            # Check if already registered
            existing = manifest.get(dataset_id)
            if existing is not None:
                console.print(f"  [dim]exists {pq.name}  ({dataset_id})[/]")
                skipped += 1
                continue

            # Read parquet for row count + columns
            try:
                df = pd.read_parquet(pq)
                n_rows = len(df)
                cols   = list(df.columns)
            except Exception as exc:
                console.print(f"  [red]error  {pq.name}  ({exc})[/]")
                failed += 1
                continue

            entry = DatasetEntry(
                id=dataset_id,
                category=meta["category"],
                geography=meta["geography"],
                vintage=meta["vintage"],
                state=meta["state"],
                source="derived",
                election_type=meta.get("election_type"),
                output_file=str(pq.resolve()),
                row_count=n_rows,
                columns=cols,
                notes="Re-registered by fdp scan",
            )

            if dry_run:
                console.print(
                    f"  [cyan]would register[/]  {dataset_id}  "
                    f"({n_rows:,} rows, {len(cols)} cols)"
                )
                registered += 1
            else:
                manifest.register(entry)
                console.print(
                    f"  [green]✓[/] {dataset_id}  "
                    f"({n_rows:,} rows, {len(cols)} cols)"
                )
                registered += 1

    action = "would register" if dry_run else "registered"
    console.print(
        f"\n  {action}: [green]{registered}[/]  "
        f"skipped (exists): [dim]{skipped}[/]  "
        f"failed: [{'red' if failed else 'dim'}]{failed}[/]"
    )
    if not dry_run and registered > 0:
        console.print(f"\nNext:  fdp load-pg --geo vtd")


# ---------------------------------------------------------------------------
# fdp init-db — create schema, manifest table, and CDM tables
# ---------------------------------------------------------------------------

@main.command("init-db")
@click.option("--dsn", envvar="DATABASE_URL", default=None,
              help="PostgreSQL connection string (default: $DATABASE_URL)")
def init_db(dsn):
    """
    Create the FDP PostgreSQL schema and all CDM tables.

    Runs every SQL file in the sql/ directory in order:
      001_manifest.sql  — fdp.datasets (manifest registry)
      002_cdm.sql       — fdp.geography, fdp.geo_crosswalk, fdp.population,
                          fdp.election_results, fdp.cvap, fdp.ensemble_plans,
                          audit triggers, and analytical views

    Safe to re-run at any time — all statements are idempotent
    (IF NOT EXISTS / CREATE OR REPLACE).

    Run once when pointing at a new database (local Docker or Supabase):

        export DATABASE_URL=postgresql://fdp:password@localhost:5432/fdp
        fdp init-db
    """
    import os
    import psycopg

    # DataManifest.__init__ creates the fdp schema + datasets table
    manifest = _make_manifest(db_url=dsn)

    db_url = dsn or os.environ.get("DATABASE_URL")
    sql_dir = Path(__file__).parent.parent / "sql"
    sql_files = sorted(sql_dir.glob("*.sql"))

    if not sql_files:
        console.print("[yellow]No SQL files found in sql/[/]")
    else:
        with psycopg.connect(db_url) as conn:
            for sql_file in sql_files:
                sql = sql_file.read_text()
                with conn.cursor() as cur:
                    cur.execute(sql)
                conn.commit()
                console.print(f"  [green]✓[/] {sql_file.name}")

    console.print(f"\n[green]✓[/] All schema migrations applied")
    console.print(f"  Database : {manifest.db_url_display}")
    console.print(f"  Manifest : {len(manifest)} dataset(s) registered")


# ---------------------------------------------------------------------------
# fdp load-pg — populate CDM tables from registered parquets
# ---------------------------------------------------------------------------

@main.command("load-pg")
@click.option("--dsn", envvar="DATABASE_URL", default=None,
              help="PostgreSQL connection string (default: $DATABASE_URL)")
@click.option("--state", default=None, help="Filter by state (e.g. GA)")
@click.option("--year",  default=None, type=int,
              help="Only load a specific election/CVAP year")
@click.option("--vintage", default=None, type=int,
              envvar="FDP_VINTAGE_YEAR",
              help="Boundary vintage year to tag geography rows (default: 2020, "
                   "or $FDP_VINTAGE_YEAR env var)")
@click.option("--replace", is_flag=True,
              help="Overwrite existing rows that share the same primary key")
@click.option("--fdp-root", envvar="FDP_ROOT", default=None)
def load_pg(dsn, state, year, vintage, replace, fdp_root):
    """
    Load registered VTD parquets into the FDP Common Data Model tables.

    Populates three normalized tables in the fdp schema:

      fdp.geography        ← geography register (geoid, geo_level, county_fips, …)
      fdp.election_results ← all election results, long format
                             one row per geoid × year × office × party × candidate
      fdp.cvap             ← CVAP by geoid and ACS year

    All years, races, and geographic levels coexist in the same tables.
    New elections are added with UPSERT so existing data is never lost.

    Use --vintage to set the boundary year tag on geography rows (default 2020).
    This can also be set via the FDP_VINTAGE_YEAR environment variable.

    Requires fdp init-db to have been run first.

    Examples:

        fdp load-pg                          # load everything
        fdp load-pg --state GA --year 2022   # only 2022 GA data
        fdp load-pg --replace                # re-load and overwrite existing rows
        fdp load-pg --vintage 2020           # tag geography rows as 2020 boundaries
    """
    import os
    import pandas as pd
    import psycopg
    from fdp.transforms.pg_loaders import (
        extract_geography_dim,
        melt_election_vtd,
        normalize_cvap_vtd,
        upsert_to_pg,
    )

    manifest    = _make_manifest(db_url=dsn)
    db_url      = dsn or os.environ.get("DATABASE_URL")
    vintage_yr  = vintage or int(os.environ.get("FDP_VINTAGE_YEAR", 2020))
    loaded_by   = "fdp load-pg"

    # Only load VTD-level election and CVAP datasets
    entries = manifest.list(state=state, geography="vtd")
    entries = [
        e for e in entries
        if e.category in ("election", "cvap")
        and e.exists
        and (year is None or e.vintage == year)
    ]

    if not entries:
        console.print(
            "[yellow]No VTD datasets found. "
            "Run 'fdp aggregate election/cvap' first, then 'fdp scan'.[/]"
        )
        return

    console.print(f"\n[bold]Loading {len(entries)} dataset(s) → CDM tables[/]")
    console.print(f"  Database : {manifest.db_url_display}")
    console.print(f"  Vintage  : {vintage_yr}")
    console.print(f"  Replace  : {'yes — overwrite on conflict' if replace else 'no — skip on conflict'}\n")

    geo_total = election_total = cvap_total = 0

    with psycopg.connect(db_url) as conn:
        for entry in entries:
            tag = f"{entry.vintage} {entry.election_type or ''} {entry.category} [{entry.state}]".strip()
            console.print(f"  [cyan]{entry.id}[/]  ({tag})")

            def log(msg, _entry=entry): console.print(msg)  # noqa: E731

            df = pd.read_parquet(entry.output_file)

            # ── Geography dimension (always upsert — idempotent) ──────────────
            geo_df = extract_geography_dim(
                df,
                state=entry.state,
                geo_level="vtd",
                geo_type="census",
                vintage_year=vintage_yr,
                loaded_by=loaded_by,
            )
            n = upsert_to_pg(
                conn, geo_df, "fdp", "geography",
                ["geoid", "vintage_year"],
                log_fn=log,
            )
            geo_total += n
            conn.commit()

            # ── Election results ──────────────────────────────────────────────
            if entry.category == "election":
                long_df = melt_election_vtd(
                    df,
                    state=entry.state,
                    source=entry.source or "derived",
                    geo_level="vtd",
                    collection_geo_level="precinct",
                    loaded_by=loaded_by,
                    log_fn=log,
                )
                if not long_df.empty:
                    n = upsert_to_pg(
                        conn, long_df, "fdp", "election_results",
                        ["geoid", "year", "election_type", "office", "party", "candidate"],
                        replace=replace, log_fn=log,
                    )
                    election_total += n
                    conn.commit()

            # ── CVAP ─────────────────────────────────────────────────────────
            elif entry.category == "cvap":
                cvap_df = normalize_cvap_vtd(
                    df,
                    year=entry.vintage,
                    state=entry.state,
                    source=entry.source or "derived",
                    geo_level="vtd",
                    loaded_by=loaded_by,
                )
                n = upsert_to_pg(
                    conn, cvap_df, "fdp", "cvap",
                    ["geoid", "year"],
                    replace=replace, log_fn=log,
                )
                cvap_total += n
                conn.commit()

    console.print(f"\n[bold green]Done.[/]")
    console.print(f"  fdp.geography        : {geo_total:,} rows upserted")
    console.print(f"  fdp.election_results : {election_total:,} rows upserted")
    console.print(f"  fdp.cvap             : {cvap_total:,} rows upserted")
    console.print(f"\nQuery examples:")
    console.print(f"  SELECT year, office, party, SUM(votes)")
    console.print(f"  FROM fdp.election_results")
    console.print(f"  WHERE state = 'GA' GROUP BY 1,2,3 ORDER BY 1,2,3;")
    console.print(f"\n  SELECT * FROM fdp.v_statewide_results WHERE year = 2022;")
