"""Plain-language definitions of the terms an answer uses.

The UI marks these words in an answer and shows the definition on hover or
tap. Every number in a definition (the band, the population floor, the
record's years, the variant count) is read from `data/` at first use, the
same way the prompt and the caveats read theirs, so a regenerated run cannot
leave a stale figure in a tooltip.

`aliases` are the spellings that count as a mention, matched whole-word and
case-insensitively by the client. `column` names the CSV column the term
maps to, when there is one, so a reader can go from the tooltip to the data.
"""

from __future__ import annotations

from functools import lru_cache
from typing import TypedDict

from . import query


class Entry(TypedDict):
    term: str
    aliases: list[str]
    definition: str
    column: str | None


def _e(term: str, aliases: list[str], definition: str, column: str | None) -> Entry:
    return {
        "term": term,
        "aliases": aliases,
        "definition": definition,
        "column": column,
    }


# Definitions are format strings over `query.counts()` plus the band's four
# edges. Keep them readable to someone who has never seen the methodology.
_ENTRIES: list[Entry] = [
    _e(
        "comfort hours",
        ["comfort hours", "comfortable hours", "comfortable daylight hours"],
        "Daylight hours in a typical year when being outside feels neither too "
        "hot nor too cold: a feels-like temperature of {cold_full:g} to "
        "{warm_full:g} °C, assuming you are in the sun about half the time, "
        "with rainy hours discounted. This is the headline number.",
        "comfort_hours_yr",
    ),
    _e(
        "daylight hours",
        ["daylight hours", "daylight"],
        "Hours in a year when the sun is up or it is civil twilight. Only these "
        "hours can count as comfortable; the night is never scored.",
        "daylight_hours_yr",
    ),
    _e(
        "comfort fraction",
        ["comfort fraction", "comfortable fraction", "share of daylight"],
        "The share of daylight hours that are comfortable. It flatters far-north "
        "cities: their miserable hours are the dark ones, and those are not "
        "daylight, so they never count against the city.",
        "comfort_fraction",
    ),
    _e(
        "comfort band",
        ["comfort band", "the band", "baseline band"],
        "The range of feels-like temperatures that counts as comfortable. Full "
        "credit from {cold_full:g} to {warm_full:g} °C, tapering to nothing at "
        "{cold_zero:g} °C on the cold side and {warm_zero:g} °C on the warm side.",
        None,
    ),
    _e(
        "UTCI",
        ["UTCI"],
        "Universal Thermal Climate Index: a feels-like temperature in °C. It "
        "folds air temperature, humidity, wind and sunshine into one number for "
        "how a person standing outside actually experiences the weather.",
        "utci_mean_daylight_c",
    ),
    _e(
        "evenness factor",
        ["evenness factor", "evenness"],
        "How evenly the comfortable hours are spread across the twelve months, "
        "from 0 (all in one season) to 1 (the same every month). It is 1 minus "
        "how much the monthly totals vary relative to their average.",
        "evenness_factor",
    ),
    _e(
        "composite",
        ["composite score", "composite"],
        "The single score the ranking is sorted by: comfort hours × evenness "
        "factor × air-quality factor. Because it multiplies, a dead winter or "
        "dirty air drags a city down however many comfortable hours it has.",
        "composite",
    ),
    _e(
        "worst month",
        ["worst month"],
        "The month with the fewest comfortable hours.",
        "worst_month_hours",
    ),
    _e(
        "best month",
        ["best month", "peak month"],
        "The month with the most comfortable hours.",
        "best_month_hours",
    ),
    _e(
        "longest bad streak",
        ["longest bad streak", "bad streak", "bad run", "longest bad stretch"],
        "The longest run of consecutive days with less than one comfortable "
        "hour, anywhere in the {start_year}–{end_year} record. A long streak is "
        "a season you simply wait out.",
        "longest_bad_streak_days",
    ),
    _e(
        "air-quality factor",
        [
            "air-quality factor",
            "air quality factor",
            "AQ factor",
            "aq_factor",
            "air-quality multiplier",
            "air quality penalty",
        ],
        "A penalty for polluted air, from 1 (clean, no penalty) down to a floor "
        "of 0.25, worked out from the city's average fine-particle level.",
        "aq_factor",
    ),
    _e(
        "PM2.5",
        ["PM2.5", "PM₂.₅", "pm25", "fine particles", "fine particulate"],
        "Fine particles in the air, under 2.5 micrometres across: about a "
        "thirtieth of a hair's width, small enough to lodge deep in the lungs. "
        "Measured in micrograms per cubic metre of air; lower is better.",
        "pm25_ugm3",
    ),
    _e(
        "dew point",
        ["dew point", "dewpoint", "dew-point"],
        "The temperature the air would have to cool to before dew forms. It is "
        "the honest measure of humidity: under 10 °C feels dry, 16 to 18 °C "
        "humid, 18 to 21 °C muggy, above 21 °C oppressive.",
        "dewpoint_mean_daylight_c",
    ),
    _e(
        "muggy",
        ["muggy", "muggy hours"],
        "Hours when the dew point is 18 °C or higher: the air feels sticky and "
        "sweat stops cooling you.",
        "muggy_daylight_hours_yr",
    ),
    _e(
        "microclimate risk",
        ["microclimate risk", "microclimate flag", "microclimate"],
        "The weather data comes from a grid cell about 31 km across. On a coast "
        "or in steep terrain that cell can describe a different place from the "
        "city itself, so the city's numbers may be off.",
        "microclimate_risk",
    ),
    _e(
        "ERA5",
        ["ERA5"],
        "The weather record behind everything: a global, hourly reconstruction "
        "of past weather on a grid about 31 km across, produced by the European "
        "weather centre ECMWF.",
        None,
    ),
    _e(
        "reference city",
        ["reference city", "reference cities", "reference-only"],
        "A city below the {min_population:,} population floor. It is shown for "
        "comparison only and carries no rank.",
        "is_reference",
    ),
    _e(
        "rank volatility",
        [
            "rank volatility",
            "scoring variants",
            "sensitivity analysis",
            "sensitivity sweep",
        ],
        "How far a city's rank moves when the scoring choices are changed one at "
        "a time: a warmer or cooler band, no air penalty, full sun, and so on, "
        "{n_variants} variants in all. A big swing means the rank is an "
        "artefact of those choices rather than of the climate.",
        "rank_volatility",
    ),
    _e(
        "Kendall tau",
        ["Kendall tau", "Kendall's tau", "Kendall's τ"],
        "A score for how much two orderings agree, from -1 (exactly reversed) "
        "to 1 (identical). Here it compares two ways of ranking the same cities.",
        None,
    ),
    _e(
        "sun exposure",
        ["sun exposure", "half-sun", "half sun", "half-sun exposure"],
        "The published figures assume you are in the sun about half the time. "
        "Full sun and full shade are also computed and can change the picture "
        "a lot, especially in hot places.",
        "comfort_hours_sun",
    ),
    _e(
        "elevation correction",
        ["elevation correction", "lapse rate", "lapse-rate correction"],
        "A city sitting well above its grid cell's average height gets a cooler "
        "feels-like temperature, at the usual rate air cools with altitude.",
        "elev_offset_k",
    ),
]


@lru_cache(maxsize=1)
def glossary() -> list[Entry]:
    """Every term with its numbers filled in from the vendored run."""
    c = query.counts()
    values = {**c, **c["band"]}
    return [{**e, "definition": e["definition"].format(**values)} for e in _ENTRIES]
