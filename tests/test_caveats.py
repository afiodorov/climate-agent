import pytest
from conftest import flagged_city, ranked_reference_city, reference_city, unstable_city

from climate_agent import caveats, query

pytestmark = pytest.mark.skipif(
    not (query.out_dir() / "rankings.csv").exists(), reason="climate out/ not built"
)


def test_finds_city_names_in_prose():
    a, b = list(query.city_index())[:2]
    found = caveats.cities_mentioned(f"Between {a} and {b}, {a} is steadier.")
    assert found == [a, b]  # deduplicated, in order of first appearance


def test_finds_one_half_of_a_bilingual_name():
    bilingual = [n for n in query.city_index() if " / " in n]
    if not bilingual:
        pytest.skip("no bilingual city names in this run")
    name = bilingual[0]
    first = name.split(" / ")[0]
    assert caveats.cities_mentioned(f"{first} is mild all year.") == [name]


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


def test_a_ranked_yardstick_city_is_not_called_unranked():
    # Las Palmas: on the always-include list, but above the floor and ranked.
    notes = caveats.caveats_for(f"{ranked_reference_city()} looks excellent.")
    assert not any("no rank" in n for n in notes)


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


def test_trend_note_follows_reading_individual_years():
    if not query.counts()["has_agent_tables"]:
        pytest.skip("agent tables not vendored")

    def trend(sql):
        return any(
            "short for a trend" in n for n in caveats.caveats_for("Here.", sql=sql)
        )

    assert trend(["SELECT year, comfort_hours FROM monthly"])
    assert trend(["SELECT * FROM yearly"])
    assert not trend(["SELECT SUM(hours) FROM utci_histogram"])
    assert not any(
        "recomputed" in n
        for n in caveats.caveats_for("Here.", sql=["SELECT * FROM yearly"])
    )


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


def test_averaging_monthly_over_years_is_not_a_trend():
    if not query.counts()["has_agent_tables"]:
        pytest.skip("agent tables not vendored")
    sql = ["SELECT month, avg(comfort_hours) FROM monthly GROUP BY 1"]
    assert not any(
        "short for a trend" in n for n in caveats.caveats_for("Here.", sql=sql)
    )


def test_rain_note_follows_the_rain_columns():
    if not query.counts()["has_agent_tables"]:
        pytest.skip("agent tables not vendored")

    def rain(answer, sql=None):
        return any(
            "total precipitation" in n for n in caveats.caveats_for(answer, sql=sql)
        )

    assert rain("Here.", sql=["SELECT wet_days_yr FROM rankings"])
    assert rain("Here.", sql=["SELECT month, avg(precip_mm) FROM monthly GROUP BY 1"])
    assert not rain("Here.", sql=["SELECT SUM(hours_rain_adj) FROM utci_histogram"])
    assert rain("Oviedo gets 190 wet days a year.")
    assert not rain("Comfort hours are rain-adjusted.")


def test_sunshine_note_follows_the_sunshine_columns():
    if not query.counts()["has_agent_tables"]:
        pytest.skip("agent tables not vendored")

    def sun(answer, sql=None):
        return any(
            "sunshine recorder" in n for n in caveats.caveats_for(answer, sql=sql)
        )

    assert sun("Here.", sql=["SELECT clear_days_yr FROM rankings"])
    assert sun(
        "Here.", sql=["SELECT month, avg(sunshine_hours) FROM monthly GROUP BY 1"]
    )
    assert not sun("Here.", sql=["SELECT comfort_hours_sun FROM rankings"])
    assert sun("Madrid gets 2,800 hours of sunshine.")
    assert not sun("Comfort at full sun exposure.")


def test_air_note_follows_the_air_table():
    if not query.counts()["has_air"]:
        pytest.skip("no air_monthly in this export")

    def dusty(answer, sql=None):
        return any(
            "CAMS EAC4 reanalysis" in n for n in caveats.caveats_for(answer, sql=sql)
        )

    assert dusty(
        "Here.", sql=["SELECT month, avg(dust_days) FROM air_monthly GROUP BY 1"]
    )
    assert not dusty("Here.", sql=["SELECT pm25_ugm3, aq_factor FROM rankings"])
    assert dusty("La calima llega sobre todo en diciembre.")
    assert not dusty("PM2.5 enters the index as a multiplier.")
