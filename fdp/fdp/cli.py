"""
FDP command-line interface.

  fdp workspace create <name> [--base main] [--desc "..."]
  fdp workspace list
  fdp workspace delete <name>

  fdp catalog [--app <app>] [--repo <repo>]
  fdp validate [--app <app>] [--repo <repo>] [--category boundaries]

  fdp sync-app <app> --dest <dir>
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
