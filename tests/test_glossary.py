import re

from conftest import needs_data

from climate_agent import glossary, query

pytestmark = needs_data

_FIELDS = re.compile(r"\{[^}]*\}")


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


# --- Translations -----------------------------------------------------------


def test_there_are_translations():
    langs = glossary.languages()
    assert len(langs) >= 10
    assert "en" not in langs  # English is the source, in the module
    for code, lang in langs.items():
        assert re.fullmatch(r"[a-z]{2}", code), code
        assert lang["language"], code
        assert lang["thousands"] in {",", ".", " ", " ", " ", ""}, code


def test_every_language_translates_every_term():
    english = {e["term"]: e for e in glossary._ENTRIES}
    for code, lang in glossary.languages().items():
        assert set(lang["terms"]) == set(english), code
        seen: dict[str, str] = {}
        for term, t in lang["terms"].items():
            assert t["term"], (code, term)
            assert t["term"] in t["aliases"], (code, term)
            for alias in t["aliases"]:
                assert alias.strip() == alias and alias, (code, term, alias)
                # One spelling, one meaning — within the language.
                assert seen.setdefault(alias.lower(), term) == term, (code, alias)
            # Same numbers as the English, wherever the sentence puts them.
            assert set(_FIELDS.findall(t["definition"])) == set(
                _FIELDS.findall(english[term]["definition"])
            ), (code, term)
            assert t["definition"][-1] in ".。", (code, term)


def test_no_spelling_means_two_things_across_languages():
    """The client matches every language's aliases in one pass and maps a hit
    back to a term by its spelling, so a spelling must name one term
    everywhere: 'composite' may be English, French and Portuguese, but only
    ever for the composite score."""
    meaning: dict[str, tuple[str, str]] = {}
    for e in glossary.glossary():
        spellings = [(alias, "en") for alias in e["aliases"]]
        for code, t in e["translations"].items():
            spellings += [(alias, code) for alias in t["aliases"]]
        for alias, code in spellings:
            key = alias.lower()
            other = meaning.setdefault(key, (e["term"], code))
            assert other[0] == e["term"], (alias, code, "also", other)


def test_translations_are_rendered_with_local_numbers():
    c = query.counts()
    for code, lang in glossary.languages().items():
        for e in glossary.glossary():
            t = e["translations"][code]
            assert "{" not in t["definition"], (code, e["term"])
            if e["term"] == "reference city":
                floor = f"{c['min_population']:,}".replace(",", lang["thousands"])
                assert floor in t["definition"], (code, t["definition"])
            if e["term"] == "rank volatility":
                assert str(c["n_variants"]) in t["definition"], code
