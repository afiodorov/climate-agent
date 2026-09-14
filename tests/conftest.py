"""Shared helpers. The data-dependent tests pick their cities from whatever
`data/` (or CLIMATE_OUT_DIR) holds, so the suite runs unchanged against the
vendored files and against the pipeline's synthetic fixture."""

from __future__ import annotations

import pytest

from climate_agent import query

has_data = (query.out_dir() / "rankings.csv").exists()
needs_data = pytest.mark.skipif(not has_data, reason="climate out/ not built")
needs_agent_tables = pytest.mark.skipif(
    not (query.out_dir() / "agent" / "manifest.json").exists(),
    reason="agent tables not vendored",
)


def flagged_city() -> str:
    """A ranked city carrying the microclimate flag."""
    for name, row in query.city_index().items():
        if row.get("microclimate_risk") and row.get("rank") is not None:
            return name
    pytest.skip("no flagged city in the data")


def reference_city() -> str:
    for name, row in query.city_index().items():
        if row.get("is_reference"):
            return name
    pytest.skip("no reference city in the data")


def unstable_city() -> str:
    from climate_agent import caveats

    for name in query.city_index():
        ratio = caveats._instability(name)
        if ratio is not None and ratio >= caveats._UNSTABLE_RATIO:
            return name
    pytest.skip("no unstable city in the data")
