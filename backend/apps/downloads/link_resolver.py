"""
Ports lib/services/link_resolver.dart's scoring algorithm 1:1 — see the
plan's porting reference map. Given an Entry's Link queryset and the
caller's UserSettings, returns links ranked by score, descending. A score
of AUTH_GATED_SCORE marks a link that's gated behind an IA login the caller
doesn't have; downloads.tasks._find_failover_link excludes these, exactly
like Dart's `_tryFailover`.
"""

from dataclasses import dataclass

AUTH_GATED_SCORE = -100


@dataclass
class RankedLink:
    link: object
    score: int
    notice: str | None = None


def rank_links(links, user_settings, ia_logged_in: bool = False) -> list[RankedLink]:
    torrents_disabled = bool(user_settings and user_settings.torrents_disabled)
    debrid_enabled = bool(user_settings and user_settings.debrid_enabled)
    preferred = set(user_settings.preferred_source_ids) if user_settings else set()
    disabled = set(user_settings.disabled_source_ids) if user_settings else set()

    out: list[RankedLink] = []
    for link in links:
        source_id = link.source_id
        is_torrent = link.torrent_id is not None

        if source_id and source_id in disabled:
            continue
        if is_torrent and torrents_disabled and not debrid_enabled:
            continue
        if link.requires_auth and not ia_logged_in:
            out.append(RankedLink(link=link, score=AUTH_GATED_SCORE, notice="Internet Archive login required"))
            continue

        score = link.source.priority if link.source_id else 0
        if source_id and source_id in preferred:
            score += 1000
        if not is_torrent or debrid_enabled:
            score += 1
        out.append(RankedLink(link=link, score=score))

    # Stable sort — ties keep their original (source-priority) order, same
    # as Dart's List.sort on a comparator with no secondary key.
    out.sort(key=lambda r: r.score, reverse=True)
    return out
