"""
Race registry — maps RDH column prefixes to canonical race names.

RDH column naming:  {prefix}{YY}{RACE_CODE}{PARTY}{NAME3}
  prefix:  G = general, R = runoff, S = special
  YY:      2-digit year
  RACE_CODE: GOV, USS, PRE, ATG, SOS, LTG, PSC, INS, LAB, SUP, AGR, A01…

This registry maps (year_prefix, race_code) → canonical race name used
in filenames and dataset IDs (e.g. "governor", "senate", "president").

Usage
-----
    from fdp.ingest.race_registry import race_name_for, cols_for_race

    race_name_for("G22GOV") → "governor"
    cols_for_race("governor", all_cols, year=2022) → ["G22GOVDABR", "G22GOVRKEM", ...]
"""

from __future__ import annotations

import re

# Mapping: RDH race code → canonical name
# Sorted from most specific to least so longest match wins
_CODE_TO_NAME: dict[str, str] = {
    "GOV":  "governor",
    "USS":  "senate",        # US Senate
    "PRE":  "president",
    "ATG":  "attorney-general",
    "SOS":  "secretary-of-state",
    "LTG":  "lt-governor",
    "PSC":  "public-service-commission",
    "INS":  "insurance-commissioner",
    "LAB":  "labor-commissioner",
    "SUP":  "superintendent",
    "AGR":  "agriculture-commissioner",
    # Ballot measures: A01, A02, RFA, RFB, A1, A2 etc. → "amendments"
}

# Reverse: canonical name → RDH code
_NAME_TO_CODE: dict[str, str] = {v: k for k, v in _CODE_TO_NAME.items()}

# Regex to parse an RDH column: prefix(G/R/S) + YY + RACE_CODE + party + name
# Office codes are capped at 3 chars to prevent greedy overlap with the party code.
# e.g. R21USSRLOE must parse as USS+R+LOE (not USSR+L+OE).
_COL_RE = re.compile(r"^([GRS])(\d{2})([A-Z0-9]{2,3})([DRLGI])([A-Z0-9]{2,4})$")

# Columns that are ballot measures / amendments (not candidate races)
_AMENDMENT_RE = re.compile(r"^[GRS]\d{2}[AR]\d+(NO|YES|YE)$", re.IGNORECASE)
_REFERENDUM_RE = re.compile(r"^[GRS]\d{2}RF[AB](NO|YES)$", re.IGNORECASE)


def race_code_from_col(col: str) -> str | None:
    """
    Extract the race code from an RDH column name.

    Returns the 2-6 char race code (e.g. "GOV", "USS", "PRE") or None if
    the column doesn't match the RDH naming pattern.
    """
    m = _COL_RE.match(col)
    return m.group(3) if m else None


def race_name_for(col_or_code: str) -> str | None:
    """
    Return the canonical race name for an RDH column or race code.

    Returns None for ballot measures, amendments, and unrecognized codes.

    Examples
    --------
        race_name_for("G22GOVDABR")  → "governor"
        race_name_for("G24PRERTRU")  → "president"
        race_name_for("G22A01NO")    → None  (ballot measure)
        race_name_for("GOV")         → "governor"
    """
    # Maybe it's already a code
    if col_or_code.upper() in _CODE_TO_NAME:
        return _CODE_TO_NAME[col_or_code.upper()]

    # Bail out on amendments/referendums
    if _AMENDMENT_RE.match(col_or_code) or _REFERENDUM_RE.match(col_or_code):
        return None

    code = race_code_from_col(col_or_code)
    return _CODE_TO_NAME.get(code) if code else None


def is_candidate_race(col: str) -> bool:
    """Return True if this column is a candidate vote tally (not a ballot measure)."""
    if _AMENDMENT_RE.match(col) or _REFERENDUM_RE.match(col):
        return False
    return _COL_RE.match(col) is not None


def cols_for_race(
    race: str,
    all_cols: list[str],
    year: int | None = None,
) -> list[str]:
    """
    Return all RDH columns belonging to a specific race from a column list.

    Parameters
    ----------
    race:      Canonical race name (e.g. "governor", "president", "senate")
               or RDH race code (e.g. "GOV", "PRE", "USS").
    all_cols:  Full column list from the shapefile/parquet.
    year:      Filter to this year's columns (e.g. 2022 → G22*, R22*).

    Returns
    -------
    List of matching column names.
    """
    # Normalize to RDH code
    if race.upper() in _CODE_TO_NAME:
        code = race.upper()
    else:
        code = _NAME_TO_CODE.get(race.lower())
        if code is None:
            raise ValueError(
                f"Unknown race {race!r}. Known races: {sorted(_NAME_TO_CODE)}"
            )

    yy: str | None = str(year)[-2:] if year else None

    result = []
    for col in all_cols:
        m = _COL_RE.match(col)
        if not m:
            continue
        if m.group(3) != code:
            continue
        if yy and m.group(2) != yy:
            continue
        result.append(col)
    return result


def races_present(all_cols: list[str], year: int | None = None) -> dict[str, list[str]]:
    """
    Scan a column list and return all candidate races found, grouped by name.

    Returns dict: canonical_race_name → [col1, col2, ...]

    Ballot measures are grouped under "amendments".
    """
    result: dict[str, list[str]] = {}
    yy = str(year)[-2:] if year else None

    for col in all_cols:
        if _AMENDMENT_RE.match(col) or _REFERENDUM_RE.match(col):
            result.setdefault("amendments", []).append(col)
            continue
        m = _COL_RE.match(col)
        if not m:
            continue
        if yy and m.group(2) != yy:
            continue
        name = _CODE_TO_NAME.get(m.group(3), f"other_{m.group(3).lower()}")
        result.setdefault(name, []).append(col)

    return result
