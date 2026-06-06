#!/usr/bin/env python3
"""
Generate static JSON assets for GitHub Pages deployment of fdensemble.

Calls the FastAPI endpoints via TestClient (same code path as the live server)
and writes the responses to a directory structure that the static frontend expects.

Usage (from the repo root):
    cd fdensemble
    python scripts/export_static.py --out-dir frontend/dist

Output structure inside --out-dir:
    api/
        runs.json                              ← GET /api/runs
        analysis/
            {run_id}.json                      ← GET /api/analysis?run={id}&election=0
        correlations/
            {run_id}.json                      ← GET /api/analysis/correlations?run={id}
"""

import argparse
import json
import os
import pathlib
import sys
import urllib.parse


def main() -> None:
    parser = argparse.ArgumentParser(description="Export fdensemble static JSON")
    parser.add_argument(
        "--out-dir",
        required=True,
        help="Output directory (e.g. frontend/dist). api/ subdirs are created inside.",
    )
    args = parser.parse_args()

    out = pathlib.Path(args.out_dir).resolve()

    # Change to fdensemble/ so that main.py can find input_data/, data/, etc.
    script_dir = pathlib.Path(__file__).parent  # fdensemble/scripts/
    fdensemble_dir = script_dir.parent           # fdensemble/
    os.chdir(fdensemble_dir)
    sys.path.insert(0, str(fdensemble_dir))

    print(f"[export] Working directory: {fdensemble_dir}")
    print(f"[export] Output directory:  {out}")

    # Import the FastAPI app (this reads all scorecard JSONs from input_data/)
    print("[export] Importing app from main.py …")
    from fastapi.testclient import TestClient  # starlette ≥ 0.20 / httpx required
    from main import app  # noqa: E402

    client = TestClient(app, raise_server_exceptions=True)

    # ── /api/runs ──────────────────────────────────────────────────────────────
    print("[export] GET /api/runs")
    r = client.get("/api/runs")
    r.raise_for_status()
    runs: list[dict] = r.json()

    runs_dir = out / "api"
    runs_dir.mkdir(parents=True, exist_ok=True)
    (runs_dir / "runs.json").write_text(json.dumps(runs, indent=None))
    print(f"         → {len(runs)} runs written to api/runs.json")

    analysis_dir = out / "api" / "analysis"
    analysis_dir.mkdir(parents=True, exist_ok=True)

    correlations_dir = out / "api" / "correlations"
    correlations_dir.mkdir(parents=True, exist_ok=True)

    for run in runs:
        run_id = run["id"]
        safe_id = urllib.parse.quote(run_id, safe="")

        # ── /api/analysis?run=X&election=0 ────────────────────────────────────
        print(f"[export] GET /api/analysis?run={run_id}&election=0")
        r = client.get(f"/api/analysis?run={safe_id}&election=0")
        if r.status_code == 200:
            (analysis_dir / f"{run_id}.json").write_text(r.text)
            print(f"         → api/analysis/{run_id}.json  ({len(r.text):,} bytes)")
        else:
            print(f"         ! HTTP {r.status_code} — skipping")

        # ── /api/analysis/correlations?run=X ──────────────────────────────────
        print(f"[export] GET /api/analysis/correlations?run={run_id}")
        r = client.get(f"/api/analysis/correlations?run={safe_id}")
        if r.status_code == 200:
            data = r.json()
            if data.get("available"):
                (correlations_dir / f"{run_id}.json").write_text(r.text)
                print(f"         → api/correlations/{run_id}.json  ({len(r.text):,} bytes)")
            else:
                print(f"         (no correlation data for {run_id})")
        else:
            print(f"         ! HTTP {r.status_code} — skipping")

    print(f"\n[export] Done. Files written to {out}/api/")


if __name__ == "__main__":
    main()
