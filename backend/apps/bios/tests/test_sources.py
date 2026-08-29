"""
The curated query map. The point of sources.yml is that its results are
good, which no test can assert — but the mechanics around it are testable,
and the one that matters is that a user's search text can only ever narrow
the curation, never replace it.
"""

from apps.bios.sources import BiosSource, build_query, get_source, load_sources

SOURCE = BiosSource(id="ps1", name="PlayStation", platform_id="ps1", query="title:(bios) AND (psx)")


def test_an_empty_search_leaves_the_curated_query_alone():
    assert build_query(SOURCE, "") == SOURCE.query
    assert build_query(SOURCE, "   ") == SOURCE.query


def test_user_text_is_anded_on_rather_than_replacing():
    assert build_query(SOURCE, "scph") == 'title:(bios) AND (psx) AND ("scph")'


def test_quotes_cannot_break_out_of_the_users_term():
    # An unescaped " would end the phrase and let the rest of the input act
    # as query syntax against archive.org.
    assert build_query(SOURCE, 'a" OR mediatype:(movies') == 'title:(bios) AND (psx) AND ("a  OR mediatype:(movies")'


def test_every_shipped_source_is_well_formed():
    sources = load_sources()
    assert sources, "sources.yml must not be empty"
    assert len({s.id for s in sources}) == len(sources), "source ids must be unique"
    for source in sources:
        assert source.name
        # The title: scoping is the whole reason these results are usable —
        # a bare `bios AND (...)` returns romsets and SD-card images.
        assert "title:(" in source.query
        assert "mediatype:" in source.query


def test_get_source_finds_by_id_and_returns_none_otherwise():
    assert get_source("ps1") is not None
    assert get_source("nope") is None
