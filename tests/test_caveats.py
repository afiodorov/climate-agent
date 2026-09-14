import pytest
from conftest import flagged_city, reference_city, unstable_city

from climate_agent import caveats, query

pytestmark = pytest.mark.skipif(
    not (query.out_dir() / "rankings.csv").exists(), reason="climate out/ not built"
)


def test_finds_city_names_in_prose():
    a, b = list(query.city_index())[:2]
    found = caveats.cities_mentioned(f"Between {a} and {b}, {a} is steadier.")
    assert found == [a, b]  # deduplicated, in order of first appearance


def test_ignores_ordinary_words():
    assert caveats.cities_mentioned("It is comfortable most of the year.") == []


def test_flags_microclimate_risk():
    notes = caveats.caveats_for(f"{flagged_city()} ranks first on comfort hours.")
    note = next(n for n in notes if "Microclimate risk" in n)
    c = query.counts()
    assert f"{c['n_flagged']} of the {c['n_cities']} cities" in note


def test_flags_unstable_rank():
    notes = caveats.caveats_for(f"{unstable_city()} ranks first on comfort hours.")
    assert any("unstable" in n for n in notes)


def test_flags_reference_cities():
    notes = caveats.caveats_for(f"{reference_city()} looks excellent.")
    assert any("population floor" in n for n in notes)


@pytest.mark.parametrize(
    "text",
    [
        "At night Sydney keeps 800 comfortable hours.",
        "Under a warmer band the list reorders.",
        "Evenings in July are the sweet spot.",
    ],
)
def test_flags_recomputed_figures(text):
    if not query.counts()["has_agent_tables"]:
        pytest.skip("agent tables not vendored")
    assert any("recomputed" in n for n in caveats.caveats_for(text))


def test_flags_humidity_claims():
    notes = caveats.caveats_for(
        "Its dew point stays under 16 C, so it is rarely muggy."
    )
    assert any("dew point" in n for n in notes)
    assert not any("dew point" in n for n in caveats.caveats_for("February is mild."))
    # A passing adjective is not a humidity claim.
    assert not any(
        "dew point" in n for n in caveats.caveats_for("Its humid summers are long.")
    )


def test_recomputed_note_follows_the_sql_when_given():
    if not query.counts()["has_agent_tables"]:
        pytest.skip("agent tables not vendored")
    published = ["SELECT name FROM rankings", 'SELECT "band_warm_+2C" FROM sensitivity']
    rebuilt = ["SELECT SUM(hours) FROM utci_histogram"]
    wording = "Under a warmer band the list reorders."
    assert not any(
        "recomputed" in n for n in caveats.caveats_for(wording, sql=published)
    )
    assert any("recomputed" in n for n in caveats.caveats_for("Here.", sql=rebuilt))


def _metric_note(text):
    return any('"Best" depends' in n for n in caveats.caveats_for(text))


@pytest.mark.parametrize(
    "text",
    [
        "The best city is Porto.",
        "Porto ranks 83rd.",
        "Tijuana leads on raw comfort hours.",
    ],
)
def test_flags_metric_ambiguity_on_ordering_claims(text):
    assert _metric_note(text)


def test_metric_note_quotes_the_measured_tau():
    tau = query.sensitivity_summary().get("metric_raw_hours")
    if tau is None:
        pytest.skip("sensitivity_summary.csv not vendored")
    note = next(
        n for n in caveats.caveats_for("The best city is Porto.") if "Best" in n
    )
    assert f"{tau:.2f}" in note


@pytest.mark.parametrize(
    "text",
    [
        "Porto is mild in February.",
        # Column names, not claims.
        "Porto's worst month is January and its best month is July.",
        # A time-of-day answer, not a ranking claim.
        "The best hour in Porto is 10:00; the worst time is dawn.",
        # The answer already explained the metric choice; repeating it is noise.
        "Tijuana leads on raw hours; Lima ranks first on the composite.",
    ],
)
def test_stays_quiet_when_ambiguity_note_would_be_noise(text):
    assert not _metric_note(text)


def test_quiet_when_nothing_applies():
    assert caveats.caveats_for("I need a city name to answer that.") == []
