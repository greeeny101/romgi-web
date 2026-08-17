"""
MarioCube source plugin.

repo.mariocube.com renders a sortable HTML file-listing table for every
directory, and the table markup has already drifted twice from what this
scraper expects (see git history). Current shape, per row:

    <tr tabindex="0">
      <td class=""><a href="?doc=FILENAME" ...>-txt-</a></td>
      <td class=""><a href="/ABSOLUTE/PATH/TO/FILENAME">FILENAME</a></td>
      <td sortv="SIZE_BYTES" class="">SIZE_HUMAN</td>
      <td class="">EXT</td><td class="">DATE</td>
    </tr>

Two rows per entry — a `?doc=` "-txt-" link (skipped; href doesn't start
with `/`, so the regex only matches the second, real-file `<a>`) and the
actual file link. `href` is now a *site-absolute* path (starts with `/`),
not a bare filename — pass it through `urllib.parse.urljoin` (which
replaces the base's path entirely for a leading `/`) rather than
`join_urls` (which treats every link as relative to the current directory
and would double up the path here).
"""
import html
import re
import urllib.parse

from utils import cache_manager
from utils.scrape_utils import fetch_url, create_scraper_session
from utils.parse_utils import size_bytes_to_str

from typing import Any, Generator
from core.contract import BuildContext, PlatformConfig, SourceManifest


HOST_NAME = 'MarioCube'

# Harmless leftover from the site's old plain-text-listing behavior; kept
# since it doesn't affect the current HTML response.
CURL_HEADERS = {
    'User-Agent': 'curl/8.0',
    'Accept': '*/*'
}

_ROW_RE = re.compile(
    r'<a href="(?P<href>/[^"]+)"[^>]*>(?P<filename>[^<]*)</a>\s*'
    r'</td>\s*<td sortv="(?P<size>\d+)" class="">',
    re.DOTALL,
)


def extract_entries(response: str, source: dict[str, Any], platform: str, base_url: str) -> list[dict[str, Any]]:
    """Extract entries from the HTML file-listing table response."""
    entries = []

    for filename, href, size_bytes in parse_listing_rows(response):
        match = re.match(source['filter'], filename)
        if not match:
            continue

        title = match.group(1)
        entries.append(create_entry(
            href, filename, title, size_bytes, source, platform, base_url))

    return entries


def create_entry(link: str, filename: str, title: str, size: int, source: dict[str, Any], platform: str, base_url: str) -> dict[str, Any]:
    """Create a dictionary representing a single entry."""
    name = html.unescape(title).strip()
    url = urllib.parse.urljoin(base_url, link)

    return {
        'title': name,
        'platform': platform,
        'regions': source['regions'],
        'links': [
            {
                'name': name,
                'type': source['type'],
                'format': source['format'],
                'url': url,
                'filename': filename,
                'host': HOST_NAME,
                'size': size,
                'size_str': size_bytes_to_str(size) if size else '',
                'source_url': base_url
            }
        ]
    }


def parse_listing_rows(response: str) -> Generator[tuple[str, str, int], None, None]:
    """Yield (filename, href, size_bytes) tuples from the HTML listing table."""
    for match in _ROW_RE.finditer(response):
        filename = html.unescape(match.group('filename'))
        href = html.unescape(match.group('href'))
        size_raw = match.group('size')
        size_bytes = int(size_raw) if size_raw.isdigit() else 0
        yield filename, href, size_bytes


def fetch_response(url: str, use_cached: bool, session: Any = None) -> str | None:
    """Fetch the response from a URL, optionally using a cached version."""
    url_stripped = url.rstrip('/')
    short_url = url_stripped.split('/')[-1][:50] if '/' in url_stripped else url_stripped[:50]

    if use_cached:
        response = cache_manager.get_cached_response(url)
        if response:
            print(f"      {short_url}... cached")
            return response

    # Fetch the URL directly if no cached response is available
    return fetch_url(url, session=session)


def scrape(source: dict[str, Any], platform: str, use_cached: bool = False) -> list[dict[str, Any]]:
    """Scrape entries from MarioCube based on the source configuration."""
    entries = []
    session = create_scraper_session(CURL_HEADERS)

    for url in source['urls']:
        # Fetch the response for each URL
        response = fetch_response(url, use_cached, session=session)
        if not response:
            print(f"Warning: Failed to get response from {url}, skipping...")
            continue

        # Extract entries from the response
        parsed_entries = extract_entries(response, source, platform, url)
        if not parsed_entries:
            print(f"Warning: No entries parsed from {url}, skipping...")
            continue

        entries.extend(parsed_entries)

    return entries


class MarioCubeSource:
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


SOURCE = MarioCubeSource
