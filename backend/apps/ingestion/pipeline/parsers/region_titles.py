"""
Region detection from a ROM title's parenthesised tags — "Sonic (Europe)",
"10-Yard Fight (World, set 1)".

This started life inside no_intro.py, which is where most platforms get their
regions. It lives on its own now for two reasons:

  * Not every platform runs the no_intro parser — `fbneo` runs mame+libretro
    only — so the orchestrator applies parse_regions() as a last-resort
    fallback for any entry the configured parsers left region-less.
  * The vocabulary needs to be looser than a fixed country list. The same
    region shows up as "USA", "US" and "United States" depending on who built
    the set, so matching goes through a normalised alias table.

no_intro.py imports LANGUAGES and REGIONS_MAP from here, so this module must
not import from it.
"""

import re
from typing import Any

# Country/region names as they appear verbatim inside a title's parentheses,
# mapped to the catalog.Region ids seeded by the catalog migrations.
#
# Germany/France/Australia/United Kingdom used to collapse into 'eu'; they are
# their own regions now, grouped back under Europe at filter time by
# apps.catalog.regions. The rest of the PAL countries stay collapsed — they
# have no flag of their own in the UI.
REGIONS_MAP = {
    'USA': 'us',
    'Canada': 'us',
    'Mexico': 'us',
    'Europe': 'eu',
    'Australia': 'au',
    'Italy': 'eu',
    'Germany': 'de',
    'France': 'fr',
    'Spain': 'eu',
    'United Kingdom': 'uk',
    'UK': 'uk',
    'Netherlands': 'eu',
    'Austria': 'eu',
    'Belgium': 'eu',
    'Croatia': 'eu',
    'Denmark': 'eu',
    'Finland': 'eu',
    'Greece': 'eu',
    'Ireland': 'eu',
    'Poland': 'eu',
    'Portugal': 'eu',
    'Sweden': 'eu',
    'Turkey': 'eu',
    'Japan': 'jp',
    'World': 'world',
    'Argentina': 'other',
    'Brazil': 'other',
    'China': 'other',
    'Hong Kong': 'other',
    'India': 'other',
    'Israel': 'other',
    'Korea': 'other',
    'Latin America': 'other',
    'New Zealand': 'other',
    'Norway': 'other',
    'Russia': 'other',
    'Scandinavia': 'other',
    'South Africa': 'other',
    'Switzerland': 'other',
    'Taiwan': 'other',
    'United Arab Emirates': 'other',
    'Asia': 'other',
    'Unknown': 'other'
}

# List of possible languages described in a title
LANGUAGES = [
    'En', 'Ja', 'Fr', 'De', 'Es', 'It', 'Nl', 'Pt', 'Sv', 'No', 'Da', 'Fi',
    'Zh', 'Ko', 'Pl', 'Ru', 'Cs', 'Hu', 'Zh-Hant', 'Zh-Hans', 'El', 'Es-XL',
    'Pt-BR', 'Tr', 'En-GB', 'Ar', 'En+En', 'It+En', 'Ro', 'Af'
]

# Alternate spellings the same region is written as across ROM sets, on top of
# the canonical names in REGIONS_MAP. Deliberately no bare 'de' or 'fr' here:
# both are language codes (see LANGUAGES), and "(En,Fr,De)" is a language list,
# not a French-German release.
EXTRA_ALIASES = {
    'us': ['US', 'U.S.', 'U.S.A.', 'United States', 'United States of America',
           'America', 'North America', 'NTSC-U'],
    'jp': ['JP', 'JPN', 'Japanese', 'NTSC-J'],
    'de': ['German', 'Ger', 'Deu', 'Deutschland'],
    'fr': ['French', 'Fra'],
    'au': ['AU', 'AUS', 'Australian'],
    # No bare 'GB': "Donkey Kong (GB) (Virtual Console)" is a Game Boy title,
    # not a British one. 'GBR' has no console competing for it.
    'uk': ['GBR', 'Great Britain', 'Britain', 'England'],
    'eu': ['EU', 'EUR', 'European', 'PAL'],
}


def _normalize(text: str) -> str:
    """Fold a tag to its lookup key: lowercase, whitespace collapsed."""
    return re.sub(r"\s+", ' ', text).strip().lower()


_LANGUAGE_KEYS = {_normalize(language) for language in LANGUAGES}

REGION_ALIASES = {_normalize(name): region for name, region in REGIONS_MAP.items()}
for _region, _aliases in EXTRA_ALIASES.items():
    for _alias in _aliases:
        REGION_ALIASES[_normalize(_alias)] = _region

# Belt and braces on the "no bare language codes" rule above: if an alias ever
# collides with a language code, drop it rather than let "(En,Fr,De)" start
# assigning regions. Currently a no-op — it exists to keep it that way.
REGION_ALIASES = {
    alias: region for alias, region in REGION_ALIASES.items() if alias not in _LANGUAGE_KEYS
}


_MAX_ALIAS_WORDS = max(len(alias.split()) for alias in REGION_ALIASES)

# Function words don't appear in a region qualifier — "900227 World", "USA
# Phoenix Edition", "Japanese version" — but are all over the prose that
# happens to contain a region name, as in "Teen Angst (What the World Needs
# Now)". Finding one means the part is a subtitle, so the word-by-word scan
# below stays out of it. 'new' is deliberately absent: "New Zealand".
_PROSE_WORDS = {
    'the', 'a', 'an', 'and', 'or', 'of', 'for', 'to', 'in', 'on', 'at', 'from',
    'what', 'who', 'why', 'how', 'my', 'your', 'our', 'their', 'his', 'her',
    'its', 'this', 'that', 'is', 'are', 'was', 'were', 'be', 'not', 'no',
}


def _regions_in_part(part: str) -> set[str]:
    """Regions named by one comma-separated part of a parenthesised group."""
    key = _normalize(part)
    if key in REGION_ALIASES:
        return {REGION_ALIASES[key]}

    # The arcade sets qualify the region with a build date or a version in the
    # same breath — "1941 - Counter Attack (900227 World)", "Street Fighter II
    # (910522 Japan)" — so fall back to scanning the part word by word. Longest
    # run first: 'America' is itself an alias, so a shortest-first scan would
    # read "Latin America" as the USA.
    tokens = key.split()
    if _PROSE_WORDS.intersection(tokens):
        return set()

    found: set[str] = set()
    index = 0
    while index < len(tokens):
        for length in range(min(_MAX_ALIAS_WORDS, len(tokens) - index), 0, -1):
            region = REGION_ALIASES.get(' '.join(tokens[index : index + length]))
            if region:
                found.add(region)
                index += length
                break
        else:
            index += 1
    return found


def parse_regions(title: str) -> list[str]:
    """Parse the regions from a title.

    Walks the parenthesised groups left to right and returns the first one
    that yields any region — the leading group is the region tag by No-Intro
    convention, and later ones are revisions, dump flags and set numbers.
    """
    for group in re.findall(r"\((.*?)\)", title):
        parts = [part.strip() for part in group.split(',') if part.strip()]
        if not parts:
            continue

        # A group that is *entirely* language codes is a language list, not a
        # region tag. Checked before the alias lookup because a few codes
        # ('Fr', 'De') would otherwise read as countries.
        if all(_normalize(part) in _LANGUAGE_KEYS for part in parts):
            continue

        regions = set()
        for part in parts:
            regions |= _regions_in_part(part)
        if regions:
            # Sorted so the same title always produces the same order — the
            # entry slug is built from this list (utils.parse_utils.create_slug).
            return sorted(regions)

    return []


def apply_fallback(entries: list[dict[str, Any]], enabled: bool = True) -> list[dict[str, Any]]:
    """Assign regions from the title to any entry the parsers left without one.

    Runs after the configured parser chain, so it only sees what nothing else
    could identify: platforms with no no_intro parser at all, and titles whose
    tag isn't one no_intro recognised.
    """
    if not enabled:
        return entries

    for entry in entries:
        if not entry.get('regions'):
            entry['regions'] = parse_regions(entry.get('title') or '')

    return entries
