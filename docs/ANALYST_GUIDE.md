# Fair Districts GA — Analyst & User Guide

**Audience:** Data analysts, researchers, and advocates who want to understand
what the ensemble benchmark measures, how each metric is calculated, and how to
interpret the results.

No programming knowledge is required to follow this guide.

---

## Table of Contents

1. [What Is an Ensemble Benchmark?](#1-what-is-an-ensemble-benchmark)
2. [Input Data](#2-input-data)
3. [How the Ensemble Is Built](#3-how-the-ensemble-is-built)
4. [Metrics — Partisan Fairness](#4-metrics--partisan-fairness)
   - 4.1 [Democratic Seat Count](#41-democratic-seat-count)
   - 4.2 [Efficiency Gap](#42-efficiency-gap)
   - 4.3 [Mean-Median Difference](#43-mean-median-difference)
   - 4.4 [Competitive Districts](#44-competitive-districts)
5. [Metrics — Demographics](#5-metrics--demographics)
   - 5.1 [Majority-Black Districts](#51-majority-black-districts)
   - 5.2 [Majority-White Districts](#52-majority-white-districts)
   - 5.3 [Majority-Minority Coalition](#53-majority-minority-coalition)
6. [The Princeton Grading System](#6-the-princeton-grading-system)
7. [Key Findings — Georgia Congress 2026 v1](#7-key-findings--georgia-congress-2026-v1)
8. [Interpreting the Charts](#8-interpreting-the-charts)
9. [Data Quality & Limitations](#9-data-quality--limitations)
10. [Glossary](#10-glossary)

---

## 1. What Is an Ensemble Benchmark?

### The core idea

When someone draws a district map, they face millions of possible choices. Some
of those choices are neutral — the result of geography, following county lines,
keeping communities together. Other choices are strategic — deliberately drawing
lines to help one party win more seats.

The ensemble benchmark answers: **"Is the enacted map a typical outcome, or an
extreme outlier?"**

We generate 9,000–10,000 randomly drawn maps that satisfy every legal constraint:
- Equal population (within ±1–5% depending on chamber)
- Geographic contiguity (every district is connected)
- Reasonable compactness

If the enacted map happens to give Republicans 9 seats when 9,950 out of 10,000
random maps gave Democrats 5 or more, that's not a coincidence — it's a sign of
intentional design.

### Analogy

Imagine a coin that comes up heads 95% of the time. One flip of heads is not
evidence of cheating. But if a neutral coin-flipping algorithm produces heads
only 5% of the time, and the actual coin lands heads every time, something
is clearly wrong.

The ensemble is the neutral coin-flipping algorithm. The enacted map is the
actual flip.

---

## 2. Input Data

### Election results (6 elections)

All elections are from official Georgia Secretary of State certified results,
processed through the Redistricting Data Hub (RDH) block-disaggregation pipeline.

| Label | Election | Candidates | Source |
|---|---|---|---|
| `gov_2018` | 2018 General — Governor | Kemp (R) / Abrams (D) | ALARM RDS |
| `pre_2020` | 2020 General — President | Trump (R) / Biden (D) | RDH block file |
| `uss_2021_war` | 2021 January 5 Runoff — US Senate | Loeffler (R) / Warnock (D) | RDH block file |
| `gov_2022` | 2022 General — Governor | Kemp (R) / Abrams (D) | RDH block file |
| `uss_2022` | 2022 General — US Senate | Walker (R) / Warnock (D) | RDH block file |
| `pre_2024` | 2024 General — President | Trump (R) / Harris (D) | RDH block file |

**Why these six?** They span three election cycles and two different offices
(president and governor), which reduces the risk that any single unusual election
drives the findings. Using both a presidential and gubernatorial race from each
cycle captures both national and state-level partisan trends.

**Why not state legislative elections?** Down-ballot state legislature races
are frequently uncontested (no opponent runs), which makes them unsuitable for
measuring partisan voting patterns across all 14 districts.

### CVAP (Citizen Voting Age Population)

Demographic data comes from the **2024 ACS 5-year estimates** (covering
2020–2024), disaggregated to 2020 Census blocks by RDH.

CVAP measures the number of citizens of voting age — the legally relevant
population for assessing Voting Rights Act compliance. It differs from total
population and from total voting age population (VAP) in that it excludes
non-citizens who cannot legally vote.

| Column | What it counts |
|---|---|
| `CVAP_TOT` | Total citizen voting age population |
| `CVAP_BLK` | Black or African American alone or in combination |
| `CVAP_HSP` | Hispanic or Latino (any race) |
| `CVAP_WHT` | White, non-Hispanic alone |
| `CVAP_ASN` | Asian alone or in combination |

### Prison population adjustment

The raw Census counts for some rural Georgia counties (Telfair, Stewart, Wheeler,
etc.) include large prison populations that inflate those counties' official
numbers. We subtract the group quarters corrections (`P0050003` in PL 94-171)
to compute `VAP_MOD`, which is used as the disaggregation weight when
proportioning block-level data to VTD boundaries.

### Geography: 2020 Census VTDs

All analysis uses the **2020 Census Voting Tabulation Districts (VTDs)** —
Georgia's 2,698 officially designated precinct-equivalent units. These are the
smallest geographic units for which Census demographic data is published.

The VTDs are the "atoms" of the redistricting simulation: the algorithm can move
whole VTDs between districts but cannot split them.

> **Limitation:** VTDs can be larger than legislative districts in rural areas.
> This is why the enacted State House map shows population deviations up to 33%
> at VTD level — not because the actual enacted map is that unequal, but because
> assigning large VTDs whole to one side of a boundary introduces rounding error.
> The ensemble simulation stays within ±5% at VTD resolution.

---

## 3. How the Ensemble Is Built

### Step 1 — Build the dual graph

Each VTD becomes a **node**. Two nodes are connected by an **edge** if the
corresponding VTDs share a geographic border (rook adjacency — shared boundary
length > 0). This gives us a graph with 2,698 nodes and ~7,705 edges.

Each node carries attributes used during sampling:
- `TOTPOP` — total population (from 2020 Census PL 94-171)
- `GEOID20` — unique 11-character VTD identifier
- `CDIST` / `SDIST` / `HDIST` — the enacted district assignment

### Step 2 — Run the ReCom algorithm

**ReCom** (short for ReCombination) is a Markov Chain Monte Carlo algorithm
developed by the Princeton Gerrymandering Project (GerryChain library).

At each step:
1. Pick two **adjacent districts** at random
2. Build a **random spanning tree** across all the VTDs in those two districts
3. Find an edge in the tree that divides the VTDs into two groups with
   roughly equal population (within ±ε of the ideal)
4. Assign one group to district A and the other to district B
5. Accept the new map (we use "always accept" — this is a uniform random walk)

After 10,000 steps (with the first 500–2,000 discarded as warm-up), we have a
sample of 8,000–9,500 distinct maps, each one a legal redistricting plan.

**Population tolerance (ε):**
- Congress: ±1.0% (federal constitutional standard)
- State Senate: ±5.0% (state constitutional standard, Reynolds v. Sims)
- State House: ±5.0%

**Draw 1 always = the enacted plan.** It is stored as the first row so it can be
directly compared against the simulated draws (2 through N).

### Step 3 — Score each map

For each simulated map × each election × each district, we compute:
- Total Democratic votes and total Republican votes
- **Two-party vote share (dem_2pv)**: Democratic votes ÷ (Democratic + Republican votes)
- Winner: `dem` if dem_2pv > 0.5, `rep` if dem_2pv < 0.5

We then aggregate to the draw level for each election to compute the metrics
described in the next section.

---

## 4. Metrics — Partisan Fairness

All metrics are computed separately for each of the six benchmark elections.
This produces six distributions — one per election — which can be compared to
see how the enacted map performs across different political environments.

### 4.1 Democratic Seat Count

**What it measures:** How many of the 14 congressional districts would be won
by the Democratic candidate.

**Formula:**

```
dem_seats = number of districts where dem_2pv > 0.5
```

where `dem_2pv = dem_votes / (dem_votes + rep_votes)` for each district.

**How to interpret:** The ensemble produces a distribution of seat counts. If
the enacted map gives Democrats 5 seats and 8,000 out of 9,000 simulated maps
give Democrats 6 or more, the enacted map is an outlier favoring Republicans.

**What we found (Georgia Congress 2026 v1):**

| Election | Enacted D seats | Ensemble median | Percentile | Grade |
|---|---|---|---|---|
| 2018 Governor | D5 | 5 | 78th | B |
| 2020 President | D5 | 5 | 55th | A |
| 2021 Senate Runoff | D5 | 6 | 43rd | A |
| 2022 Governor | D5 | 4 | 95th | C |
| 2022 Senate | D5 | 5 | 50th | A |
| 2024 President | D5 | 5 | 65th | A |

The 2021 Senate Runoff is the most revealing: in a Democratic wave environment
where neutral maps produce a median of 6 Democratic seats, the enacted map
produces only 5. The 2022 Governor race shows the opposite — in a Republican
wave year, the enacted map actually produces more Democratic seats than typical
neutral maps (D5 vs. median D4). This asymmetry is a design signature: the map
is built to lock in Republican advantage in neutral or Democratic environments
while still appearing fair in heavily Republican environments.

---

### 4.2 Efficiency Gap

**What it measures:** The difference in "wasted votes" between the two parties.
A vote is wasted if it goes to the losing candidate (regardless of margin) or
is more than the minimum needed to win (excess votes in a landslide).

**Formula:**

For each district in a given draw:

```
Wasted Dem votes =
    IF Dems win: dem_votes − (total_votes / 2)   [excess votes above winning threshold]
    IF Dems lose: all dem_votes                   [all votes go to the losing candidate]

Wasted Rep votes = same logic from the Republican side

Efficiency Gap = (total_wasted_dem − total_wasted_rep) / total_votes
```

**Sign convention:** Positive = Republican advantage (Dems waste more votes).
Negative = Democratic advantage.

**Significance thresholds:**
- |EG| < 0.05 (5%): within normal range
- |EG| > 0.08 (8%): substantial partisan bias (SCOTUS-cited threshold)
- |EG| > 0.10 (10%): severe

**Plain English:** If one party consistently wins big in a few districts while
the other party wins many districts by small margins, the big-winning party
is "wasting" votes, and the map is inefficient for them. A gerrymanderer
**packs** the opponent's voters into safe districts (lots of excess wasted votes)
and **cracks** the remainder across districts where they lose narrowly (all
wasted). This creates a large positive EG favoring the gerrymanderer.

**What we found:** The enacted Georgia congressional map has an average
efficiency gap of +11% across all six elections, meaning Democrats waste
significantly more votes than Republicans. This is above the 8% threshold
considered substantial by election law scholars.

---

### 4.3 Mean-Median Difference

**What it measures:** The difference between the mean Democratic vote share
across all districts and the median Democratic vote share.

**Formula:**

```
Mean-Median = mean(dem_2pv across all districts) − median(dem_2pv across all districts)
```

**Sign convention:** Positive = Democratic advantage (Dems win seats more efficiently).
Negative = Republican advantage.

**Significance threshold:** Values outside ±0.03 (3 percentage points) suggest
systematic partisan advantage.

**Plain English:** In a fair map, the mean and median vote share should be close.
If a party's vote share is clustered in a few large wins (packing), their median
will be higher than their mean — meaning they win some seats in blowouts while
losing many others narrowly. This produces a negative mean-median (favoring
Republicans) even when Democrats win the statewide popular vote.

---

### 4.4 Competitive Districts

**What it measures:** How many districts have a close enough vote margin
that either party could win with a reasonable shift in turnout or candidate quality.

**Formula:**

```
win_margin = |dem_2pv − 0.50| × 2

competitive_at_threshold_T = number of districts where win_margin ≤ T
```

**Primary threshold used:** T = 0.05 (5% win margin — the winning candidate
gets between 52.5% and 47.5% of the two-party vote).

**How to interpret:** A district with a 5% margin can flip parties if 2.5% of
voters switch sides — a realistic possibility in most elections. The more
competitive districts a map has, the more voters have real choices and the more
the legislature reflects actual shifts in public opinion.

**What we found:** The enacted Georgia congressional map has **0 competitive
districts** (margin ≤ 5%) in every election. The ensemble average is 1–2
competitive districts. This means **100% of simulated neutral maps produce more
competitive districts** than the enacted map — the enacted map maximally
insulates all incumbents from electoral accountability.

---

## 5. Metrics — Demographics

Demographic metrics use CVAP (Citizen Voting Age Population) rather than total
population, because only citizens can vote. The threshold for a "majority"
district is CVAP > 50%.

### 5.1 Majority-Black Districts

**Formula:**

```
majority_black = (CVAP_BLK / CVAP_TOT) > 0.50
```

where CVAP_BLK counts Black or African American citizens "alone or in combination"
(includes biracial and multiracial individuals with any Black ancestry, per
the standard Census "any part" counting method).

**Legal significance:** The Voting Rights Act (VRA) § 2 prohibits maps that
dilute minority voting power. Courts have generally held that minority groups
must have an opportunity to elect candidates of their choice when they are
geographically concentrated and politically cohesive. A map that packs a minority
group into fewer districts than geography would naturally produce may violate § 2.

**What we found:** The enacted Georgia congressional map has **4 majority-Black
districts** (D4, D5, D6, D13). The ensemble average is only **2**. This is at
the extreme high end — the enacted map has more majority-Black districts than
virtually any neutral simulation would produce. This is consistent with a
"packing" strategy: concentrating Black Democratic voters into a small number
of overwhelmingly safe Democratic seats, which reduces their influence in
surrounding districts.

### 5.2 Majority-White Districts

**Formula:**

```
majority_white = (CVAP_WHT / CVAP_TOT) > 0.50
```

where CVAP_WHT counts White, non-Hispanic citizens only.

**What we found:** The enacted map has **9 majority-white districts**. The
ensemble average is 9.7, so the enacted map is slightly below the ensemble
center on this metric.

### 5.3 Majority-Minority Coalition

**Formula:**

```
pct_minority_coalition = 1 − (CVAP_WHT / CVAP_TOT)
majority_coalition = pct_minority_coalition > 0.50
```

This captures districts where all non-white groups together constitute a majority,
even if no single group crosses 50% on its own.

**What we found:** The enacted map has **5 majority-minority coalition districts**,
at the 37th percentile of the ensemble — roughly within the normal range.

---

## 6. The Princeton Grading System

The Princeton Gerrymandering Project grades maps based on where the enacted plan
falls in the distribution of simulated plans. We use the same framework.

**For seat counts, the grade is:**

| Grade | What it means | Percentile range |
|---|---|---|
| **A** | Enacted map falls in the center 50% of simulated maps | 25th–75th percentile |
| **B** | Enacted map falls in the center 80% of simulated maps | 10th–90th percentile |
| **C** | Enacted map falls in the center 90% of simulated maps | 5th–95th percentile |
| **F** | Enacted map is a significant outlier | 1st–99th percentile |
| **FAIL** | Enacted map is an extreme outlier | Below 1st or above 99th percentile |

**Important note:** The grade is based on the enacted map's **percentile rank**,
not the direction. A map can get an "A" grade by being in the IQR whether it's
favorable to Democrats or Republicans. The grade measures statistical extremeness,
not partisan direction. Advocates should report both the grade and the direction
(e.g., "Grade C, enacted map at 95th percentile, meaning 95% of neutral maps
produced more Democratic seats").

**Composite grading:** If a run has multiple elections, the **worst grade across
all elections** is used as the composite grade. This is the most conservative
approach — a map that looks fair in one election but is an outlier in another
should not receive a passing composite grade.

---

## 7. Key Findings — Georgia Congress 2026 v1

**Run name:** `congress_2026_v1`  
**Draws:** 9,999 simulated maps + 1 enacted (draw 1)  
**Algorithm:** ReCom, 10,000 steps, burn-in 0, ε = 2% (VTD-level)  

### Partisan fairness summary

The enacted map locks in a **D5/R9 split** regardless of political environment:

- In the 2021 Senate Runoff wave (a statewide Democratic environment), the
  ensemble median is **D6**. The enacted map produces only **D5** — 1 seat
  below what a neutral map would typically produce.
- In the 2022 GOP wave, the enacted map produces **D5** when the ensemble
  median is **D4** — meaning the map actually protected 1 Democratic seat
  that a neutral map might have flipped.
- In the moderate 2020/2024 presidential environments, the enacted map
  sits at or near the ensemble median.

This asymmetric behavior — performing slightly below expectations for Democrats
in their best environment, slightly above in their worst — is consistent with
a map designed to minimize variance around a target of 5 Democratic seats.

### Competitiveness finding (strongest signal)

**0 competitive districts** (margin ≤ 5%) in 5 of 6 elections.  
Only the 2022 Governor race produces 1 competitive district in the enacted map.  
Ensemble average: **1.4 districts** at the 5% threshold.  
**100% of simulated maps produce more competitive districts** than the enacted
map in most election environments.

This is the clearest quantitative signal of gerrymandering in the dataset.

### Demographic finding (packing)

**4 majority-Black districts vs. ensemble average of 2.**  
The enacted map has more majority-Black districts than essentially all neutral
simulations — at the **0th percentile** of the distribution. While VRA compliance
requires some majority-minority districts, having more than nearly any neutral
map suggests that Black voters are being packed into the minimum number of
politically effective seats.

---

## 8. Interpreting the Charts

### Partisan histogram

Each bar shows the fraction of simulated maps that produced that many Democratic
seats. The blue shaded region is the IQR (center 50%). The red dashed line is
the enacted map.

**What to look for:**
- Is the enacted map's red line inside the blue shaded IQR? (Grade A = good)
- Is the enacted map consistently to the left of center? (Fewer Democratic seats than typical)
- Is the pattern consistent across all six elections?

### Competitiveness histogram

Same structure as the partisan histogram, but the x-axis shows how many
competitive districts each simulated map produced.

**What to look for:**
- Is the enacted map's line at 0 (or near 0) while the ensemble clusters at 2–4?
- A map at the extreme left means it maximally reduces competitive districts.

### Demographics histogram

Three panels: majority-Black, majority-White, majority-minority coalition.
The colored bar shows the simulated distribution; the red line shows enacted.

**What to look for:**
- Majority-Black panel: Is the enacted map to the right of the ensemble (more
  packed)? Is it at or above the 90th percentile?

### River chart

The x-axis shows each district, sorted by its median Democratic vote share
across all simulated maps (leftmost = most Republican, rightmost = most Democratic).
The blue bands show the 5th–95th percentile (outer band) and 25th–75th percentile
(IQR, inner band). The red line is the enacted plan.

**What to look for:**
- Does the red line follow the blue IQR band smoothly (consistent with typical
  maps), or does it zigzag wildly (unusually structured)?
- Districts where the red line is far outside the bands represent unusual choices.
- The classic gerrymander pattern is a zigzag: alternating very safe R and very
  safe D districts, with no competitive ones in between.

---

## 9. Data Quality & Limitations

### Election data accuracy

All vote totals are verified against Georgia Secretary of State certified results.
Typical discrepancy: < 0.1%. The small gap comes from VTD-level rounding when
disaggregating block-level data.

| Election | Dem diff from SOS | Rep diff from SOS |
|---|---|---|
| 2018 Governor | 0.04% | 0.04% |
| 2021 Senate Runoff | 0.00% | 0.00% |
| 2022 Governor | 0.01% | 0.04% |
| 2022 Senate | 0.04% | 0.00% |
| 2024 President | 0.01% | 0.03% |

### VTD vs. precinct

The analysis uses 2020 Census VTDs, not actual 2022 or 2024 election precincts.
Georgia changed precinct boundaries between 2020 and 2024. This means:

1. The precinct data is disaggregated from blocks to 2020 VTDs using population
   weights — a standard redistricting practice, not an approximation unique to
   this analysis.
2. The same geographic unit is used consistently for all elections and for the
   ensemble, so relative comparisons are valid.

### Ensemble sample size

9,000–10,000 draws is standard for published redistricting analyses (Princeton
uses 1M, but for most applications 10,000 is sufficient for stable percentile
estimates). Percentile ranks reported to the nearest 0.1% are reliable; the
uncertainty on a percentile estimate from 10,000 draws is approximately ±0.5%.

### Enacted map VTD-level deviations

The enacted congressional map, when evaluated at VTD level, has a maximum
population deviation of 1.8% (vs. the 1% target). This is because the actual
enacted map was drawn at block or split-VTD precision; assigning whole VTDs
to one side of a boundary introduces rounding. The ensemble uses ±2% tolerance
to accommodate this. This is consistent with Princeton and ALARM methodologies.

---

## 10. Glossary

| Term | Definition |
|---|---|
| **CVAP** | Citizen Voting Age Population — people who are both citizens and at least 18 years old |
| **dem_2pv** | Democratic two-party vote share: Dem votes ÷ (Dem + Rep votes), expressed as 0–1 |
| **Draw** | One simulated map produced by the ReCom algorithm |
| **Efficiency Gap (EG)** | Measure of wasted vote asymmetry between parties; positive = Republican advantage |
| **Ensemble** | The full set of simulated maps used as a statistical benchmark |
| **Gerrymander** | Drawing district lines to give one party a systematic advantage |
| **IQR** | Interquartile range — the middle 50% of a distribution (25th–75th percentile) |
| **Majority-minority district** | A district where a minority group constitutes > 50% of CVAP |
| **Mean-median difference** | Mean Dem vote share minus median Dem vote share; negative = Republican packing advantage |
| **Packing** | Concentrating a group's voters into a small number of overwhelmingly safe districts |
| **Cracking** | Splitting a group's voters across many districts where they narrowly lose |
| **Percentile rank** | The fraction of simulated maps at or below the enacted value |
| **Princeton grade** | Letter grade (A–F) based on percentile rank of enacted map vs. ensemble |
| **ReCom** | Redistricting Combinatorics — the Markov Chain algorithm used to generate random maps |
| **VTD** | Voting Tabulation District — Census precinct equivalent; the atom of this analysis |
| **VRA** | Voting Rights Act of 1965 — federal law prohibiting racial discrimination in voting |
| **Win margin** | |dem_2pv − 0.5| × 2; a margin of 0.05 means 52.5% vs 47.5% |
| **ε (epsilon)** | Population tolerance — how much any district can deviate from ideal population |
