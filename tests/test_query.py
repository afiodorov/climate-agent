import pytest

from climate_agent import query

has_data = (query.out_dir() / "rankings.csv").exists()
needs_data = pytest.mark.skipif(has_data is False, reason="climate out/ not built")


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
    out = query.run_sql("SELECT name FROM rankings")
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
    assert query.city_index()["Lima"]["country"] == "Peru"
    assert query.volatility_index()["Lima"]["rank_volatility"] >= 0
