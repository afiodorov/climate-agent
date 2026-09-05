"""DuckDB query layer over the climate project's published artefacts.

The climate pipeline emits one flat table per artefact, so a read-only SQL view
over the CSVs is the whole query layer — no ingestion step, no schema drift.
The CSVs themselves are vendored into `data/` so this repo has no dependency on
a sibling checkout of the climate project.
"""

from __future__ import annotations

import logging
import os
import re
import time
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import duckdb

log = logging.getLogger(__name__)

_DEFAULT_OUT = Path(__file__).resolve().parents[2] / "data"

# Only reads. DuckDB can write files (COPY ... TO, EXPORT DATABASE) and load
# extensions, so the model-supplied SQL is checked against an allowlist of
# opening keywords plus a denylist of the statements that reach the filesystem.
_ALLOWED_START = re.compile(r"^\s*(select|with)\b", re.IGNORECASE)
_FORBIDDEN = re.compile(
    r"\b(attach|copy|create|delete|detach|drop|export|insert|install|load|"
    r"pragma|set|update|call)\b",
    re.IGNORECASE,
)

MAX_ROWS = 60

SCHEMA = """
Two views are available.

rankings — one row per city, 1118 rows.
  rank                    1 = most comfortable. NULL for reference cities.
  rank_if_eligible        rank the city would hold if the 500k population floor were dropped
  city_id, name, country, lat, lon, population, elevation_m, tz
  microclimate_risk       BOOLEAN. True when the ERA5 grid cell probably does not
                          represent the city (coast or steep relief). 578 of 1118 cities.
  microclimate_reason     'coastal', 'relief', or 'coastal+relief'
  is_reference            BOOLEAN. True for sub-500k cities shown for comparison only.
  coast_distance_km, relief_m, cell_elev_m, below_threshold
  comfort_hours_yr        THE HEADLINE METRIC: daylight hours per year in the comfort band
  daylight_hours_yr, comfort_fraction
  worst_month_hours, best_month_hours, peak_month
  evenness_stat, evenness_method, evenness_factor
  longest_bad_streak_days
  utci_mean_daylight_c    mean UTCI over daylight hours, degrees C
  comfort_hours_sun       comfort hours assuming full sun exposure
  comfort_hours_shade     comfort hours assuming full shade
  elev_offset_k           lapse-rate correction applied, kelvin
  pm25_ugm3, aq_factor    CAMS 2021-2023 mean PM2.5 and the derived penalty
  has_precip
  month_01_hours .. month_12_hours   comfort hours in each calendar month
  composite               comfort_hours_yr * evenness_factor * aq_factor. Drives `rank`.

sensitivity — one row per city, the same ranking recomputed under 17 variants.
  city_id, name, country
  baseline, band_warm_+2C, band_cool_-2C, daylight_sunrise_0deg, aq_penalty_off,
  rain_penalty_off, evenness_shannon, elevation_correction_off, profile_sitting,
  profile_running, exposure_0, exposure_0.25, exposure_0.75, exposure_1,
  metric_fraction, metric_raw_hours, metric_worst_month
      -- each column holds the city's rank under that variant
  rank_volatility         spread of rank across the variants. High = the answer
                          depends on which scoring choices you accept.
  rank_median

Columns with non-identifier characters need double quotes: "band_warm_+2C".
"""


class QueryError(Exception):
    """Raised for SQL this layer refuses to run, or that DuckDB rejects."""


def out_dir() -> Path:
    return Path(os.environ.get("CLIMATE_OUT_DIR", _DEFAULT_OUT))


@lru_cache(maxsize=1)
def _connection() -> duckdb.DuckDBPyConnection:
    d = out_dir()
    rankings, sensitivity = d / "rankings.csv", d / "sensitivity.csv"
    if not rankings.exists():
        raise QueryError(
            f"{rankings} not found. Set CLIMATE_OUT_DIR to the directory holding "
            "rankings.csv (and sensitivity.csv), or copy them into ./data."
        )
    con = duckdb.connect(":memory:")
    con.execute(f"CREATE VIEW rankings AS SELECT * FROM read_csv_auto('{rankings}')")
    if sensitivity.exists():
        con.execute(
            f"CREATE VIEW sensitivity AS SELECT * FROM read_csv_auto('{sensitivity}')"
        )
    return con


@dataclass(frozen=True)
class QueryResult:
    """Rows as DuckDB returned them, before any rendering.

    `run_sql` renders this as text for the model's tool result; the agent-facing
    HTTP and MCP surface hands it out as JSON instead. Same query, same cap on
    rows, two shapes.
    """

    columns: list[str]
    rows: list[list[object]]
    truncated: bool


def run_query(sql: str) -> QueryResult:
    """Run a read-only SELECT and return at most `MAX_ROWS` rows.

    Everything asked for is logged at DEBUG, including the queries this refuses
    to run — watching the SQL is the cheapest way to see what a caller actually
    believes about the schema. `LOG_LEVEL=DEBUG` turns it on.
    """
    flat = " ".join(sql.split())
    if not _ALLOWED_START.match(sql) or _FORBIDDEN.search(sql):
        log.debug("sql REFUSED (not read-only): %s", flat)
        raise QueryError("Only read-only SELECT and WITH statements are allowed.")

    log.debug("sql: %s", flat)
    started = time.perf_counter()
    try:
        cur = _connection().execute(sql)
        columns = [c[0] for c in cur.description]
        rows = cur.fetchmany(MAX_ROWS + 1)
    except duckdb.Error as exc:
        log.debug(
            "sql FAILED after %.0fms: %s", (time.perf_counter() - started) * 1e3, exc
        )
        raise QueryError(str(exc)) from exc

    truncated = len(rows) > MAX_ROWS
    log.debug(
        "sql -> %d row%s%s in %.0fms",
        min(len(rows), MAX_ROWS),
        "" if len(rows) == 1 else "s",
        " (truncated)" if truncated else "",
        (time.perf_counter() - started) * 1e3,
    )
    return QueryResult(columns, [list(r) for r in rows[:MAX_ROWS]], truncated)


def run_sql(sql: str) -> str:
    """`run_query`, rendered as the markdown-ish table the model reads."""
    result = run_query(sql)
    if not result.rows:
        return "(no rows)"

    lines = [" | ".join(result.columns)]
    for row in result.rows:
        lines.append(" | ".join("" if v is None else _fmt(v) for v in row))
    if result.truncated:
        lines.append(f"... truncated at {MAX_ROWS} rows; add LIMIT or aggregate.")
    return "\n".join(lines)


def _fmt(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.4g}"
    return str(value)


@lru_cache(maxsize=1)
def city_index() -> dict[str, dict]:
    """Every city keyed by name, for callers that need facts without writing SQL."""
    cur = _connection().execute(
        "SELECT name, country, rank, microclimate_risk, microclimate_reason, "
        "is_reference, comfort_hours_yr FROM rankings"
    )
    columns = [c[0] for c in cur.description]
    return {row[0]: dict(zip(columns, row)) for row in cur.fetchall()}


@lru_cache(maxsize=1)
def volatility_index() -> dict[str, dict]:
    """Rank volatility keyed by city name. Empty if sensitivity.csv is absent."""
    try:
        cur = _connection().execute(
            "SELECT name, rank_volatility, rank_median, metric_raw_hours, "
            "metric_worst_month FROM sensitivity"
        )
    except duckdb.Error:
        return {}
    columns = [c[0] for c in cur.description]
    return {row[0]: dict(zip(columns, row)) for row in cur.fetchall()}
