#!/usr/bin/env python3
"""
generate_narrative.py — AI-generated prose narrative from a canonical scorecard JSON.

Reads a *_scorecard.json (produced by build_scorecard.py or transcode_alarm.py)
and uses LiteLLM to generate a multi-section Markdown narrative suitable for:
  - Sharing with advocacy stakeholders
  - NotebookLM source document (upload the .md → get an Audio Overview podcast)
  - Press briefings and litigation support

Model is fully configurable via LLM_PROVIDER env var — no hardcoded providers.

Usage (from fgdp/ root):
    # Default model (openai/gpt-4o):
    uv run --project fdp python fdp/scripts/generate_narrative.py \\
        --scorecard fdensemble/input_data/congress_2026_v2_scorecard.json

    # Groq (fast, free tier):
    LLM_PROVIDER=groq/llama-3.3-70b-versatile \\
    uv run --project fdp python fdp/scripts/generate_narrative.py \\
        --scorecard fdensemble/input_data/congress_2026_v2_scorecard.json

    # Anthropic:
    LLM_PROVIDER=anthropic/claude-opus-4-5 \\
    uv run --project fdp python fdp/scripts/generate_narrative.py \\
        --scorecard fdensemble/input_data/congress_2026_v2_scorecard.json

    # All three chambers, one run:
    for run in congress senate house; do
      uv run --project fdp python fdp/scripts/generate_narrative.py \\
          --scorecard fdensemble/input_data/${run}_2026_v1_scorecard.json
    done

Environment variables:
    LLM_PROVIDER        provider/model string (default: openai/gpt-4o)
    OPENAI_API_KEY      for openai/* and openrouter/*
    GROQ_API_KEY        for groq/*
    ANTHROPIC_API_KEY   for anthropic/*

Output:
    docs/narratives/{run_name}_narrative.md
    (or --out <path> to override)
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date
from pathlib import Path

_SCRIPT_DIR = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = _SCRIPT_DIR.parent.parent / "docs" / "narratives"
DEFAULT_MODEL   = "openai/gpt-4o"


# ── Scorecard → structured summary ────────────────────────────────────────────

def _grade_meaning(grade: str) -> str:
    return {"A": "Excellent (within normal range)", "B": "Acceptable",
            "C": "Concern — outside typical range", "F": "Fail — strong evidence of manipulation"}.get(grade, grade)


def _pct_context(pct_rank: float) -> str:
    """Human-readable percentile context."""
    if pct_rank >= 97.5:
        return f"more extreme than 97.5% of neutral maps — a 1-in-40 outlier"
    if pct_rank >= 95:
        return f"more extreme than 95% of neutral maps"
    if pct_rank >= 90:
        return f"more extreme than 90% of neutral maps"
    if pct_rank <= 2.5:
        return f"more extreme (in the other direction) than 97.5% of neutral maps"
    if pct_rank <= 5:
        return f"more extreme than 95% of neutral maps (reverse direction)"
    if pct_rank <= 10:
        return f"more extreme than 90% of neutral maps (reverse direction)"
    return f"within the normal range (at the {pct_rank:.0f}th percentile)"


def _build_prompt(sc: dict) -> str:
    """
    Convert scorecard JSON → a rich structured prompt for the LLM.
    Returns the full user message with all findings embedded.
    """
    run = sc["run"]
    chamber  = run.get("chamber", "unknown").title()
    n_draws  = run.get("n_draws", 0)
    n_dist   = run.get("n_districts", 0)
    source   = run.get("source", "unknown")
    algo     = run.get("algorithm", "ensemble")
    name     = run.get("name", run.get("id", ""))
    today    = date.today().strftime("%B %Y")

    # Overall grades
    grades = sc.get("grades", {})
    overall_g = grades.get("_overall", {})
    pf_g      = grades.get("_partisan_fairness", {})

    overall_grade   = overall_g.get("grade", "?")
    pf_grade        = pf_g.get("grade", "?")
    ensemble_pass   = pf_g.get("ensemble_pass", None)
    normative_pass  = pf_g.get("normative_pass", None)

    # Per-election findings
    elections = sc.get("elections", [])
    election_blocks = []
    for elec in elections:
        label   = elec.get("label", "")
        metrics = elec.get("metrics", {})
        lines   = [f"\n**{label}**"]

        for key, label_txt in [
            ("dem_seats",      "Seat-Vote Proportionality"),
            ("efficiency_gap", "Wasted Votes Balance (Efficiency Gap)"),
            ("mean_median",    "Vote Distribution Symmetry (Mean-Median)"),
            ("comp_seats",     "Competitive Districts"),
        ]:
            m = metrics.get(key)
            if not m:
                continue
            enacted = m.get("enacted", 0)
            pct     = m.get("pct_rank", 50)
            hist    = m.get("histogram", {})
            p50     = hist.get("p50", 0)
            p5      = hist.get("p5", 0)
            p95     = hist.get("p95", 0)
            grade   = m.get("grade", "?")
            takeaway = m.get("takeaway", "")

            lines.append(
                f"  - {label_txt}: enacted={enacted:.3f}, neutral median={p50:.3f} "
                f"(range {p5:.3f}–{p95:.3f}), grade={grade}, {_pct_context(pct)}. "
                f"{takeaway}"
            )
        election_blocks.append("\n".join(lines))

    elections_text = "\n".join(election_blocks) if election_blocks else "(no per-election data)"

    # Demographics
    demo = sc.get("demographics", {})
    demo_lines = []
    if demo and demo.get("metrics"):
        for key, friendly in [("maj_black", "Majority-Black districts"),
                               ("min_coal",  "Minority-coalition districts")]:
            m = demo["metrics"].get(key)
            if not m:
                continue
            enacted = m.get("enacted", 0)
            pct     = m.get("pct_rank", 50)
            hist    = m.get("histogram", {})
            p5, p95 = hist.get("p5", 0), hist.get("p95", 0)
            grade   = m.get("grade", "?")
            takeaway = m.get("takeaway", "")
            demo_lines.append(
                f"  - {friendly}: {enacted:.0f} districts, neutral range {p5:.0f}–{p95:.0f}, "
                f"grade={grade}, {_pct_context(pct)}. {takeaway}"
            )
    demo_text = "\n".join(demo_lines) if demo_lines else "  (no demographic data in this scorecard)"

    # Compactness
    compact = sc.get("compactness", {})
    compact_text = "Not computed in this run (GerryChain does not measure compactness)." \
        if not compact.get("polsby_popper") else \
        f"Polsby-Popper (compactness): {compact['polsby_popper']}"

    prompt = f"""You are an expert redistricting analyst writing a non-partisan, factual assessment of a Georgia legislative district map for the Fair Districts GA advocacy organization.

CONTEXT:
- Map: Georgia {chamber} district plan
- Benchmark: {name}
- Algorithm: {algo} ensemble ({n_draws:,} independently drawn maps)
- Districts evaluated: {n_dist}
- Report date: {today}
- Data source: Princeton Gerrymandering Project methodology; election data from Redistricting Data Hub

OVERALL GRADES:
- Overall: {overall_grade} ({_grade_meaning(overall_grade)})
- Partisan Fairness: {pf_grade} ({_grade_meaning(pf_grade)})
- Ensemble test: {"PASS" if ensemble_pass else "FAIL" if ensemble_pass is not None else "N/A"}
- Normative (symmetry) test: {"PASS" if normative_pass else "FAIL" if normative_pass is not None else "N/A"}

PER-ELECTION FINDINGS:
{elections_text}

MINORITY REPRESENTATION:
{demo_text}

COMPACTNESS & GEOGRAPHY:
{compact_text}

---

WRITING INSTRUCTIONS:
Write a comprehensive analytical narrative with the following sections. The audience includes:
- Fair Districts GA advocates and volunteers
- Georgia legislators and their staff
- Journalists and media
- Legal teams (this may support Voting Rights Act or gerrymandering litigation)
- General public curious about how their maps were drawn

Tone: Authoritative, factual, non-partisan. Report findings objectively — state which party benefits from structural advantages as a factual observation, not an editorial judgment. Explain all technical terms in plain language when first introduced.

Structure your response EXACTLY as follows (use these Markdown headers):

# Georgia {chamber} District Map — Redistricting Fairness Assessment
## {today}

## Executive Summary
(3-4 sentences. Overall grade, whether the map passes the Princeton fairness test, and the single most striking finding. Suitable for a press release lede.)

## How This Analysis Works
(2-3 paragraphs. Explain the ensemble benchmark approach in plain language: what it means to draw thousands of neutral alternative maps, what the Princeton Gerrymandering Project methodology measures, and why this is a more rigorous standard than looking at the map in isolation. Define "gerrymandering" for general readers.)

## Partisan Fairness: Does the Map Treat Voters Equally?
(3-4 paragraphs. Walk through the partisan findings across elections. Identify patterns — does the map consistently favor one party across multiple elections? Quote specific numbers. Explain the Efficiency Gap and Mean-Median Difference in plain language. State clearly which party, if any, receives a structural advantage and what that means for voters.)

## Electoral Competitiveness: Do Voters Have a Meaningful Choice?
(2 paragraphs. How many competitive districts does the enacted map produce? How does this compare to neutral alternatives? What does a lack of competitiveness mean for voter representation and legislative accountability?)

## Minority Representation: Voting Rights Act Implications
(2 paragraphs. How does the map treat Black voters and other communities of color compared to what neutral geography would produce? Reference Section 2 of the Voting Rights Act. Note whether the findings raise legal concerns.)

## Pattern Across Elections
(2 paragraphs. Do the findings hold consistently across multiple elections (governor, president, senate)? Consistent patterns across multiple elections strengthen the case that the outcome reflects deliberate map design rather than natural geography.)

## What This Means for Georgia Voters
(2-3 paragraphs. Concrete implications. If the map is graded poorly: what does it mean that voters cannot change these outcomes through voting alone? If graded well: what does it mean that the map reflects neutral geographic principles? Avoid partisanship — frame around democratic values, voter voice, and fair representation.)

## Methodology Note
(1 paragraph. Brief technical note: GerryChain ReCom MCMC algorithm, number of draws, election data sources, Princeton grading methodology. Suitable for journalists who need to verify the analysis.)

---
*Analysis produced by Fair Districts GA using the Princeton Gerrymandering Project methodology. Data: Redistricting Data Hub (RDH). Ensemble computed with GerryChain (MGGG, MIT). This report may be freely reproduced with attribution.*
"""
    return prompt


# ── LiteLLM call ──────────────────────────────────────────────────────────────

def generate_narrative(scorecard_path: Path, model: str, verbose: bool = True) -> str:
    """Call LiteLLM to generate the narrative. Returns Markdown string."""
    import litellm

    sc = json.loads(scorecard_path.read_text())
    prompt = _build_prompt(sc)

    if verbose:
        run_name = sc.get("run", {}).get("id", scorecard_path.stem)
        print(f"Calling {model} for {run_name}…")
        print(f"  Prompt: ~{len(prompt.split()):,} words")

    response = litellm.completion(
        model    = model,
        messages = [
            {
                "role": "system",
                "content": (
                    "You are an expert non-partisan redistricting analyst. "
                    "Write clear, accurate, accessible prose. "
                    "Always explain technical terms. "
                    "State findings factually — note which party benefits "
                    "from structural advantages as an observation, not an endorsement."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        temperature = 0.4,   # factual, consistent
        max_tokens  = 4000,
    )

    return response.choices[0].message.content


# ── CLI ────────────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    ap.add_argument("--scorecard", required=True,
                    help="Path to *_scorecard.json (e.g. fdensemble/input_data/congress_2026_v2_scorecard.json)")
    ap.add_argument("--out", default=None,
                    help="Output Markdown path (default: docs/narratives/{run_name}_narrative.md)")
    ap.add_argument("--model", default=None,
                    help="LiteLLM model string, e.g. groq/llama-3.3-70b-versatile "
                         "(default: $LLM_PROVIDER or openai/gpt-4o)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print the prompt but don't call the LLM")
    args = ap.parse_args()

    scorecard_path = Path(args.scorecard)
    if not scorecard_path.exists():
        print(f"ERROR: scorecard not found: {scorecard_path}")
        sys.exit(1)

    model = args.model or os.environ.get("LLM_PROVIDER", DEFAULT_MODEL)

    sc       = json.loads(scorecard_path.read_text())
    run_name = sc.get("run", {}).get("id", scorecard_path.stem.replace("_scorecard", ""))

    out_file = Path(args.out) if args.out else (DEFAULT_OUT_DIR / f"{run_name}_narrative.md")
    out_file.parent.mkdir(parents=True, exist_ok=True)

    if args.dry_run:
        prompt = _build_prompt(sc)
        print(f"=== DRY RUN — prompt for {run_name} ===")
        print(prompt)
        print(f"\n[Would write to: {out_file}]")
        return

    narrative = generate_narrative(scorecard_path, model)

    out_file.write_text(narrative, encoding="utf-8")
    size_kb = out_file.stat().st_size / 1024
    word_count = len(narrative.split())

    print(f"\n✓ {out_file.name}  ({size_kb:.0f} KB, ~{word_count:,} words)")
    print(f"\nNext steps:")
    print(f"  1. Review the narrative: cat {out_file}")
    print(f"  2. Upload to NotebookLM → Sources → Add → select the .md file")
    print(f"     Then: Audio Overview → Generate → ~20 min for a podcast episode")
    print(f"  3. Or share the .md directly with stakeholders / legal team")


if __name__ == "__main__":
    main()
