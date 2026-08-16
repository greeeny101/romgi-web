"""
Seeds the fixed Platform/Region reference data — verbatim port of the
PLATFORMS/REGIONS dicts in romgi/db/database/db_manager.py's
init_database(). Static, not per-CatalogBuild.
"""

from django.db import migrations

PLATFORMS = {
    "nes": {"brand": "Nintendo", "name": "Nintendo Entertainment System"},
    "fds": {"brand": "Nintendo", "name": "Famicom Disk System"},
    "snes": {"brand": "Nintendo", "name": "Super Nintendo Entertainment System"},
    "gb": {"brand": "Nintendo", "name": "Game Boy"},
    "gbc": {"brand": "Nintendo", "name": "Game Boy Color"},
    "gba": {"brand": "Nintendo", "name": "Game Boy Advance"},
    "min": {"brand": "Nintendo", "name": "Pokemon Mini"},
    "vb": {"brand": "Nintendo", "name": "Virtual Boy"},
    "n64": {"brand": "Nintendo", "name": "Nintendo 64"},
    "ndd": {"brand": "Nintendo", "name": "Nintendo 64DD"},
    "gc": {"brand": "Nintendo", "name": "GameCube"},
    "nds": {"brand": "Nintendo", "name": "Nintendo DS"},
    "dsi": {"brand": "Nintendo", "name": "Nintendo DSi"},
    "wii": {"brand": "Nintendo", "name": "Wii"},
    "3ds": {"brand": "Nintendo", "name": "Nintendo 3DS"},
    "n3ds": {"brand": "Nintendo", "name": "New Nintendo 3DS"},
    "wiiu": {"brand": "Nintendo", "name": "Wii U"},
    "ps1": {"brand": "Sony", "name": "PlayStation"},
    "ps2": {"brand": "Sony", "name": "PlayStation 2"},
    "psp": {"brand": "Sony", "name": "PlayStation Portable"},
    "ps3": {"brand": "Sony", "name": "PlayStation 3"},
    "psv": {"brand": "Sony", "name": "PlayStation Vita"},
    "xbox": {"brand": "Microsoft", "name": "Xbox"},
    "x360": {"brand": "Microsoft", "name": "Xbox 360"},
    "sms": {"brand": "Sega", "name": "Master System - Mark III"},
    "gg": {"brand": "Sega", "name": "Game Gear"},
    "smd": {"brand": "Sega", "name": "Mega Drive - Genesis"},
    "scd": {"brand": "Sega", "name": "Mega-CD - Sega CD"},
    "32x": {"brand": "Sega", "name": "32X"},
    "sat": {"brand": "Sega", "name": "Sega Saturn"},
    "dc": {"brand": "Sega", "name": "Dreamcast"},
    "mame": {"brand": "Arcade", "name": "MAME"},
    "fbneo": {"brand": "Arcade", "name": "FinalBurn Neo"},
    "a26": {"brand": "Atari", "name": "Atari 2600"},
    "a52": {"brand": "Atari", "name": "Atari 5200"},
    "a78": {"brand": "Atari", "name": "Atari 7800"},
    "lynx": {"brand": "Atari", "name": "Atari Lynx"},
    "jag": {"brand": "Atari", "name": "Atari Jaguar"},
    "jcd": {"brand": "Atari", "name": "Atari Jaguar CD"},
    "tg16": {"brand": "NEC", "name": "PC Engine - TurboGrafx-16"},
    "tgcd": {"brand": "NEC", "name": "PC Engine CD - TurboGrafx-CD"},
    "pcfx": {"brand": "NEC", "name": "PC-FX"},
    "pc98": {"brand": "NEC", "name": "PC-98"},
    "intv": {"brand": "Mattel", "name": "Intellivision"},
    "cv": {"brand": "Coleco", "name": "ColecoVision"},
    "3do": {"brand": "The 3DO Company", "name": "3DO Interactive Multiplayer"},
    "cdi": {"brand": "Philips", "name": "CD-i"},
    "fmt": {"brand": "Fujitsu", "name": "FM Towns"},
    "ngcd": {"brand": "SNK", "name": "Neo Geo CD"},
    "pip": {"brand": "Apple-Bandai", "name": "Pippin"},
}

REGIONS = {
    "eu": "Europe",
    "us": "USA",
    "jp": "Japan",
    "other": "Other",
}


def seed(apps, schema_editor):
    Platform = apps.get_model("catalog", "Platform")
    Region = apps.get_model("catalog", "Region")

    Platform.objects.bulk_create(
        [Platform(id=pid, brand=info["brand"], name=info["name"]) for pid, info in PLATFORMS.items()],
        ignore_conflicts=True,
    )
    Region.objects.bulk_create(
        [Region(id=rid, name=name) for rid, name in REGIONS.items()],
        ignore_conflicts=True,
    )


def unseed(apps, schema_editor):
    Platform = apps.get_model("catalog", "Platform")
    Region = apps.get_model("catalog", "Region")
    Platform.objects.filter(id__in=PLATFORMS.keys()).delete()
    Region.objects.filter(id__in=REGIONS.keys()).delete()


class Migration(migrations.Migration):
    dependencies = [("catalog", "0001_initial")]
    operations = [migrations.RunPython(seed, unseed)]
