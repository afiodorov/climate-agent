"""DuckDB query layer over the climate project's published artefacts.

The climate pipeline emits flat tables, so a read-only SQL layer over them is
the whole query layer — no ingestion step. Everything is vendored into `data/`
so this repo has no dependency on a sibling checkout of the climate project:

- `rankings.csv`, `sensitivity.csv`, `sensitivity_summary.csv` — the published
  ranking, the 17-variant sweep, and Kendall's tau per variant.
- `agent/*.parquet` + `agent/manifest.json` — the pipeline's `export-agent`
  stage: the hourly cache re-aggregated into a UTCI histogram (by city, month,
  light and dew-point class), a month x hour-of-day profile, per-year totals
  and a few derived per-city columns. Small enough to vendor, rich enough that
  SQL can rebuild the ranking under a different comfort band, at night, or
  with a humidity filter.
- `methodology.md` — the pipeline's generated write-up, served by a tool.

All of `data/` must come from one pipeline run; `make data` copies it over.
"""

from __future__ import annotations

import json
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

AGENT_TABLES = ("utci_histogram", "hourly_profile", "yearly", "city_extras")

# The relations whose numbers are recomputed rather than published.
_RECOMPUTED_RELATIONS = re.compile(
    r"\b(utci_histogram|hourly_profile|yearly|comfort_weight|baseline_weight)\b",
    re.IGNORECASE,
)


def recomputes(sql: str) -> bool:
    """True when a statement rebuilds numbers from the aggregated hourly record."""
    return bool(_RECOMPUTED_RELATIONS.search(sql))


class QueryError(Exception):
    """Raised for SQL this layer refuses to run, or that DuckDB rejects."""


def out_dir() -> Path:
    return Path(os.environ.get("CLIMATE_OUT_DIR", _DEFAULT_OUT))


@lru_cache(maxsize=1)
def manifest() -> dict:
    """The export manifest, or {} when the agent tables are not vendored."""
    path = out_dir() / "agent" / "manifest.json"
    if not path.exists():
        return {}
    return json.loads(path.read_text())


def _band(m: dict) -> dict[str, float]:
    return dict(
        m.get("comfort", {}).get("band")
        or {"cold_zero": 3.0, "cold_full": 9.0, "warm_full": 26.0, "warm_zero": 32.0}
    )


@lru_cache(maxsize=1)
def _connection() -> duckdb.DuckDBPyConnection:
    d = out_dir()
    rankings, sensitivity = d / "rankings.csv", d / "sensitivity.csv"
    if not rankings.exists():
        raise QueryError(
            f"{rankings} not found. Set CLIMATE_OUT_DIR to the directory holding "
            "rankings.csv (and the rest of the pipeline's out/), or run `make data`."
        )
    con = duckdb.connect(":memory:")
    agent = d / "agent"
    extras = agent / "city_extras.parquet"
    if extras.exists():
        # The derived per-city columns are folded into `rankings` so the model
        # finds night and humidity numbers where it already looks.
        con.execute(
            "CREATE VIEW rankings AS SELECT r.*, x.* EXCLUDE (city_id) "
            f"FROM read_csv_auto('{rankings}') r "
            f"LEFT JOIN read_parquet('{extras}') x USING (city_id)"
        )
    else:
        con.execute(
            f"CREATE VIEW rankings AS SELECT * FROM read_csv_auto('{rankings}')"
        )
    if sensitivity.exists():
        con.execute(
            f"CREATE VIEW sensitivity AS SELECT * FROM read_csv_auto('{sensitivity}')"
        )
    summary = d / "sensitivity_summary.csv"
    if summary.exists():
        con.execute(
            f"CREATE VIEW sensitivity_summary AS SELECT * FROM read_csv_auto('{summary}')"
        )

    # The big parquet files become in-memory tables rather than views: a view
    # over read_parquet re-reads the file on every query, and the model asks
    # several per turn. Tens of MB in RAM, ~100 ms at boot.
    for name in ("utci_histogram", "hourly_profile", "yearly"):
        path = agent / f"{name}.parquet"
        if path.exists():
            con.execute(f"CREATE TABLE {name} AS SELECT * FROM read_parquet('{path}')")

    m = manifest()
    profiles = m.get("comfort", {}).get("profiles") or {}
    if profiles:
        rows = ", ".join(
            f"('{name}', {b['cold_zero']}, {b['cold_full']}, {b['warm_full']}, {b['warm_zero']})"
            for name, b in profiles.items()
        )
        con.execute(
            "CREATE TABLE comfort_profiles(profile VARCHAR, cold_zero DOUBLE, cold_full DOUBLE, "
            f"warm_full DOUBLE, warm_zero DOUBLE); INSERT INTO comfort_profiles VALUES {rows}"
        )
    if m:
        con.execute("CREATE TABLE scoring_config(name VARCHAR, value VARCHAR)")
        con.executemany(
            "INSERT INTO scoring_config VALUES (?, ?)",
            [
                (k, json.dumps(v) if not isinstance(v, str) else v)
                for k, v in _flatten(m).items()
            ],
        )

    # The comfort weight as SQL, created here rather than by the model: the
    # read-only guard refuses CREATE in anything it is handed.
    con.execute(
        "CREATE MACRO comfort_weight(u, cold_zero, cold_full, warm_full, warm_zero) AS "
        "CASE WHEN u IS NULL THEN 0.0 ELSE greatest(0.0, least(1.0, "
        "least((u - cold_zero) / (cold_full - cold_zero), "
        "(warm_zero - u) / (warm_zero - warm_full)))) END"
    )
    b = _band(m)
    con.execute(
        "CREATE MACRO baseline_weight(u) AS comfort_weight(u, "
        f"{b['cold_zero']}, {b['cold_full']}, {b['warm_full']}, {b['warm_zero']})"
    )
    return con


def _flatten(d: dict, prefix: str = "") -> dict:
    out: dict = {}
    for k, v in d.items():
        key = f"{prefix}{k}"
        if isinstance(v, dict):
            out.update(_flatten(v, key + "."))
        else:
            out[key] = v
    return out


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
        raise QueryError(
            "Only read-only SELECT and WITH statements are allowed; the words "
            "attach, copy, create, delete, detach, drop, export, insert, install, "
            "load, pragma, set, update and call are refused anywhere in the "
            "statement, comments included."
        )

    log.debug("sql: %s", flat)
    started = time.perf_counter()
    try:
        # A cursor is a second connection to the same in-memory database. The
        # model issues tool calls in parallel, and two executes on one
        # connection from two threads hand one of them the other's result set.
        with _connection().cursor() as cur:
            cur.execute(sql)
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


# --- Facts about the data, for prompts and caveats ---------------------------


def _scalar(sql: str, default=None):
    try:
        row = _connection().execute(sql).fetchone()
    except (QueryError, duckdb.Error):
        return default
    return row[0] if row else default


@lru_cache(maxsize=1)
def counts() -> dict:
    """The numbers the prompt and the caveats quote, read rather than typed."""
    m = manifest()
    period = m.get("period", {})
    return {
        "n_cities": _scalar("SELECT count(*) FROM rankings", 1118),
        "n_ranked": _scalar(
            "SELECT count(*) FROM rankings WHERE rank IS NOT NULL", 1114
        ),
        "n_flagged": _scalar(
            "SELECT count(*) FROM rankings WHERE microclimate_risk", 578
        ),
        "n_variants": _scalar(
            "SELECT count(*) FROM sensitivity_summary WHERE variant <> 'baseline'", 16
        )
        + 1,
        "start_year": period.get("start_year", 2010),
        "end_year": period.get("end_year", 2024),
        "generated_on": m.get("generated_on"),
        "band": _band(m),
        "profile": m.get("comfort", {}).get("profile", "walking"),
        "has_agent_tables": bool(m),
    }


@lru_cache(maxsize=1)
def sensitivity_summary() -> dict[str, float]:
    """Kendall's tau against the baseline, keyed by variant. Empty if absent."""
    try:
        cur = _connection().execute(
            "SELECT variant, kendall_tau_vs_baseline FROM sensitivity_summary"
        )
    except (QueryError, duckdb.Error):
        return {}
    return {row[0]: float(row[1]) for row in cur.fetchall()}


def methodology(section: str = "") -> str:
    """The pipeline's generated write-up, whole or one `## section`."""
    path = out_dir() / "methodology.md"
    if not path.exists():
        return "No methodology document is vendored with this data."
    text = path.read_text()
    if not section.strip():
        return text
    wanted = section.strip().lower()
    parts = re.split(r"(?m)^(?=## )", text)
    for part in parts:
        heading = (
            part.splitlines()[0].lstrip("# ").strip().lower() if part.strip() else ""
        )
        if wanted in heading:
            return part.strip()
    headings = [
        p.splitlines()[0].lstrip("# ").strip() for p in parts if p.startswith("## ")
    ]
    return f"No section matching {section!r}. Sections: {', '.join(headings)}."


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


# --- The schema the model reads ----------------------------------------------

# Hand-written meaning per column. The column *lists* come from DuckDB at
# runtime so a regenerated data/ cannot drift from this text; only the prose
# is maintained by hand.
NOTES: dict[str, dict[str, str]] = {
    "rankings": {
        "rank": "1 = most comfortable. NULL for reference cities.",
        "rank_if_eligible": "rank the city would hold if the 500k population floor were dropped",
        "microclimate_risk": "BOOLEAN. True when the ERA5 grid cell probably does not represent the city (coast or steep relief).",
        "microclimate_reason": "'coastal', 'relief', or 'coastal+relief'",
        "is_reference": "BOOLEAN. True for sub-500k cities shown for comparison only.",
        "comfort_hours_yr": "THE HEADLINE METRIC: daylight hours per year in the comfort band (baseline band, half-sun exposure, rain-adjusted)",
        "comfort_fraction": "comfort_hours_yr / daylight_hours_yr",
        "worst_month_hours": "the lowest of the 12 month_XX_hours",
        "evenness_factor": "0-1, 1 = comfort spread evenly across the year. 1 - (stddev / mean) of the 12 monthly totals, clamped at 0",
        "longest_bad_streak_days": "longest run of consecutive days with under 1 comfortable hour, over the whole record",
        "utci_mean_daylight_c": "mean UTCI over daylight hours, degrees C",
        "comfort_hours_sun": "comfort hours assuming full sun exposure",
        "comfort_hours_shade": "comfort hours assuming full shade",
        "elev_offset_k": "lapse-rate correction applied, kelvin",
        "pm25_ugm3": "CAMS 2021-2023 mean PM2.5",
        "aq_factor": "the air-quality multiplier derived from pm25_ugm3 (1 = no penalty, floor 0.25)",
        "month_01_hours": "comfort hours in January; month_02_hours .. month_12_hours likewise",
        "composite": "comfort_hours_yr * evenness_factor * aq_factor. Drives `rank`.",
        "comfort_hours_night_yr": "comfortable hours per year after dark (solar elevation <= -6 deg), baseline band",
        "comfort_hours_24h_yr": "comfortable hours per year over all 24 hours, i.e. comfort_hours_yr + comfort_hours_night_yr",
        "night_hours_yr": "hours per year that count as night",
        "dewpoint_mean_daylight_c": "mean dew point over daylight hours, degrees C. Under 10 is dry, 16-18 humid, 18-21 muggy, 21+ oppressive",
        "rh_mean_daylight": "mean relative humidity over daylight hours, 0-1",
        "muggy_daylight_hours_yr": "daylight hours per year with dew point >= 18 C",
        "comfort_hours_dry_yr": "comfort_hours_yr counting only hours with dew point < 16 C: comfortable AND not humid",
    },
    "sensitivity": {
        "baseline": "the city's rank under the published scoring. Each other variant column is its rank under that one change.",
        "rank_volatility": "spread of rank across the variants. High = the answer depends on which scoring choices you accept.",
        "rank_median": "median rank across the variants",
    },
    "sensitivity_summary": {
        "variant": "one row per sweep variant",
        "kendall_tau_vs_baseline": "rank agreement with the baseline, 1 = identical ordering",
    },
    "utci_histogram": {
        "month": "calendar month, local time, 1-12",
        "light": "'day' (sun above the horizon), 'twilight' (civil twilight, -6..0 deg) or 'night'. light IN ('day','twilight') is exactly the daylight the published metrics count.",
        "dewpoint_class": "'dry' (<10 C), 'mild' (10-16), 'humid' (16-18), 'muggy' (18-21), 'oppressive' (>=21)",
        "utci_bin": "integer degrees C; the bin holds hours with UTCI in [utci_bin, utci_bin+1)",
        "hours": "hours per year in this cell",
        "hours_rain_adj": "the same hours after the rain penalty (x0.3 light rain, x0 heavy). Multiply THIS by a comfort weight.",
        "utci_mean_c": "rain-weighted mean UTCI of the hours in the cell. SUM(hours_rain_adj * comfort_weight(utci_mean_c, ...)) reproduces the published comfort hours exactly for any whole-degree band.",
        "dewpoint_mean_c": "mean dew point of the hours in the cell",
    },
    "hourly_profile": {
        "hour_local": "local wall-clock hour, 0-23",
        "hours": "hours per year in this month-hour cell (about 30)",
        "day_hours": "of those, hours with the sun up; twilight_hours and night_hours likewise",
        "utci_mean_c": "mean UTCI; utci_p10_c and utci_p90_c are the 10th and 90th percentiles",
        "dewpoint_mean_c": "mean dew point, degrees C",
        "rh_mean": "mean relative humidity, 0-1",
        "muggy_hours": "hours per year with dew point >= 18 C",
        "comfort_hours_all": "comfortable hours per year in this cell, day or night, baseline band",
        "comfort_hours": "the same counting daylight only (sums to rankings.comfort_hours_yr)",
        "comfort_hours_sun": "daylight comfort hours at full sun; comfort_hours_shade at full shade",
    },
    "yearly": {
        "year": "calendar year, local time",
        "hours": "hours in the record that year",
        "comfort_hours": "daylight comfort hours that year; comfort_hours_all includes the night",
        "utci_mean_daylight_c": "mean daylight UTCI that year",
        "muggy_daylight_hours": "daylight hours with dew point >= 18 C that year",
    },
    "comfort_profiles": {
        "profile": "'walking' (the baseline), 'sitting', 'running'; the four knots of each trapezoid",
    },
    "scoring_config": {
        "name": "every knob of the pipeline run, dotted (comfort.band.cold_full, exposure.sun_fraction, period.start_year, generated_on, ...)",
    },
}

_TABLE_INTRO = {
    "rankings": "one row per city. The published numbers: read these first, and always for anything they already answer.",
    "sensitivity": 'one row per city: the rank recomputed under {n_variants} scoring variants (band_warm_+2C, band_cool_-2C, daylight_sunrise_0deg, aq_penalty_off, rain_penalty_off, evenness_shannon, elevation_correction_off, profile_sitting, profile_running, exposure_0/0.25/0.75/1, metric_fraction, metric_raw_hours, metric_worst_month). Columns with non-identifier characters need double quotes: "band_warm_+2C".',
    "sensitivity_summary": "one row per variant: how much the whole ranking moved.",
    "utci_histogram": "the hourly record, aggregated: one row per city x month x light x dewpoint_class x 1 C UTCI bin, hours per year. Rebuilds the ranking under ANY whole-degree comfort band, by day or by night, with or without a humidity filter.",
    "hourly_profile": "one row per city x month x local hour: what a typical hour of that month is like. Answers 'best time of day', 'are evenings pleasant', diurnal shape.",
    "yearly": "one row per city x year: year-to-year variability of the record ({start_year}-{end_year}). A handful of points, not a trend analysis.",
    "comfort_profiles": "the trapezoid knots of the named activity profiles.",
    "scoring_config": "name/value pairs describing the run that produced all of the above.",
}


def _describe(table: str) -> list[tuple[str, str]]:
    try:
        rows = _connection().execute(f"DESCRIBE {table}").fetchall()
    except (QueryError, duckdb.Error):
        return []
    return [(r[0], r[1]) for r in rows]


def _render_table(table: str, c: dict) -> str:
    columns = _describe(table)
    if not columns:
        return ""
    notes = NOTES.get(table, {})
    lines = [f"{table} — {_TABLE_INTRO[table].format(**c)}"]
    plain: list[str] = []
    seen_month = False
    for name, _ in columns:
        if re.fullmatch(r"month_(0[2-9]|1[0-2])_hours", name):
            continue  # month_01_hours' note covers them
        if name in notes:
            if plain:
                lines.append("  " + ", ".join(plain))
                plain = []
            lines.append(f"  {name:<24s} {notes[name]}")
            seen_month = seen_month or name == "month_01_hours"
        else:
            plain.append(name)
    if plain:
        lines.append("  " + ", ".join(plain))
    return "\n".join(lines)


_RECIPES = """\
Macros (already defined, use them in SELECT):
  comfort_weight(utci, cold_zero, cold_full, warm_full, warm_zero) -> 0..1, the trapezoid
  baseline_weight(utci) -> comfort_weight with the baseline band ({cold_zero}/{cold_full}/{warm_full}/{warm_zero} C, '{profile}')

Recipes:

-- (a) Rank a country under a custom band (here 2 C warmer than baseline), composite rebuilt.
--     Whole-degree knots are exact; fractional knots are within ~0.5%. Fill all 12 months
--     before evenness: polar cities have months with no daylight rows.
WITH monthly AS (
  SELECT city_id, month, SUM(hours_rain_adj * comfort_weight(utci_mean_c, {cz2}, {cf2}, {wf2}, {wz2})) AS comfort
  FROM utci_histogram WHERE light IN ('day', 'twilight') GROUP BY 1, 2),
filled AS (
  SELECT r.city_id, m.month, COALESCE(x.comfort, 0) AS comfort
  FROM rankings r CROSS JOIN range(1, 13) AS m(month)
  LEFT JOIN monthly x ON x.city_id = r.city_id AND x.month = m.month
  WHERE r.country = 'United States' AND r.rank IS NOT NULL),
city AS (
  SELECT city_id, SUM(comfort) AS comfort_hours_yr, MIN(comfort) AS worst_month_hours,
         greatest(0, 1 - stddev_pop(comfort) / NULLIF(avg(comfort), 0)) AS evenness_factor
  FROM filled GROUP BY 1)
SELECT r.name, r.rank AS published_rank, r.comfort_hours_yr AS published_hours,
       c.comfort_hours_yr, c.worst_month_hours,
       c.comfort_hours_yr * c.evenness_factor * r.aq_factor AS composite
FROM city c JOIN rankings r USING (city_id) ORDER BY composite DESC LIMIT 20;

-- (b) A night-time index: comfortable hours after dark, baseline band.
SELECT r.name, r.country, r.comfort_hours_night_yr, r.night_hours_yr, r.comfort_hours_yr
FROM rankings r WHERE r.rank IS NOT NULL ORDER BY comfort_hours_night_yr DESC LIMIT 15;
-- or by month / custom band from the histogram:
SELECT h.month, SUM(h.hours_rain_adj * baseline_weight(h.utci_mean_c)) AS night_comfort
FROM utci_histogram h JOIN rankings r USING (city_id)
WHERE r.name = 'Miami' AND h.light = 'night' GROUP BY 1 ORDER BY 1;

-- (c) Best time of day: Miami in July, hour by hour (24 rows).
SELECT hour_local, round(utci_mean_c, 1) AS utci_c, round(utci_p90_c, 1) AS utci_p90_c,
       round(comfort_hours_all / hours, 2) AS share_of_days_comfortable,
       round(dewpoint_mean_c, 1) AS dewpoint_c
FROM hourly_profile p JOIN rankings r USING (city_id)
WHERE r.name = 'Miami' AND p.month = 7 ORDER BY 1;

-- (d) Comfortable year-round AND not humid: daylight comfort with dew point under 16 C,
--     ranked by the worst month so 'year-round' means the floor, not the total.
WITH monthly AS (
  SELECT city_id, month, SUM(hours_rain_adj * baseline_weight(utci_mean_c)) AS dry_comfort
  FROM utci_histogram
  WHERE light IN ('day', 'twilight') AND dewpoint_class IN ('dry', 'mild') GROUP BY 1, 2),
filled AS (
  SELECT r.city_id, m.month, COALESCE(x.dry_comfort, 0) AS dry_comfort
  FROM rankings r CROSS JOIN range(1, 13) AS m(month)
  LEFT JOIN monthly x ON x.city_id = r.city_id AND x.month = m.month WHERE r.rank IS NOT NULL)
SELECT r.name, r.country, round(SUM(f.dry_comfort)) AS dry_comfort_hours_yr,
       round(MIN(f.dry_comfort)) AS worst_month, round(r.dewpoint_mean_daylight_c, 1) AS dewpoint_c,
       round(r.muggy_daylight_hours_yr) AS muggy_hours
FROM filled f JOIN rankings r USING (city_id) GROUP BY ALL ORDER BY worst_month DESC LIMIT 15;

What this data cannot answer: individual hours or dates (only climatological aggregates
{start_year}-{end_year}), anything after {end_year}, forecasts, a custom band restricted to one hour of the day
(the histogram has no hour; the profile has no bin), custom bands at full sun or full shade
(the histogram is at half-sun exposure; use sensitivity.exposure_* or the profile's sun/shade
columns), streaks other than the published longest_bad_streak_days, cities not in the list.
Night-time 'shade' is not meaningful and is not offered. Humidity is ERA5's 2 m dew point over a
~31 km cell, so coastal and lakeside cities can be more humid than their cell."""


@lru_cache(maxsize=1)
def schema() -> str:
    """What the model is told about the data. Rendered from DuckDB + NOTES."""
    c = counts()
    b = c["band"]
    header = (
        f"Data: {c['n_cities']} cities with population >= 500,000 ({c['n_ranked']} ranked, the rest "
        f"reference rows), UTCI computed hourly from ERA5 reanalysis {c['start_year']}-{c['end_year']}"
        + (f", exported {c['generated_on']}" if c["generated_on"] else "")
        + f". Baseline: '{c['profile']}' comfort band {b['cold_zero']:g}/{b['cold_full']:g}/"
        f"{b['warm_full']:g}/{b['warm_zero']:g} C (zero / full / full / zero comfort, linear between), "
        "half-sun exposure, daylight = solar elevation above -6 deg, rain-penalised hours, "
        "PM2.5 as a city-level multiplier."
    )
    tables = [
        _render_table(t, c)
        for t in (
            "rankings",
            "sensitivity",
            "sensitivity_summary",
            "utci_histogram",
            "hourly_profile",
            "yearly",
            "comfort_profiles",
            "scoring_config",
        )
    ]
    tables = [t for t in tables if t]
    if not tables:  # no data on disk: the notes alone, so the prompt still reads
        tables = [
            f"{name} — " + "; ".join(f"{k}: {v}" for k, v in notes.items())
            for name, notes in NOTES.items()
        ]
    parts = [header, "\n\n".join(tables)]
    if c["has_agent_tables"]:
        parts.append(
            _RECIPES.format(
                cold_zero=b["cold_zero"],
                cold_full=b["cold_full"],
                warm_full=b["warm_full"],
                warm_zero=b["warm_zero"],
                cz2=b["cold_zero"] + 2,
                cf2=b["cold_full"] + 2,
                wf2=b["warm_full"] + 2,
                wz2=b["warm_zero"] + 2,
                profile=c["profile"],
                start_year=c["start_year"],
                end_year=c["end_year"],
            )
        )
    return "\n\n".join(parts) + "\n"
