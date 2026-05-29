"""
Geography level definitions and GEOID format helpers.

Census 2020 GEOID hierarchy (Georgia):
    state    →  2-char  "13"
    county   →  5-char  "13001"
    tract    →  11-char "13001950100"   (different from VTD!)
    VTD      →  11-char "13001000002"   SS+CCC+VVVVVV
    block    →  15-char "130010001001000"  SS+CCC+TTTTTT+BBBB

Block GEOID20 and VTD GEOID20 both use 15 and 11 chars respectively, but
the block encoding embeds tract+block, not VTD.  They CANNOT be related by
string truncation — a spatial join is required.
"""

from __future__ import annotations

from enum import Enum


class GeoLevel(str, Enum):
    """Geographic resolution levels supported by FDP."""

    BLOCK = "block"
    VTD = "vtd"
    PRECINCT = "precinct"
    COUNTY = "county"
    DISTRICT = "district"
    STATE = "state"

    def __str__(self) -> str:
        return self.value


# Expected GEOID20 string lengths by geography level
GEOID_LENGTH: dict[GeoLevel, int] = {
    GeoLevel.STATE:    2,
    GeoLevel.COUNTY:   5,
    GeoLevel.VTD:     11,   # SS+CCC+VVVVVV
    GeoLevel.BLOCK:   15,   # SS+CCC+TTTTTT+BBBB
}

# FIPS code for Georgia
GA_FIPS = "13"


def state_fips(state: str) -> str:
    """Return the 2-char FIPS code for a state abbreviation."""
    _MAP = {"GA": "13"}
    code = _MAP.get(state.upper())
    if code is None:
        raise ValueError(f"Unknown state abbreviation: {state!r}")
    return code


def validate_geoid(geoid: str, level: GeoLevel) -> bool:
    """Return True if geoid has the expected length for the given geography."""
    expected = GEOID_LENGTH.get(level)
    if expected is None:
        return True  # unknown level — skip check
    return len(geoid) == expected
