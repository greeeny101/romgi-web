"""
The two pure decisions the BIOS browser makes about a remote file name:
whether to offer it, and whether to write it.

Worth pinning because both are made from archive.org's data in two places
(api._item_files and tasks.start_bios_download) and a disagreement between
them is a download that fails only after the user has committed to it.
"""

from apps.bios.files import is_derived, is_safe, selectable


def test_archive_orgs_own_bookkeeping_is_not_offered():
    # None of these were uploaded by anyone; archive.org derives them for
    # every item, and they are useless in an emulator's system folder.
    assert is_derived("PlayStationBIOSFilesNAEUJP_files.xml")
    assert is_derived("ps1-2-BIOS_meta.xml")
    assert is_derived("ps1-2-BIOS_meta.sqlite")
    assert is_derived("ps1-2-BIOS_reviews.xml")
    assert is_derived("ps1-2-BIOS_archive.torrent")
    assert is_derived("__ia_thumb.jpg")
    assert is_derived("history/files/scph1001.bin.~1~")


def test_real_bios_files_survive_the_filter():
    assert not is_derived("scph1001.bin")
    assert not is_derived("SCPH-5501.BIN")
    assert not is_derived("bios/saturn/sega_101.bin")
    # An item's own .torrent is derived; a file that merely ends in .xml or
    # sits in a folder called history is not.
    assert not is_derived("readme.xml")
    assert not is_derived("bios-history/notes.txt")


def test_names_that_would_escape_the_library_folder_are_refused():
    assert not is_safe("../../etc/passwd")
    assert not is_safe("/etc/passwd")
    assert not is_safe("bios/../../../root/.ssh/authorized_keys")
    assert not is_safe("")


def test_subdirectories_are_allowed_because_items_really_use_them():
    assert is_safe("scph1001.bin")
    assert is_safe("bios/ps1/scph1001.bin")
    # Traversal that stays inside is fine — normalising it is enough.
    assert is_safe("bios/../scph1001.bin")


def test_selectable_requires_both():
    assert selectable("scph1001.bin")
    assert not selectable("item_files.xml")
    assert not selectable("../escape.bin")
