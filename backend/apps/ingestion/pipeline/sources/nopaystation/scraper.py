"""
NoPayStation source plugin.

Scrapes the NoPayStation TSV database for PS3/PSV titles. Generates RAP
(PS3) and ZRIF (PSV) key files locally, served back via
apps.ingestion.api.get_ingestion_key — see KEYS_DIR/KEYS_BASE_URL below.
"""
import os
import csv
import io
import xml.etree.ElementTree as ET
from typing import Any

import requests

from utils import cache_manager
from utils.scrape_utils import fetch_url
from utils.parse_utils import size_bytes_to_str, join_urls

from core.contract import BuildContext, PlatformConfig, SourceManifest


HOST_NAME = 'NoPayStation'

REGIONS_MAP = {
    'US': 'us',
    'EU': 'eu',
    'JP': 'jp'
}

# Where generated RAP/ZRIF key files get written, and the base URL they're
# served from — apps.ingestion.api.get_ingestion_key proxies this same
# directory. Not `static/content/...`: this project doesn't commit
# generated ingestion artefacts back to a repo the way the original app
# did (see CatalogBuild), so there's nothing to serve those from other
# than this app itself. Read directly via os.environ (not django.conf.settings)
# to keep this pipeline framework-agnostic, matching minerva/scraper.py's
# MINERVA_INDEX_TXT/MINERVA_HASHES_DB convention — settings.py defines the
# same NOPAYSTATION_KEYS_DIR default for the Django-facing side.
KEYS_DIR = os.environ.get('NOPAYSTATION_KEYS_DIR', 'data/nopaystation')
# Internal Docker Compose service URL — the download pipeline that later
# fetches these links runs in a celery-worker container on the same
# network, not on the host, so `localhost` would not resolve.
KEYS_BASE_URL = os.environ.get('NOPAYSTATION_KEYS_BASE_URL', 'http://django:8000')

PS3_RAPS_DIR = os.path.join(KEYS_DIR, 'ps3', 'raps')
PS3_RAPS_BASE_URL = f'{KEYS_BASE_URL}/api/ingestion/keys/ps3/raps'

PSV_ZRIFS_DIR = os.path.join(KEYS_DIR, 'psv', 'zrifs')
PSV_ZRIFS_BASE_URL = f'{KEYS_BASE_URL}/api/ingestion/keys/psv/zrifs'


def create_rap_file(rap: str, filepath: str) -> None:
    """Create a RAP file from a hex string."""
    with open(filepath, 'wb') as f:
        f.write(bytes.fromhex(rap))


def create_zrif_file(zrif: str, filepath: str) -> None:
    """Create a ZRIF file from a string."""
    with open(filepath, 'w') as f:
        f.write(zrif)


def add_ps3_links(result: dict[str, Any], links: list[dict[str, Any]], base_url: str) -> None:
    """Add PS3-specific links (e.g., RAP files) to the links list."""
    name = result['Name']
    rap = result['RAP']
    content_id = result['Content ID']

    if len(rap) == 32 and content_id:
        filename = f'{content_id}.rap'
        filepath = os.path.join(PS3_RAPS_DIR, filename)
        create_rap_file(rap, filepath)

        links.append({
            'name': name,
            'type': 'RAP file',
            'format': 'rap',
            'url': join_urls(PS3_RAPS_BASE_URL, filename),
            'filename': filename,
            'host': HOST_NAME,
            'size': 16,
            'size_str': size_bytes_to_str(16),
            'source_url': base_url
        })


def add_psv_links(result: dict[str, Any], links: list[dict[str, Any]], base_url: str) -> None:
    """Add PSV-specific links (e.g., ZRIF strings) to the links list."""
    name = result['Name']
    zrif = result['zRIF']
    content_id = result['Content ID']

    if zrif and content_id:
        filename = content_id
        filepath = os.path.join(PSV_ZRIFS_DIR, filename)
        create_zrif_file(zrif, filepath)

        links.append({
            'name': name,
            'type': 'ZRIF string',
            'format': 'string',
            'url': join_urls(PSV_ZRIFS_BASE_URL, filename),
            'filename': filename,
            'host': HOST_NAME,
            'size': len(zrif),
            'size_str': size_bytes_to_str(len(zrif)),
            'source_url': base_url
        })


def parse_links(result: dict[str, Any], source: dict[str, Any], platform: str, base_url: str) -> list[dict[str, Any]]:
    """Parse links from the result and generate metadata for each link."""
    links = []
    url = result['PKG direct link']
    if not url.startswith('http'):
        return links

    name = result['Name']
    filename = url.rstrip('/').split('/')[-1]
    file_size_val = result.get('File Size', '')
    size = round(float(file_size_val)) if file_size_val and file_size_val.isdigit() else 0
    size_str = size_bytes_to_str(size) if size else '0B'

    if url.endswith('.xml'):
        # Handle XML files containing multiple URLs
        r = requests.get(url)
        if r.ok:
            root = ET.fromstring(r.text)
            urls = [piece.attrib['url'] for piece in root.findall('pieces')]
            for i, url in enumerate(urls):
                filename = url.rstrip('/').split('/')[-1]

                links.append({
                    'name': name,
                    'type': f"{source['type']} #{i}",
                    'format': source['format'],
                    'url': url,
                    'filename': filename,
                    'host': HOST_NAME,
                    'size': size,
                    'size_str': size_str,
                    'source_url': base_url
                })
    else:
        # Handle direct links
        links.append({
            'name': name,
            'type': source['type'],
            'format': source['format'],
            'url': url,
            'filename': filename,
            'host': HOST_NAME,
            'size': size,
            'size_str': size_str,
            'source_url': base_url
        })

    # Add platform-specific links
    if platform == 'ps3':
        add_ps3_links(result, links, base_url)
    elif platform == 'psv':
        add_psv_links(result, links, base_url)

    return links


def create_entry(result: dict[str, Any], source: dict[str, Any], platform: str, base_url: str) -> dict[str, Any]:
    """Create an entry for a ROM based on the result data."""
    rom_id = result['Title ID']
    name = result['Name']
    region = REGIONS_MAP.get(result['Region'], 'other')
    links = parse_links(result, source, platform, base_url)

    return {
        'rom_id': rom_id,
        'title': name,
        'platform': platform,
        'regions': [region],
        'links': links
    }


def parse_response(response: str, source: dict[str, Any], platform: str, base_url: str) -> list[dict[str, Any]]:
    """Parse the response and extract entries."""
    entries = []
    results = csv.DictReader(io.StringIO(response), delimiter='\t')

    for result in results:
        entry = create_entry(result, source, platform, base_url)
        if entry and entry['links']:
            entries.append(entry)

    return entries


def fetch_response(url: str, use_cached: bool) -> str | None:
    """Fetch the response from a URL, optionally using a cached version."""
    short_url = url.split('/')[-1][:50] if '/' in url else url[:50]

    if use_cached:
        response = cache_manager.get_cached_response(url)
        if response:
            print(f"      {short_url}... cached")
            return response

    return fetch_url(url)


def scrape(source: dict[str, Any], platform: str, use_cached: bool = False) -> list[dict[str, Any]]:
    """Scrape data from the source and extract entries."""
    # Ensure directories exist
    for path in (PS3_RAPS_DIR, PSV_ZRIFS_DIR):
        os.makedirs(path, exist_ok=True)

    entries = []

    for url in source['urls']:
        response = fetch_response(url, use_cached)
        if not response:
            print(f"Warning: Failed to get response from {url}, skipping...")
            continue

        parsed_entries = parse_response(response, source, platform, url)
        if not parsed_entries:
            print(f"Warning: No entries parsed from {url}, skipping...")
            continue

        entries.extend(parsed_entries)

    return entries


class NoPayStationSource:
    """Adapter from the plugin contract to the legacy scrape()."""

    def __init__(self, manifest: SourceManifest):
        self.manifest = manifest

    def scrape(
        self,
        platform: str,
        config: PlatformConfig,
        ctx: BuildContext,
    ) -> list[dict[str, Any]]:
        return scrape(config.to_legacy_dict(), platform, ctx.use_cached)


SOURCE = NoPayStationSource
