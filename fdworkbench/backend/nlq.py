"""
NLQ → SQL translation and similarity detection via LiteLLM.
"""
from __future__ import annotations

import logging
import os
import re
from typing import Any

import litellm

from .schema import DATA_DICTIONARY

logger = logging.getLogger(__name__)

litellm.set_verbose = False


def _nlq_model() -> str:
    return os.environ.get(
        "NLQ_LLM_PROVIDER",
        os.environ.get("LLM_FALLBACK_PROVIDER", "groq/llama-3.3-70b-versatile"),
    )


_SYSTEM_PROMPT = f"""You are an expert SQL analyst for Fair Districts Georgia (FairDistrictsGA.org), specializing in redistricting, gerrymandering, and census data analysis. Your role is to convert natural language questions into precise DuckDB SQL queries.

{DATA_DICTIONARY}

────────────────────────────────────────────────────────────────────
SQL RULES:
• Return ONLY the raw SQL query — no markdown fences, no explanations, no comments.
• Use DuckDB SQL syntax.
• Percentages (pct_* columns) are stored as fractions 0.0–1.0 — multiply by 100 for display.
• step=0 in ensemble tables is always the enacted (current) plan. There is NO year column — the data does not distinguish 2021 vs 2023 plan years. Do NOT fabricate a year dimension; query what exists.
• If a question asks for a year-over-year comparison that cannot be answered from the available tables, write the best possible query given the actual data and add a SQL comment (-- NOTE: ...) explaining the limitation.
• Efficiency gap and mean-median: positive = favors Republicans, negative = favors Democrats.
• Add ORDER BY and LIMIT 100 for exploratory queries unless the user asks for aggregates or all data.
• When comparing enacted vs. ensemble, filter step>0 for simulated plans, step=0 for enacted.
• For "how does the enacted plan compare" queries, use UNION ALL with labeled rows.
• Never truncate table names. Always use the full name: ensemble_congress, ensemble_house, ensemble_senate.
• Return EXACTLY ONE SQL statement. Never output multiple SELECT statements separated by semicolons.
  If a question asks for multiple rankings, use a single query with UNION ALL or CTEs.
• For questions about Black VAP, minority VAP, or total population/VAP by district,
  use the vap_districts table — NOT demographics_* tables (which have no racial data).
• IMPORTANT: Hispanic VAP data does NOT exist in this dataset. vap_districts only has BVAP (Black VAP).
  If asked about Hispanic VAP, explain this limitation and query BVAP instead as the available metric.
• demographics_* tables only have: district_id, chamber, median_income, pct_poverty, poverty_count,
  pct_bachelors_plus, bachelors_plus_count, pct_male, pct_female, pct_married_family, married_hh_count,
  pct_single_parent, single_parent_count, pct_no_vehicle, no_vehicle_count, pct_uninsured, uninsured_count,
  pct_unemployed, unemployed_count, labor_force_count. Do NOT reference any other column names.

────────────────────────────────────────────────────────────────────
EXAMPLE NLQ → SQL PAIRS:

NLQ: "How does the enacted congressional map compare to the ensemble on partisan bias?"
SQL:
SELECT 'Enacted' AS plan_type, dem_seats, ROUND(efficiency_gap,4) AS efficiency_gap, ROUND(mean_median,4) AS mean_median, ROUND(polsby_popper_mean,4) AS compactness
FROM ensemble_congress WHERE step = 0
UNION ALL
SELECT 'Ensemble Avg', ROUND(AVG(dem_seats),1), ROUND(AVG(efficiency_gap),4), ROUND(AVG(mean_median),4), ROUND(AVG(polsby_popper_mean),4)
FROM ensemble_congress WHERE step > 0

NLQ: "Which congressional districts have the highest poverty rates?"
SQL:
SELECT district_id, ROUND(pct_poverty*100,1) AS pct_poverty, poverty_count, ROUND(median_income) AS median_income
FROM demographics_congress
ORDER BY pct_poverty DESC
LIMIT 14

NLQ: "What percentage of simulated senate plans had fewer Democratic seats than the enacted map?"
SQL:
WITH enacted AS (SELECT dem_seats FROM ensemble_senate WHERE step = 0)
SELECT
    e.dem_seats AS enacted_dem_seats,
    COUNT(*) AS plans_with_fewer,
    ROUND(COUNT(*) * 100.0 / (SELECT COUNT(*) FROM ensemble_senate WHERE step > 0), 1) AS pct_with_fewer
FROM ensemble_senate s, enacted e
WHERE s.step > 0 AND s.dem_seats < e.dem_seats

NLQ: "Which GA counties had public participation in their 2021 redistricting?"
SQL:
SELECT name, type, pop20, dist_type, redist_coord
FROM lrdb
WHERE participation_w = 'yes' AND type = 'County Commission'
ORDER BY pop20 DESC
LIMIT 50

NLQ: "Show me the distribution of Democratic seats across the congressional ensemble"
SQL:
SELECT dem_seats, COUNT(*) AS plans, ROUND(COUNT(*)*100.0/SUM(COUNT(*)) OVER(),1) AS pct
FROM ensemble_congress
WHERE step > 0
GROUP BY dem_seats
ORDER BY dem_seats
"""

_SIMILARITY_PROMPT = """You are checking if a new question is semantically equivalent to any of the saved queries below.
Two questions are "equivalent" if they ask for the same data and analysis, even if worded differently.

Respond with ONLY the integer ID of the matching saved query, or the word "none" if no match exists.
Do not explain your answer.

New question: {nlq}

Saved queries:
{saved_list}

Answer:"""


def _call_llm(messages: list[dict], model: str | None = None, max_tokens: int = 1024) -> str:
    m = model or _nlq_model()
    resp = litellm.completion(
        model=m,
        messages=messages,
        max_tokens=max_tokens,
        temperature=0,
    )
    return resp.choices[0].message.content.strip()


def check_similarity(nlq: str, saved_queries: list[dict]) -> int | None:
    """Return the ID of a semantically equivalent saved query, or None."""
    if not saved_queries:
        return None

    saved_list = "\n".join(f"  ID {q['id']}: {q['nlq']}" for q in saved_queries)
    prompt = _SIMILARITY_PROMPT.format(nlq=nlq, saved_list=saved_list)

    try:
        answer = _call_llm(
            [{"role": "user", "content": prompt}],
            max_tokens=16,
        )
        answer = answer.strip().lower()
        if answer == "none" or not answer:
            return None
        # Extract first integer found
        m = re.search(r"\d+", answer)
        if m:
            matched_id = int(m.group())
            # Validate that the ID actually exists
            valid_ids = {q["id"] for q in saved_queries}
            if matched_id in valid_ids:
                return matched_id
        return None
    except Exception as exc:
        logger.warning("Similarity check failed: %s", exc)
        return None


def nlq_to_sql(nlq: str) -> str:
    """Translate a natural language question to DuckDB SQL."""
    messages = [
        {"role": "system", "content": _SYSTEM_PROMPT},
        {"role": "user", "content": nlq},
    ]
    raw = _call_llm(messages, max_tokens=2048)
    # Strip any accidental markdown fences
    raw = re.sub(r"^```\w*\s*", "", raw, flags=re.MULTILINE)
    raw = re.sub(r"\s*```$", "", raw.strip())
    return raw.strip()
