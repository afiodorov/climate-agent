"""The honesty sidecar.

`caveats_for` runs as the `caveats` node in the graph, after `climate` — it
appends the caveats a chat answer would otherwise strip. It stays a passive
step: the climate node does not call it directly or know its output shape, the
graph's own edge is what hands the draft answer over. It uses no LLM — every
caveat below is a lookup against columns the climate pipeline already computes.
"""

from __future__ import annotations

import re
from functools import lru_cache

from . import query

# Short names produce false positives against ordinary prose ("Ube", "Las").
_MIN_NAME = 4
_MAX_NAMED = 6

# An ordering claim: a superlative, or any appeal to rank. "best month" and
# "worst month" are column names, not claims, so they do not count.
_ORDERING = re.compile(
    r"\b(best|worst)\b(?!\s+month)"
    r"|\b(top|highest|lowest|number one|most comfortable|winner|leads?)\b"
    r"|\brank(s|ed|ing)?\b|#1",
    re.IGNORECASE,
)

# ...unless the answer already did the disambiguation itself, in which case
# repeating it is noise.
_ALREADY_HEDGED = re.compile(r"composite", re.IGNORECASE)


@lru_cache(maxsize=1)
def _matcher() -> re.Pattern[str] | None:
    names = [
        n for n in query.city_index() if isinstance(n, str) and len(n) >= _MIN_NAME
    ]
    if not names:
        return None
    # Longest first so "San Luis Potosí" wins over a hypothetical "San Luis".
    names.sort(key=len, reverse=True)
    alternation = "|".join(re.escape(n) for n in names)
    return re.compile(rf"(?<!\w)({alternation})(?!\w)")


# Instability has to be measured relative to the city's own rank. Median
# volatility across all 1118 cities is ~89 places, but a mid-pack city moving
# from 500th to 600th means nothing, while Lima moving 12 places off rank 3
# means its podium finish is an artefact of scoring choices. A city whose rank
# swings by more than its own rank is unstable in the way that matters; that
# cutoff flags 8 cities, all inside the top 40.
_UNSTABLE_RATIO = 1.0


def _instability(city: str) -> float | None:
    entry = query.volatility_index().get(city, {})
    spread, median = entry.get("rank_volatility"), entry.get("rank_median")
    if spread is None or median is None:
        return None
    return spread / max(median, 1.0)


def cities_mentioned(text: str) -> list[str]:
    """City names appearing in the text, in order, deduplicated."""
    matcher = _matcher()
    if matcher is None:
        return []
    seen: dict[str, None] = {}
    for match in matcher.finditer(text):
        seen.setdefault(match.group(1), None)
    return list(seen)


def _join(names: list[str]) -> str:
    shown = names[:_MAX_NAMED]
    text = ", ".join(shown)
    if len(names) > _MAX_NAMED:
        text += f" and {len(names) - _MAX_NAMED} more"
    return text


def caveats_for(answer: str) -> list[str]:
    """Every caveat the published columns say applies to this answer."""
    cities = cities_mentioned(answer)
    index = query.city_index()
    volatility = query.volatility_index()
    notes: list[str] = []

    risky = [c for c in cities if index.get(c, {}).get("microclimate_risk")]
    if risky:
        # Reasons are 'coastal', 'relief' or 'coastal+relief'. Reduce the set to
        # its distinct causes so a mixed bag doesn't read "coastal and
        # coastal + relief and relief".
        causes = {
            part
            for c in risky
            for part in str(index[c].get("microclimate_reason") or "").split("+")
            if part
        }
        why = " and ".join(
            {"coastal": "coast", "relief": "steep relief"}.get(c, c)
            for c in sorted(causes)
        )
        notes.append(
            f"Microclimate risk ({why}): the ERA5 grid cell may not represent "
            f"conditions in the city itself for {_join(risky)}. 578 of the 1118 "
            "cities carry this flag."
        )

    unstable = [
        c
        for c in cities
        if (ratio := _instability(c)) is not None and ratio >= _UNSTABLE_RATIO
    ]
    for city in unstable[:3]:
        entry = volatility[city]
        notes.append(
            f"{city}'s position is unstable: across the 17 scoring variants its rank "
            f"spans {entry['rank_volatility']:.0f} places (median {entry['rank_median']:.0f}). "
            "Treat it as indicative, not exact."
        )

    reference = [c for c in cities if index.get(c, {}).get("is_reference")]
    if reference:
        notes.append(
            f"{_join(reference)} sit below the 500,000 population floor and are shown "
            "for comparison only — they carry no rank."
        )

    if _ORDERING.search(answer) and not _ALREADY_HEDGED.search(answer):
        notes.append(
            '"Best" depends on the metric. Raw comfort hours and the composite score '
            "agree only moderately (Kendall tau ~= 0.56), so roughly a fifth of city "
            "pairs swap order between them."
        )

    return notes
