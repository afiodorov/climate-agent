import pytest
from conftest import flagged_city, needs_agent_tables, needs_data

from climate_agent import query


@pytest.mark.parametrize(
    "sql",
    [
        "DROP VIEW rankings",
        "CREATE TABLE t AS SELECT 1",
        "COPY (SELECT 1) TO '/tmp/x.csv'",
        "INSTALL httpfs",
        "  update rankings set rank = 1",
        "SELECT 1; DROP VIEW rankings",  # trailing statement still trips the denylist
    ],
)
def test_rejects_writes(sql):
    with pytest.raises(query.QueryError):
        query.run_sql(sql)


@needs_data
def test_select_returns_a_table():
    out = query.run_sql("SELECT name, rank FROM rankings ORDER BY rank LIMIT 3")
    assert out.splitlines()[0] == "name | rank"
    assert len(out.splitlines()) == 4


@needs_data
def test_truncates_long_results():
    out = query.run_sql("SELECT name FROM rankings CROSS JOIN range(100)")
    assert "truncated" in out.splitlines()[-1]


@needs_data
def test_bad_sql_surfaces_as_query_error():
    with pytest.raises(query.QueryError):
        query.run_sql("SELECT no_such_column FROM rankings")


@needs_data
def test_logs_the_sql_and_the_row_count(caplog):
    with caplog.at_level("DEBUG", logger="climate_agent.query"):
        query.run_sql("SELECT name\n  FROM rankings\n  LIMIT 2")
    messages = [r.getMessage() for r in caplog.records]
    # Whitespace is flattened so a multi-line query stays one log line.
    assert any("sql: SELECT name FROM rankings LIMIT 2" in m for m in messages)
    assert any("sql -> 2 rows in" in m for m in messages)


@needs_data
def test_logs_refusals_and_failures(caplog):
    with caplog.at_level("DEBUG", logger="climate_agent.query"):
        with pytest.raises(query.QueryError):
            query.run_sql("DROP VIEW rankings")
        with pytest.raises(query.QueryError):
            query.run_sql("SELECT nope FROM rankings")
    messages = [r.getMessage() for r in caplog.records]
    assert any("REFUSED" in m for m in messages)
    assert any("FAILED" in m for m in messages)


@needs_data
def test_indexes_are_keyed_by_city_name():
    city = flagged_city()
    assert query.city_index()[city]["country"]
    assert query.volatility_index()[city]["rank_volatility"] >= 0


@needs_data
def test_comfort_weight_macro_is_the_trapezoid():
    out = query.run_query(
        "SELECT comfort_weight(x, 3, 9, 26, 32) FROM (VALUES (0.0), (6.0), (15.0), (29.0), (40.0), (NULL)) t(x)"
    )
    assert [r[0] for r in out.rows] == [0.0, 0.5, 1.0, 0.5, 0.0, 0.0]


@needs_data
def test_schema_names_every_column_of_every_relation():
    text = query.schema()
    for relation in ("rankings", "sensitivity"):
        for name, _ in query._describe(relation):
            if not name.startswith("month_"):
                assert name in text, (relation, name)
    assert "month_01_hours" in text
    assert str(query.counts()["n_cities"]) in text


@needs_data
def test_counts_come_from_the_data():
    c = query.counts()
    assert c["n_cities"] == query.run_query("SELECT count(*) FROM rankings").rows[0][0]
    assert (
        c["n_flagged"]
        == query.run_query(
            "SELECT count(*) FROM rankings WHERE microclimate_risk"
        ).rows[0][0]
    )


@needs_agent_tables
def test_histogram_reproduces_the_published_comfort_hours():
    out = query.run_query(
        "SELECT max(abs(r.comfort_hours_yr - x.rebuilt)) FROM rankings r JOIN ("
        "  SELECT city_id, SUM(hours_rain_adj * baseline_weight(utci_mean_c)) AS rebuilt"
        "  FROM utci_histogram WHERE light IN ('day', 'twilight') GROUP BY 1) x USING (city_id)"
    )
    assert out.rows[0][0] < 0.01  # float32 storage


@needs_agent_tables
def test_profile_sums_to_the_published_sun_and_shade_columns():
    out = query.run_query(
        "SELECT max(abs(r.comfort_hours_sun - p.sun)), max(abs(r.comfort_hours_shade - p.shade)),"
        " max(abs(r.comfort_hours_yr - p.day))"
        " FROM rankings r JOIN (SELECT city_id, SUM(comfort_hours_sun) AS sun,"
        " SUM(comfort_hours_shade) AS shade, SUM(comfort_hours) AS day"
        " FROM hourly_profile GROUP BY 1) p USING (city_id)"
    )
    assert all(v < 0.01 for v in out.rows[0])


@needs_agent_tables
def test_extras_are_folded_into_rankings_and_add_up():
    out = query.run_query(
        "SELECT max(abs(comfort_hours_24h_yr - comfort_hours_yr - comfort_hours_night_yr)),"
        " min(comfort_hours_dry_yr <= comfort_hours_yr + 1e-3) FROM rankings"
    )
    assert out.rows[0][0] < 0.01
    assert out.rows[0][1] is True


@needs_agent_tables
def test_config_tables_carry_the_band():
    rows = query.run_query(
        "SELECT profile, cold_full FROM comfort_profiles ORDER BY 1"
    ).rows
    assert ("walking", query.counts()["band"]["cold_full"]) in [tuple(r) for r in rows]
    names = {r[0] for r in query.run_query("SELECT name FROM scoring_config").rows}
    assert {"generated_on", "period.start_year", "comfort.band.cold_full"} <= names


@needs_agent_tables
@pytest.mark.parametrize(
    "sql",
    [
        "SELECT hour_local, comfort_hours_all FROM hourly_profile WHERE month = 7 LIMIT 3",
        "SELECT light, dewpoint_class, SUM(hours) FROM utci_histogram GROUP BY ALL",
        "SELECT year, comfort_hours FROM yearly LIMIT 3",
        "SELECT baseline_weight(20.0)",
    ],
)
def test_new_relations_pass_the_read_only_guard(sql):
    assert query.run_query(sql).columns


@needs_data
def test_methodology_can_be_read_by_section():
    whole = query.methodology()
    part = query.methodology("sensitivity")
    assert part.startswith("## ")
    assert "ensitivity" in part.splitlines()[0]
    assert len(part) < len(whole)
    assert "No section" in query.methodology("no such heading")
