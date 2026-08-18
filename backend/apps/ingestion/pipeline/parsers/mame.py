"""
Resolves arcade/softlist ROM short names to the real game name.

Arcade sources ship ROMs named by their MAME/FBNeo set name — `10yard`,
`bbusters`, `eswatbl` — which is unusable both as a browse title and as a
lookup key for artwork, since every art source (libretro-thumbnails,
ScreenScraper) is keyed on the human name "10-Yard Fight (World, set 1)".
This parser does the romname -> description substitution so the parsers
that run after it (libretro, retroachievements) have something to match on.

Two sources, tried in order per platform:

  * The libretro-database arcade DATs (`data/libretro/metadat/...`), which
    cover the arcade *machine* sets. Fetched by scripts/download_libretro_dats.py;
    if that hasn't been run, they're pulled over HTTP once and cached to the
    same path, so ingestion isn't silently degraded by a missing prerequisite.
  * MAME's own softlist XMLs (`data/mame/hash/*.xml`, via
    scripts/download_mame_hashes.py). These describe *software* for the
    systems MAME emulates, not arcade cabinets, so they're a supplement
    rather than the arcade answer — kept because they're the original
    behaviour of this parser and cost nothing when absent.
"""
import os
import re
import xml.etree.ElementTree as ET
from typing import Any
from urllib.parse import quote

import requests

# Directory containing XML files with MAME software data
XMLS_DIR = 'data/mame/hash'

LIBRETRO_DIR = 'data/libretro'
LIBRETRO_RAW = 'https://raw.githubusercontent.com/libretro/libretro-database/master/'

# Arcade name DATs per platform, most-specific first. FBNeo's own DAT names
# the sets its cores actually run; MAME.dat is the fallback for anything the
# FBNeo list doesn't carry.
ARCADE_DATS = {
    'fbneo': [
        'metadat/fbneo-split/FinalBurn Neo (ClrMame Pro XML, Arcade only).dat',
        'metadat/fbneo-split/FBNeo - Arcade Games.dat',
        # Broader net for sets FBNeo's own list doesn't carry.
        'metadat/mame/MAME.dat',
    ],
    'mame': [
        'metadat/mame/MAME.dat',
    ],
}

# Global dictionary to store ROMs data
roms: dict[str, str] | None = None
# platform -> {romname: description}
arcade: dict[str, dict[str, str]] | None = None


def load_roms() -> None:
    """Load ROM data from XML files in the specified directory."""
    global roms
    roms = {}

    if not os.path.isdir(XMLS_DIR):
        print(f"Warning: {XMLS_DIR} not found, skipping MAME softlist names...")
        return

    for filename in os.listdir(XMLS_DIR):
        if not filename.endswith('.xml'):
            continue

        filepath = os.path.join(XMLS_DIR, filename)

        tree = ET.parse(filepath)
        root = tree.getroot()

        for software in root.findall('software'):
            name = software.get('name')
            desc_elem = software.find('description')
            description = desc_elem.text if desc_elem is not None else None
            if name is not None and description is not None:
                roms[name] = description


def _dat_text(dat_filename: str) -> str | None:
    """Local copy if scripts/download_libretro_dats.py has run, else fetch
    once and cache it there."""
    path = os.path.join(LIBRETRO_DIR, dat_filename)
    try:
        with open(path, encoding='utf-8') as f:
            return f.read()
    except FileNotFoundError:
        pass

    try:
        r = requests.get(LIBRETRO_RAW + quote(dat_filename), timeout=120)
        r.raise_for_status()
    except requests.RequestException as e:
        print(f"Warning: could not fetch {dat_filename}: {e}")
        return None

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(r.text)
    except OSError as e:
        # Cache is an optimisation, not a requirement — a read-only or full
        # volume shouldn't fail the run.
        print(f"Warning: could not cache {dat_filename}: {e}")

    return r.text


def _parse_dat_xml(text: str) -> dict[str, str]:
    """Logiqx XML: <game name="10yard"><description>10-Yard Fight...</description>.
    Some MAME-derived DATs use <machine> for the same thing."""
    names: dict[str, str] = {}
    try:
        root = ET.fromstring(text)
    except ET.ParseError:
        return names

    for tag in ('game', 'machine'):
        for node in root.iter(tag):
            name = node.get('name')
            desc_elem = node.find('description')
            description = (desc_elem.text or '').strip() if desc_elem is not None else ''
            if name and description and name not in names:
                names[name] = description
    return names


# ClrMamePro text form, as used by metadat/mame/MAME.dat. Note this one is
# inverted relative to the XML DATs: the *game* carries the human name and
# the short name is the rom filename, so the mapping is read off the rom line.
#
#   game (
#           name "10-Yard Fight (World, set 1)"
#           rom ( name 10yard.zip size 62708 ... )
#   )
_CMP_GAME_RE = re.compile(r"^game \($", re.MULTILINE)
_CMP_NAME_RE = re.compile(r'^\s*name "(.*?)"\s*$', re.MULTILINE)
_CMP_ROM_RE = re.compile(r"^\s*rom \(\s*name (\S+)", re.MULTILINE)


def _parse_dat_clrmamepro(text: str) -> dict[str, str]:
    names: dict[str, str] = {}
    for block in _CMP_GAME_RE.split(text)[1:]:
        block = block.split("\n)", 1)[0]
        title_match = _CMP_NAME_RE.search(block)
        if not title_match:
            continue
        description = title_match.group(1).strip()
        for rom in _CMP_ROM_RE.findall(block):
            short = os.path.splitext(rom)[0]
            if short and description and short not in names:
                names[short] = description
    return names


def _parse_dat(text: str) -> dict[str, str]:
    """DAT files come in both a Logiqx XML and a ClrMamePro text flavour;
    which one a given file uses isn't inferable from its extension."""
    names = _parse_dat_xml(text)
    if not names:
        names = _parse_dat_clrmamepro(text)
    if not names:
        print("Warning: arcade DAT matched neither XML nor ClrMamePro layout, skipping...")
    return names


def load_arcade() -> None:
    global arcade
    arcade = {}

    for platform, dat_filenames in ARCADE_DATS.items():
        names: dict[str, str] = {}
        for dat_filename in dat_filenames:
            text = _dat_text(dat_filename)
            if text is None:
                continue
            for name, description in _parse_dat(text).items():
                names.setdefault(name, description)
        arcade[platform] = names
        print(f"Loaded {len(names)} arcade names for {platform}")


def parse(entries: list[dict[str, Any]], flags: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse a list of entries and update their titles based on ROM data."""
    if roms is None:
        load_roms()
    if arcade is None:
        load_arcade()

    if roms is None and arcade is None:
        return entries

    for entry in entries:
        # Arcade DATs first: for an arcade platform they're the authoritative
        # naming, and a softlist can carry an unrelated set of the same name.
        names = (arcade or {}).get(entry.get('platform')) or {}
        description = names.get(entry['title']) or (roms or {}).get(entry['title'])
        if description:
            # Keep the short name — it's how the source addresses the file,
            # and it's the join key back to cheats/RA/DAT data.
            entry['rom_id'] = entry['title']
            entry['title'] = description

    return entries
