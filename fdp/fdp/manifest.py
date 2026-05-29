"""
FDP Dataset Manifest — PostgreSQL-backed registry of every processed dataset.

The manifest tracks what data has been ingested, at what geography level,
from what source, and where the output file lives.  It simulates INSERT,
DELETE, and UPSERT semantics over a file-based data store.

Connection
----------
The manifest connects to PostgreSQL via the DATABASE_URL environment variable
(standard PostgreSQL connection string).  All tables live in the ``fdp``
schema so this can share a database instance with other applications.

    export DATABASE_URL=postgresql://fdp:password@localhost:5432/fdp

For Supabase (hosted), use the pooler connection string from the project
settings dashboard.

Usage
-----
    from fdp.manifest import DataManifest, DatasetEntry

    manifest = DataManifest()            # reads DATABASE_URL from env
    manifest.register(DatasetEntry(
        id="ga_election_2022_general_block",
        category="election",
        geography="block",
        vintage=2022,
        state="GA",
        source="RDH",
        election_type="general",
        output_file="/path/to/parquet",
        row_count=232717,
        columns=["GEOID20", "VAP_MOD", "G22GOVDABR", ...],
    ))

    for entry in manifest.list(category="election", geography="vtd"):
        print(entry.id, entry.row_count)

    manifest.delete("ga_election_2022_general_block")

Direct SQL access
-----------------
    psql $DATABASE_URL
    SELECT id, category, geography, vintage, row_count, loaded_at
    FROM fdp.datasets
    ORDER BY category, vintage, geography;

Or point Looker Studio / Tableau / DBeaver at the same DATABASE_URL.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import psycopg


# ---------------------------------------------------------------------------
# DatasetEntry — the unit of registration
# ---------------------------------------------------------------------------

@dataclass
class DatasetEntry:
    """One row in the manifest datasets table."""

    id: str
    """Slug identifier, e.g. 'ga_election_2022_general_block'."""

    category: str
    """Data category: election | cvap | boundary | lookup | alarm_combined | demographic | ensemble."""

    geography: str
    """Geographic resolution: block | vtd | precinct | county | district | state."""

    output_file: str
    """Absolute path to the canonical output parquet/geojson."""

    state: str = "GA"
    """State abbreviation."""

    vintage: int | None = None
    """Election/data year, e.g. 2022."""

    source: str | None = None
    """Data provider: RDH | Census | VEST | ALARM | (derived)."""

    source_url: str | None = None
    """URL where raw data was downloaded from."""

    election_type: str | None = None
    """For elections: general | runoff | special | primary."""

    raw_file: str | None = None
    """Absolute path to the raw source file (zip/shp/csv) used for ingestion."""

    row_count: int | None = None
    """Number of rows in the output file."""

    columns: list[str] = field(default_factory=list)
    """Column names in the output file."""

    loaded_at: str = ""
    """ISO-8601 timestamp of when this entry was registered."""

    checksum: str | None = None
    """SHA-256 hex digest of raw_file, for provenance/change detection."""

    derived_from: list[str] = field(default_factory=list)
    """IDs of parent datasets this was aggregated/joined from."""

    notes: str | None = None
    """Free-form notes."""

    def __post_init__(self) -> None:
        if not self.loaded_at:
            self.loaded_at = datetime.now(timezone.utc).isoformat()

    def to_row(self) -> tuple:
        """Return a tuple matching the INSERT column order."""
        return (
            self.id,
            self.category,
            self.geography,
            self.vintage,
            self.state,
            self.source,
            self.source_url,
            self.election_type,
            self.raw_file,
            self.output_file,
            self.row_count,
            json.dumps(self.columns),
            self.loaded_at,
            self.checksum,
            json.dumps(self.derived_from),
            self.notes,
        )

    @classmethod
    def from_row(cls, row: tuple) -> "DatasetEntry":
        """Reconstruct from a DB row (same column order as to_row)."""
        (
            id_, category, geography, vintage, state, source, source_url,
            election_type, raw_file, output_file, row_count, columns_json,
            loaded_at, checksum, derived_json, notes,
        ) = row
        return cls(
            id=id_,
            category=category,
            geography=geography,
            vintage=vintage,
            state=state or "GA",
            source=source,
            source_url=source_url,
            election_type=election_type,
            raw_file=raw_file,
            output_file=output_file,
            row_count=row_count,
            columns=json.loads(columns_json) if columns_json else [],
            loaded_at=loaded_at or "",
            checksum=checksum,
            derived_from=json.loads(derived_json) if derived_json else [],
            notes=notes,
        )

    @property
    def output_path(self) -> Path:
        return Path(self.output_file)

    @property
    def raw_path(self) -> Path | None:
        return Path(self.raw_file) if self.raw_file else None

    @property
    def exists(self) -> bool:
        """True if the output_file is present on disk."""
        return Path(self.output_file).exists()


# ---------------------------------------------------------------------------
# DDL (idempotent — safe to re-run)
# ---------------------------------------------------------------------------

_DDL_SCHEMA = "CREATE SCHEMA IF NOT EXISTS fdp"

_DDL_TABLE = """
CREATE TABLE IF NOT EXISTS fdp.datasets (
    id             TEXT        PRIMARY KEY,
    category       TEXT        NOT NULL,
    geography      TEXT        NOT NULL,
    vintage        INTEGER,
    state          TEXT        DEFAULT 'GA',
    source         TEXT,
    source_url     TEXT,
    election_type  TEXT,
    raw_file       TEXT,
    output_file    TEXT        NOT NULL,
    row_count      INTEGER,
    columns_json   TEXT,
    loaded_at      TEXT,
    checksum       TEXT,
    derived_from   TEXT,
    notes          TEXT
)
"""

_DDL_INDEXES = [
    "CREATE INDEX IF NOT EXISTS datasets_category_idx      ON fdp.datasets (category)",
    "CREATE INDEX IF NOT EXISTS datasets_geography_idx     ON fdp.datasets (geography)",
    "CREATE INDEX IF NOT EXISTS datasets_state_vintage_idx ON fdp.datasets (state, vintage)",
    "CREATE INDEX IF NOT EXISTS datasets_election_type_idx ON fdp.datasets (election_type)",
]

_INSERT = """
INSERT INTO fdp.datasets (
    id, category, geography, vintage, state, source, source_url,
    election_type, raw_file, output_file, row_count, columns_json,
    loaded_at, checksum, derived_from, notes
) VALUES (
    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
)
ON CONFLICT (id) DO UPDATE SET
    category      = EXCLUDED.category,
    geography     = EXCLUDED.geography,
    vintage       = EXCLUDED.vintage,
    state         = EXCLUDED.state,
    source        = EXCLUDED.source,
    source_url    = EXCLUDED.source_url,
    election_type = EXCLUDED.election_type,
    raw_file      = EXCLUDED.raw_file,
    output_file   = EXCLUDED.output_file,
    row_count     = EXCLUDED.row_count,
    columns_json  = EXCLUDED.columns_json,
    loaded_at     = EXCLUDED.loaded_at,
    checksum      = EXCLUDED.checksum,
    derived_from  = EXCLUDED.derived_from,
    notes         = EXCLUDED.notes
"""

_SELECT_ALL = """
SELECT id, category, geography, vintage, state, source, source_url,
       election_type, raw_file, output_file, row_count, columns_json,
       loaded_at, checksum, derived_from, notes
FROM fdp.datasets
"""


# ---------------------------------------------------------------------------
# DataManifest
# ---------------------------------------------------------------------------

class DataManifest:
    """
    Registry of FDP datasets, backed by PostgreSQL.

    Parameters
    ----------
    db_url:
        PostgreSQL connection string.  Defaults to the ``DATABASE_URL``
        environment variable.  Raises RuntimeError if neither is provided.

    Examples
    --------
    ::

        # Typical usage — reads DATABASE_URL from environment
        manifest = DataManifest()

        # Explicit connection string (useful in tests)
        manifest = DataManifest(db_url="postgresql://fdp:pw@localhost:5432/fdp")
    """

    def __init__(self, db_url: str | None = None, fdp_root: str | Path | None = None) -> None:
        # fdp_root is accepted but no longer used for database location;
        # kept for backward compatibility with call sites that pass it.
        if db_url is None:
            db_url = os.environ.get("DATABASE_URL")
        if db_url is None:
            raise RuntimeError(
                "No PostgreSQL connection string found.\n"
                "Set the DATABASE_URL environment variable:\n"
                "  export DATABASE_URL=postgresql://fdp:password@localhost:5432/fdp\n"
                "Or pass db_url= explicitly."
            )
        self._db_url = db_url
        self._init_db()

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self._db_url)

    def _init_db(self) -> None:
        """Create the fdp schema and datasets table if they don't exist."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_DDL_SCHEMA)
                cur.execute(_DDL_TABLE)
                for idx_sql in _DDL_INDEXES:
                    cur.execute(idx_sql)
            conn.commit()

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------

    def register(self, entry: DatasetEntry) -> None:
        """
        Upsert a dataset entry (INSERT … ON CONFLICT DO UPDATE).

        If an entry with the same id already exists, all fields are updated.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_INSERT, entry.to_row())
            conn.commit()

    def delete(self, id: str) -> bool:
        """
        Remove a dataset from the manifest by id.

        Does NOT delete the output file from disk — only the registry entry.
        Returns True if an entry was deleted, False if id was not found.
        """
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM fdp.datasets WHERE id = %s", (id,))
                if cur.fetchone()[0] == 0:
                    return False
                cur.execute("DELETE FROM fdp.datasets WHERE id = %s", (id,))
            conn.commit()
        return True

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------

    def get(self, id: str) -> DatasetEntry | None:
        """Return the entry for the given id, or None if not found."""
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(_SELECT_ALL + " WHERE id = %s", (id,))
                rows = cur.fetchall()
        return DatasetEntry.from_row(rows[0]) if rows else None

    def find(
        self,
        category: str | None = None,
        geography: str | None = None,
        state: str | None = None,
        vintage: int | None = None,
        election_type: str | None = None,
    ) -> DatasetEntry | None:
        """
        Return the first matching entry, or None.

        Useful for looking up "the 2022 GA general election at VTD level."
        """
        results = self.list(
            category=category,
            geography=geography,
            state=state,
            vintage=vintage,
            election_type=election_type,
        )
        return results[0] if results else None

    def list(
        self,
        category: str | None = None,
        geography: str | None = None,
        state: str | None = None,
        vintage: int | None = None,
        election_type: str | None = None,
    ) -> list[DatasetEntry]:
        """
        Return all matching entries, ordered by vintage + category + geography.

        All filter parameters are optional; omit to return all entries.
        """
        clauses: list[str] = []
        params: list[Any] = []

        if category:
            clauses.append("category = %s")
            params.append(category)
        if geography:
            clauses.append("geography = %s")
            params.append(geography)
        if state:
            clauses.append("state = %s")
            params.append(state)
        if vintage is not None:
            clauses.append("vintage = %s")
            params.append(vintage)
        if election_type:
            clauses.append("election_type = %s")
            params.append(election_type)

        where = (" WHERE " + " AND ".join(clauses)) if clauses else ""
        order = " ORDER BY state, vintage, category, geography"
        sql = _SELECT_ALL + where + order

        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute(sql, params)
                rows = cur.fetchall()

        return [DatasetEntry.from_row(r) for r in rows]

    def all(self) -> list[DatasetEntry]:
        """Return all registered datasets."""
        return self.list()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @property
    def db_url(self) -> str:
        """Raw connection string (includes password — do not log)."""
        return self._db_url

    @property
    def db_url_display(self) -> str:
        """Connection URL with password masked — safe to print/log."""
        return re.sub(r":([^:@/][^@]*)@", ":***@", self._db_url)

    @property
    def db_path(self) -> str:
        """Alias for db_url_display for backward compatibility."""
        return self.db_url_display

    def __len__(self) -> int:
        with self._connect() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT COUNT(*) FROM fdp.datasets")
                return cur.fetchone()[0]

    def __repr__(self) -> str:
        return f"DataManifest(db={self.db_url_display}, entries={len(self)})"


# ---------------------------------------------------------------------------
# Standalone utilities
# ---------------------------------------------------------------------------

def file_checksum(path: Path | str, chunk_size: int = 1 << 20) -> str:
    """Return the SHA-256 hex digest of a file."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(chunk_size):
            h.update(chunk)
    return h.hexdigest()


def auto_id(
    state: str,
    category: str,
    vintage: int | None,
    election_type: str | None,
    geography: str,
    race: str | None = None,
) -> str:
    """
    Generate a canonical dataset ID slug (underscore-separated, Python/SQL safe).

    Field order: {state}_{year}_{election_type}_{race}_{category}_{geo}

    Examples
    --------
        auto_id("GA", "election", 2022, "general", "vtd")
            → "ga_2022_general_election_vtd"

        auto_id("GA", "election", 2024, "general", "vtd", race="president")
            → "ga_2024_general_president_vtd"

        auto_id("GA", "cvap", 2024, None, "vtd")
            → "ga_2024_cvap_vtd"

        auto_id("GA", "lookup", 2020, None, "block")
            → "ga_2020_lookup_block"
    """
    parts = [state.lower()]
    if vintage is not None:
        parts.append(str(vintage))
    if election_type:
        parts.append(election_type)
    if race:
        parts.append(race.lower())
    parts.append(category.lower())
    parts.append(geography.lower())
    return "_".join(parts)


def canonical_filename(
    state: str,
    category: str,
    vintage: int | None,
    election_type: str | None,
    geography: str,
    race: str | None = None,
    ext: str = ".parquet",
) -> str:
    """
    Generate a canonical output filename (hyphen-separated, filesystem friendly).

    Field order: {state}-{year}-{election_type}-{race}-{category}-{geo}.parquet

    Examples
    --------
        canonical_filename("GA", "election", 2022, "general", "block")
            → "ga-2022-general-election-block.parquet"

        canonical_filename("GA", "election", 2024, "general", "vtd", race="president")
            → "ga-2024-general-president-vtd.parquet"

        canonical_filename("GA", "cvap", 2024, None, "vtd")
            → "ga-2024-cvap-vtd.parquet"

        canonical_filename("GA", "alarm_combined", None, None, "vtd")
            → "ga-alarm-combined-vtd.parquet"
    """
    parts = [state.lower()]
    if vintage is not None:
        parts.append(str(vintage))
    if election_type:
        parts.append(election_type)
    if race:
        parts.append(race.lower())
    # "alarm_combined" → "alarm-combined"
    parts.append(category.lower().replace("_", "-"))
    parts.append(geography.lower())
    return "-".join(parts) + ext
