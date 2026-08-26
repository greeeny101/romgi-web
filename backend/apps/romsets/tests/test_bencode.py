"""
The bdecoder and the qBittorrent name mapping, which are the two places a
ROM set can fail without anyone noticing.

Both produce a plausible-looking result when wrong: a torrent whose padding
entries leak through shows phantom 4MB files in the picker, and a file list
matched without the torrent's root directory selects nothing at all — which
qBittorrent reports as an immediately "complete" 0-byte download rather than
as an error. Neither is visible by clicking around.
"""

import hashlib

import pytest

from apps.romsets.bencode import BencodeError, bdecode, infohash_from_torrent, torrent_files


def bencode(value) -> bytes:
    """Minimal encoder — test-only, so the fixtures below are readable
    Python rather than a checked-in binary blob."""
    if isinstance(value, int):
        return b"i%de" % value
    if isinstance(value, bytes):
        return b"%d:%s" % (len(value), value)
    if isinstance(value, list):
        return b"l" + b"".join(bencode(v) for v in value) + b"e"
    if isinstance(value, dict):
        out = b"d"
        for key in sorted(value):
            out += bencode(key) + bencode(value[key])
        return out + b"e"
    raise TypeError(type(value))


def make_info(files, name=b"fbneo_1003_bestset") -> dict:
    return {b"name": name, b"piece length": 4194304, b"pieces": b"\x00" * 20, b"files": files}


def make_torrent(files, name=b"fbneo_1003_bestset") -> bytes:
    return bencode(
        {
            b"announce": b"http://bt1.archive.org:6969/announce",
            b"url-list": [b"https://archive.org/download/"],
            b"info": make_info(files, name),
        }
    )


# Mirrors the real fbneo_1003_bestset layout: BEP-47 padding blocks
# interleaved between every real file, which is what archive.org emits.
REAL_SHAPE = [
    {b"path": [b"__ia_thumb.jpg"], b"length": 10485},
    {b"path": [b".____padding_file", b"0"], b"length": 4183819, b"attr": b"p"},
    {b"path": [b"fbneo_1003_bestset_meta.xml"], b"length": 37221},
    {b"path": [b".____padding_file", b"1"], b"length": 4173824, b"attr": b"p"},
    {b"path": [b"fbneo_1_0_0_3_best.zip"], b"length": 5010379875},
    {b"path": [b".____padding_file", b"3"], b"length": 1813405, b"attr": b"p"},
]


def test_padding_files_never_reach_the_file_list():
    root, entries = torrent_files(make_torrent(REAL_SHAPE))

    assert root == "fbneo_1003_bestset"
    assert [e.path for e in entries] == [
        "__ia_thumb.jpg",
        "fbneo_1003_bestset_meta.xml",
        "fbneo_1_0_0_3_best.zip",
    ]
    assert not any("padding" in e.path for e in entries)


def test_padding_is_dropped_by_attr_even_without_the_conventional_name():
    """The `attr=p` flag is the normative signal; the filename is convention.
    A torrent that pads without using archive.org's naming must still not
    show 4MB of phantom files in the picker."""
    files = [
        {b"path": [b"game.zip"], b"length": 100},
        {b"path": [b"_pad", b"0"], b"length": 4194204, b"attr": b"p"},
    ]
    _root, entries = torrent_files(make_torrent(files))

    assert [e.path for e in entries] == ["game.zip"]


def test_nested_paths_are_joined_the_way_qbittorrent_reports_them():
    """fbneo-1.0.3 really does put its payload one directory deep."""
    files = [{b"path": [b"FBNeo - Arcade Games", b"parents.zip"], b"length": 10342832939}]
    _root, entries = torrent_files(make_torrent(files))

    assert entries[0].path == "FBNeo - Arcade Games/parents.zip"


def test_single_file_torrent_uses_the_root_name_as_the_file():
    data = bencode({b"info": {b"name": b"lone.zip", b"piece length": 16384, b"pieces": b"\x00" * 20, b"length": 4242}})
    root, entries = torrent_files(data)

    assert root == "lone.zip"
    assert [(e.path, e.size) for e in entries] == [("lone.zip", 4242)]


def test_infohash_digests_the_info_dictionary():
    """Verified against the real thing as well as this fixture: the live
    fbneo_1003_bestset torrent hashes to 4b407c1e…ee78, which is exactly the
    `btih` archive.org publishes for that item."""
    info_bytes = bencode(make_info(REAL_SHAPE))

    assert infohash_from_torrent(make_torrent(REAL_SHAPE)) == hashlib.sha1(info_bytes).hexdigest()


def test_infohash_reads_original_bytes_rather_than_re_encoding():
    """bencode permits key orders that a decode-then-re-encode would
    silently normalise. If this digested a re-encoding, the hash would drift
    for any torrent not already in canonical order — and every
    adopt-existing, poll and cancel lookup keyed on it would miss."""
    info_bytes = bencode(make_info(REAL_SHAPE))
    # `info` deliberately placed BEFORE `announce`, which canonical ordering
    # would never produce.
    data = b"d" + bencode(b"info") + info_bytes + bencode(b"announce") + bencode(b"http://x") + b"e"

    assert infohash_from_torrent(data) == hashlib.sha1(info_bytes).hexdigest()


def test_malformed_torrent_raises_rather_than_returning_nonsense():
    with pytest.raises(BencodeError):
        torrent_files(bencode({b"announce": b"http://example.invalid"}))


def test_bdecode_handles_the_types_archive_org_actually_emits():
    assert bdecode(b"i-3e") == -3
    assert bdecode(b"le") == []
    assert bdecode(b"de") == {}
    assert bdecode(b"l3:onei2ee") == [b"one", 2]
