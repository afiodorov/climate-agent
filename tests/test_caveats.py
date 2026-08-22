import pytest

from climate_agent import caveats, query

pytestmark = pytest.mark.skipif(
    not (query.out_dir() / "rankings.csv").exists(), reason="climate out/ not built"
)


def test_finds_city_names_in_prose():
    found = caveats.cities_mentioned("Between Porto and Lima, Porto is steadier.")
    assert found == ["Porto", "Lima"]  # deduplicated, in order of first appearance


def test_ignores_ordinary_words():
    assert caveats.cities_mentioned("It is comfortable most of the year.") == []


def test_flags_microclimate_risk():
    notes = caveats.caveats_for("Lima ranks first on comfort hours.")
    assert any("Microclimate risk" in n for n in notes)


def test_flags_unstable_rank():
    # Lima's rank is the pipeline's documented instability case.
    notes = caveats.caveats_for("Lima ranks first on comfort hours.")
    assert any("unstable" in n for n in notes)


def test_flags_reference_cities():
    notes = caveats.caveats_for("Funchal looks excellent.")
    assert any("population floor" in n for n in notes)


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


@pytest.mark.parametrize(
    "text",
    [
        "Porto is mild in February.",
        # Column names, not claims.
        "Porto's worst month is January and its best month is July.",
        # The answer already explained the metric choice; repeating it is noise.
        "Tijuana leads on raw hours; Lima ranks first on the composite.",
    ],
)
def test_stays_quiet_when_ambiguity_note_would_be_noise(text):
    assert not _metric_note(text)


def test_quiet_when_nothing_applies():
    assert caveats.caveats_for("I need a city name to answer that.") == []
