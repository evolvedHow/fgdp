# FDP Schema — AI Agent NLQ Reference

This document is written for an AI agent translating natural language questions
into SQL against the FDP PostgreSQL database (`fdp` schema). Read it carefully
before generating any query. Many common redistricting questions have subtle
correctness requirements that differ from general SQL intuition.

---

## Database connection

```
postgresql://fdp:fdp_local@localhost:5432/fdp
```

Schema: `fdp`. Every table and view is in this schema — always qualify names
(e.g. `fdp.election_results`, not just `election_results`).

---

## Tables and their roles

| Table | Role | When to query |
|-------|------|---------------|
| `fdp.election_results` | All election results, all years, long format | Vote counts, winners, margins, turnout |
| `fdp.cvap` | Citizen Voting Age Population by VTD and ACS year | Demographic percentages, majority-minority analysis |
| `fdp.geography` | Geographic register — one row per VTD/precinct/county | Names, county FIPS, boundary metadata |
| `fdp.population` | Decennial Census demographics (currently empty) | Raw population, VAP, race by Census year |
| `fdp.geo_crosswalk` | Political↔Census boundary bridge (currently empty) | Cross-geography joins (future) |
| `fdp.ensemble_plans` | Redistricting plan draw assignments (currently empty) | Ensemble scoring (future) |

**Views** (pre-joined, use these first):

| View | Use for |
|------|---------|
| `fdp.v_election_2pv` | Two-party vote share per VTD per race |
| `fdp.v_county_results` | County-level aggregations |
| `fdp.v_statewide_results` | State totals + pct_of_total per race |
| `fdp.v_vtd_demographics` | VTD demographics with CVAP percentages |

---

## Critical rule: always filter `geo_level = 'vtd'`

Every fact table (`election_results`, `cvap`, `geography`) has a `geo_level` column.
Currently all data is loaded at `geo_level = 'vtd'`. In the future, data may also exist
at `block`, `county`, or other levels.

**If you query `election_results` without a `geo_level` filter, totals will be correct
today but will double-count once multi-level data is loaded.**

Always add `WHERE geo_level = 'vtd'` (or whatever level is appropriate) to every
query against base tables. The views already apply this filter — prefer views when
the question fits.

```sql
-- CORRECT
SELECT SUM(votes) FROM fdp.election_results
WHERE year = 2022 AND office = 'governor' AND geo_level = 'vtd';

-- DANGEROUS (omits geo_level filter)
SELECT SUM(votes) FROM fdp.election_results
WHERE year = 2022 AND office = 'governor';
```

---

## Canonical column values

### `election_results.office`

Use these exact strings in WHERE clauses. Never use aliases or partial matches.

| String | Meaning |
|--------|---------|
| `'governor'` | Governor |
| `'senate'` | U.S. Senate |
| `'president'` | President |
| `'attorney-general'` | Attorney General |
| `'secretary-of-state'` | Secretary of State |
| `'lt-governor'` | Lieutenant Governor |
| `'labor-commissioner'` | Labor Commissioner |
| `'insurance-commissioner'` | Insurance Commissioner |
| `'agriculture-commissioner'` | Agriculture Commissioner |
| `'superintendent'` | State School Superintendent |
| `'other_agrl'` etc. | Unrecognised RDH race codes — typically safe to exclude |

**NLQ disambiguation:**
- "governor's race" → `office = 'governor'`
- "Senate race" / "US Senate" / "Warnock" / "Walker" → `office = 'senate'`
- "presidential race" / "Trump" / "Biden" / "Harris" → `office = 'president'`
- "SOS" / "secretary of state" → `office = 'secretary-of-state'`
- "AG" / "attorney general" → `office = 'attorney-general'`
- "lite guv" / "lieutenant governor" → `office = 'lt-governor'`

### `election_results.party`

| String | Party |
|--------|-------|
| `'dem'` | Democrat |
| `'rep'` | Republican |
| `'lib'` | Libertarian |
| `'grn'` | Green |
| `'ind'` | Independent |
| `'other'` | Other |

**NLQ disambiguation:**
- "Democrat" / "Democratic" / "blue" → `party = 'dem'`
- "Republican" / "GOP" / "red" → `party = 'rep'`
- "third party" / "minor party" → `party NOT IN ('dem', 'rep')`

### `election_results.election_type`

| String | Meaning |
|--------|---------|
| `'general'` | General election (November) |
| `'runoff'` | Runoff election |
| `'special'` | Special election |
| `'primary'` | Primary election |

**Currently only `'general'` is loaded.** If a user asks about the 2022 December
Warnock/Walker runoff, that data is not yet in the database — tell them clearly.

### `election_results.year`

Four-digit election year (e.g. `2022`, `2024`).

**Important edge case:** The January 2021 Georgia Senate runoffs (Warnock/Loeffler
and Ossoff/Perdue) are stored with `year = 2020` because they were originally
scheduled as part of the 2020 election cycle. If a user asks about "the 2021 runoffs"
or "January 2021 Georgia Senate", filter `year = 2020 AND election_type = 'runoff'`.
(This data is not yet loaded — note this to the user.)

### `election_results.candidate`

Lowercase RDH surname codes or full surnames (e.g. `'kemp'`, `'abrams'`, `'warnock'`,
`'walker'`, `'tru'`, `'bid'`, `'har'`). For 2024 presidential: `'tru'` = Trump,
`'har'` = Harris.

**Do not filter on candidate unless the user specifically asks about a named
candidate.** For most vote-total queries, aggregate across all candidates of a party.

---

## Data currently in the database

| Year | Type | Offices available |
|------|------|------------------|
| 2022 | general | governor, senate, attorney-general, secretary-of-state, lt-governor, labor-commissioner, insurance-commissioner, agriculture-commissioner, superintendent |
| 2024 | general | president |

**Not yet loaded (tell the user if asked):**
- 2021 January Senate runoffs
- 2022 December Warnock/Walker Senate runoff
- 2016, 2018, 2020 elections (these are in the ALARM R map object, not in PostgreSQL)

**CVAP:** ACS 2024 (2020–2024 5-year estimates), 2,698 Georgia VTDs only.

**State:** Only Georgia (`state = 'GA'`) is currently loaded. All 2,698 VTDs are present.

---

## Two-party vote share

"Two-party vote share" or "two-party margin" always means:
```
dem_2pv = dem_votes / (dem_votes + rep_votes)
```

Libertarian, Green, and other party votes are **excluded from the denominator**.
This is the standard political science definition. Never include third parties in
the denominator unless the user explicitly asks for "all-party share" or "percent
of total votes."

```sql
-- Two-party vote share for a race
SELECT
    geoid,
    SUM(CASE WHEN party = 'dem' THEN votes ELSE 0 END) AS dem_votes,
    SUM(CASE WHEN party = 'rep' THEN votes ELSE 0 END) AS rep_votes,
    ROUND(
        100.0 * SUM(CASE WHEN party = 'dem' THEN votes ELSE 0 END)::numeric
        / NULLIF(SUM(CASE WHEN party IN ('dem','rep') THEN votes ELSE 0 END), 0),
        2
    ) AS dem_2pv
FROM fdp.election_results
WHERE year = 2022 AND office = 'governor' AND geo_level = 'vtd'
GROUP BY geoid;

-- Or use the view (already computed)
SELECT geoid, dem_2pv, dem_votes, rep_votes
FROM fdp.v_election_2pv
WHERE year = 2022 AND office = 'governor';
```

---

## County-level aggregation

Counties are **not** stored as separate rows — they are derived from VTD geoids.
Georgia county FIPS = `LEFT(geoid, 5)`. This works for all Census GEOIDs.

```sql
-- County totals from VTD data
SELECT LEFT(geoid, 5) AS county_fips, party, SUM(votes) AS votes
FROM fdp.election_results
WHERE year = 2022 AND office = 'governor' AND geo_level = 'vtd'
GROUP BY LEFT(geoid, 5), party
ORDER BY county_fips, votes DESC;

-- Or use the view
SELECT county_fips, party, votes
FROM fdp.v_county_results
WHERE year = 2022 AND office = 'governor'
ORDER BY county_fips, votes DESC;
```

Known county FIPS prefixes (Georgia, partial):
- `13067` — Cobb
- `13089` — DeKalb
- `13121` — Fulton
- `13135` — Gwinnett
- `13057` — Cherokee
- `13151` — Henry
- `13063` — Clayton

---

## Demographics queries

CVAP columns (from `fdp.cvap` or `fdp.v_vtd_demographics`):

| Column | Demographic |
|--------|-------------|
| `cvap_tot` | Total CVAP |
| `cvap_blk` | Black or African American alone or in combination |
| `cvap_hsp` | Hispanic or Latino (any race) |
| `cvap_wht` | White alone, non-Hispanic |
| `cvap_asn` | Asian alone or in combination |
| `cvap_ami` | American Indian or Alaska Native |
| `cvap_nhp` | Native Hawaiian or Other Pacific Islander |
| `cvap_oth` | Other / multiracial |

**Majority-minority analysis (Voting Rights Act Section 2):**
```sql
-- VTDs where Black CVAP > 50%
SELECT geoid, pct_blk, cvap_tot, cvap_blk, county_fips
FROM fdp.v_vtd_demographics
WHERE pct_blk > 50
ORDER BY pct_blk DESC;

-- VTDs where Black + Hispanic CVAP > 50% (coalition majority)
SELECT geoid, cvap_tot,
       cvap_blk + cvap_hsp AS cvap_minority,
       ROUND(100.0 * (cvap_blk + cvap_hsp)::numeric / NULLIF(cvap_tot, 0), 1) AS pct_minority
FROM fdp.cvap
WHERE geo_level = 'vtd' AND year = 2024
  AND (cvap_blk + cvap_hsp)::float / NULLIF(cvap_tot, 0) > 0.5
ORDER BY pct_minority DESC;
```

---

## Join patterns

### Election results + demographics
```sql
SELECT er.geoid,
       SUM(CASE WHEN er.party = 'dem' THEN er.votes ELSE 0 END) AS dem_votes,
       SUM(CASE WHEN er.party = 'rep' THEN er.votes ELSE 0 END) AS rep_votes,
       c.cvap_tot,
       c.cvap_blk,
       ROUND(100.0 * c.cvap_blk::numeric / NULLIF(c.cvap_tot, 0), 1) AS pct_blk
FROM fdp.election_results er
JOIN fdp.cvap c ON c.geoid = er.geoid AND c.year = 2024 AND c.geo_level = 'vtd'
WHERE er.year = 2022 AND er.office = 'governor' AND er.geo_level = 'vtd'
GROUP BY er.geoid, c.cvap_tot, c.cvap_blk;
```

### Election results + geography (for names / county)
```sql
SELECT g.county_fips, g.name, er.party, SUM(er.votes) AS votes
FROM fdp.election_results er
JOIN fdp.geography g ON g.geoid = er.geoid AND g.vintage_year = 2020
WHERE er.year = 2022 AND er.office = 'governor' AND er.geo_level = 'vtd'
GROUP BY g.county_fips, g.name, er.party;
```

---

## Aggregation rules and gotchas

### Primary key structure
`election_results` PK: `(geoid, year, election_type, office, party, candidate)`

This means one race can have **multiple rows per VTD per party** if there are multiple
candidates of the same party (e.g. a primary). To get a party's total votes for a race,
always `SUM(votes)` and `GROUP BY party` — never assume one row per party.

### Winner determination
```sql
-- Winner per VTD (by total votes across all candidates of that party)
SELECT geoid,
       FIRST_VALUE(party) OVER (
           PARTITION BY geoid
           ORDER BY SUM(votes) DESC
       ) AS winning_party
FROM fdp.election_results
WHERE year = 2022 AND office = 'governor' AND geo_level = 'vtd'
GROUP BY geoid, party;

-- Simpler: use v_election_2pv
SELECT geoid, CASE WHEN dem_2pv > 50 THEN 'dem' ELSE 'rep' END AS winner
FROM fdp.v_election_2pv
WHERE year = 2022 AND office = 'governor';
```

### Statewide totals
```sql
-- Use the view for validation
SELECT * FROM fdp.v_statewide_results
WHERE year = 2022 AND office = 'governor';

-- Manual (equivalent)
SELECT party, SUM(votes) AS votes,
       ROUND(100.0 * SUM(votes)::numeric
             / NULLIF(SUM(SUM(votes)) OVER (), 0), 2) AS pct_total
FROM fdp.election_results
WHERE year = 2022 AND office = 'governor' AND geo_level = 'vtd'
GROUP BY party
ORDER BY votes DESC;
```

### Margin of victory
```sql
-- Statewide margin (dem_pct - rep_pct, two-party)
WITH totals AS (
    SELECT party, SUM(votes) AS votes
    FROM fdp.election_results
    WHERE year = 2022 AND office = 'governor' AND geo_level = 'vtd'
      AND party IN ('dem', 'rep')
    GROUP BY party
),
wide AS (
    SELECT
        SUM(CASE WHEN party = 'dem' THEN votes END) AS dem,
        SUM(CASE WHEN party = 'rep' THEN votes END) AS rep
    FROM totals
)
SELECT dem, rep,
       ROUND(100.0 * dem / (dem + rep), 2) AS dem_2pv,
       ROUND(100.0 * rep / (dem + rep), 2) AS rep_2pv,
       ROUND(100.0 * (dem - rep)::numeric / (dem + rep), 2) AS dem_margin
FROM wide;
```

---

## What `collection_geo_level` means (and when to ignore it)

`collection_geo_level` records where votes were **originally counted** by the
election board before any spatial disaggregation. For all RDH-sourced data it
is `'precinct'`.

**This column is metadata, not a filter dimension.** Do not add
`WHERE collection_geo_level = 'precinct'` to queries — it provides no analytical
distinction and will break if data from multiple collection levels is ever mixed.
Use `geo_level` for filtering, not `collection_geo_level`.

---

## Statewide validation benchmarks

Use these to verify query results before presenting them:

| Year | Office | Winner | Winner votes | Total votes |
|------|--------|--------|-------------|-------------|
| 2022 | governor | Kemp (rep) | 2,111,560 | 3,953,397 |
| 2022 | senate | Warnock (dem) | 1,946,113 | 3,935,905 |
| 2024 | president | Trump (rep) | 2,663,101 | 5,250,043 |

---

## Example NLQ → SQL mappings

| User question | SQL approach |
|---------------|-------------|
| "Who won the 2022 Georgia governor's race?" | `v_statewide_results WHERE year=2022 AND office='governor'` |
| "What was Abrams' vote share?" | `SUM(votes) WHERE party='dem' / total, year=2022, office='governor'` |
| "Show me the two-party margin by VTD for the 2022 governor's race" | `v_election_2pv WHERE year=2022 AND office='governor'` |
| "Which counties did Democrats win in 2022?" | `v_county_results` grouped by county, `dem_votes > rep_votes` |
| "How many majority-Black VTDs are there?" | `v_vtd_demographics WHERE pct_blk > 50` |
| "What is Fulton County's CVAP composition?" | `v_vtd_demographics WHERE county_fips = '13121'`, aggregate |
| "Compare 2022 Senate and Governor results by VTD" | `v_election_2pv WHERE year=2022 AND office IN ('governor','senate')` |
| "What was turnout vs CVAP in the 2022 election?" | Join `election_results` + `cvap`, `SUM(votes)/cvap_tot` |
| "Show VTDs where Democrats underperformed vs their demographic advantage" | Join `v_election_2pv` + `v_vtd_demographics`, compare `dem_2pv` vs `pct_blk + pct_hsp` |

---

## Out-of-scope requests (not in database)

If a user asks about any of the following, inform them the data is not yet loaded:

- **2021 January runoffs** (Warnock/Loeffler, Ossoff/Perdue) — not in PostgreSQL
- **2022 December runoff** (Warnock/Walker) — not in PostgreSQL
- **2016, 2018, 2020 elections** — in the ALARM R `.rds` files, not in PostgreSQL
- **Block-level or precinct-level election data** — aggregated to VTD only
- **Non-Georgia states** — only GA is loaded
- **Ensemble plan scoring** — `fdp.ensemble_plans` is empty
- **Decennial Census demographics** — `fdp.population` is empty; use `fdp.cvap` for demographics
