from conftest import needs_data

from climate_agent import glossary, query

pytestmark = needs_data


def test_every_entry_is_complete():
    seen_terms: set[str] = set()
    seen_aliases: set[str] = set()
    for entry in glossary.glossary():
        assert entry["term"] not in seen_terms
        seen_terms.add(entry["term"])
        assert entry["aliases"], entry["term"]
        for alias in entry["aliases"]:
            assert alias.lower() not in seen_aliases, alias
            seen_aliases.add(alias.lower())
        assert entry["definition"].endswith("."), entry["term"]
        assert "{" not in entry["definition"], entry["term"]  # no unformatted field


def test_columns_exist_in_the_views():
    columns = {
        row[0]
        for view in ("rankings", "sensitivity")
        for row in query._connection().execute(f"DESCRIBE {view}").fetchall()
    }
    for entry in glossary.glossary():
        if entry["column"] is not None:
            assert entry["column"] in columns, entry["term"]


def test_numbers_come_from_the_data():
    c = query.counts()
    by_term = {e["term"]: e["definition"] for e in glossary.glossary()}
    assert f"{c['min_population']:,}" in by_term["reference city"]
    assert f"{c['start_year']}–{c['end_year']}" in by_term["longest bad streak"]
    assert f"{c['n_variants']} variants" in by_term["rank volatility"]
