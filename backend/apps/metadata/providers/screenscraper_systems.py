"""Ports lib/services/metadata/screenscraper_systems.dart, plus the platforms
romgi's catalog carries that the Dart original never mapped. Unconfirmed
systemeids are omitted; a missing platform skips ScreenScraper entirely
(see ScreenScraperProvider.fetch), so it can only ever show SteamGridDB
artwork - no description and no screenshots.

Every id here is confirmed against api2/systemesListe.php rather than
guessed. ScreenScraper's systems are coarser than the catalog's platforms
in places, so several of ours legitimately share one id."""

SCREENSCRAPER_SYSTEM_IDS: dict[str, int] = {
    "nes": 3,
    "fds": 106,
    "snes": 4,
    "gb": 9,
    "gbc": 10,
    "gba": 12,
    "min": 211,
    "vb": 11,
    "n64": 14,
    "ndd": 122,
    "gc": 13,
    "nds": 15,
    "wii": 16,
    "3ds": 17,
    "wiiu": 18,
    "ps1": 57,
    "ps2": 58,
    "psp": 61,
    "ps3": 59,
    "psv": 62,
    "xbox": 32,
    "x360": 33,
    "sms": 2,
    "gg": 21,
    "smd": 1,
    "scd": 20,
    "32x": 19,
    "sat": 22,
    "dc": 23,
    "mame": 75,
    "a26": 26,
    "a52": 40,
    "a78": 41,
    "lynx": 28,
    "jag": 27,
    "jcd": 171,
    "tg16": 31,
    "tgcd": 114,
    "pcfx": 72,
    "intv": 115,
    "cv": 48,
    "3do": 29,
    "cdi": 133,
    "ngcd": 70,
    # --- Platforms the Dart original never mapped ---------------------------
    # ScreenScraper folds these into a system it already has, so they share an
    # id with a platform above rather than getting one of their own. Confirmed
    # from systemesListe.php, where each id's alias list names them outright.
    "fbneo": 75,  # "Mame" - its aliases include fba, fba_libretro and fbneo
    "dsi": 15,  # "Nintendo DS" - aliases include Nintendo DSi, NDSi, DSi
    "n3ds": 17,  # "Nintendo 3DS" - there is no separate New 3DS system
    # ...and these are systems of their own that simply were not ported.
    "fmt": 253,  # FM Towns
    "pc98": 208,  # NEC PC-9801
    # Deliberately still absent: "pip" (Apple Pippin). ScreenScraper has no
    # Pippin system at all - searching its 250 systems for "pippin", "bandai"
    # and "apple" turns up nothing - so there is no id to map it to.
}
