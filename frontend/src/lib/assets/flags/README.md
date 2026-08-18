# Region flags

Waved flag artwork for the four catalog regions (`us`, `eu`, `jp`, `other` — seeded by
`backend/apps/catalog/migrations/0002_seed_platforms_regions.py`).

romgi's Android app has no flag assets: `lib/utils/region_utils.dart` returns plain emoji
(🇺🇸 / 🇪🇺 / 🇯🇵, 🌍 fallback) and Android's Noto Color Emoji is what draws them waved. Emoji
won't reproduce that on the web — macOS/iOS renders flat rectangles and Windows renders no
flag at all — so the same Noto artwork is vendored here and rendered as images by
`$lib/components/region/RegionFlags.svelte`.

| File        | Source (github.com/googlefonts/noto-emoji)                              |
| ----------- | ----------------------------------------------------------------------- |
| `us.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1fa_1f1f8.svg`              |
| `eu.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1ea_1f1fa.svg`              |
| `jp.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1ef_1f1f5.svg`              |
| `other.svg` | `svg/emoji_u1f30d.svg` (🌍, stands in for the `other` region)            |

Licensing: the flag artwork under `third_party/region-flags/` is public domain or otherwise
exempt from copyright, per that directory's `LICENSE`. The globe is part of Noto Emoji, under
the Apache License 2.0.

The three flags use `viewBox="0 0 1000 1000"` with the waved flag letterboxed inside; the globe
is `0 0 128 128`. A single square box (e.g. `h-4 w-4`) therefore sizes all four consistently.
