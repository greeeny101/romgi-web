# Region flags

Waved flag artwork for the nine catalog regions (`us`, `eu`, `de`, `fr`, `au`, `uk`, `jp`,
`world`, `other` — seeded by `backend/apps/catalog/migrations/0002_seed_platforms_regions.py`
and `0004_seed_country_regions.py`).

romgi's Android app has no flag assets: `lib/utils/region_utils.dart` returns plain emoji
(🇺🇸 / 🇪🇺 / 🇯🇵, 🌍 fallback) and Android's Noto Color Emoji is what draws them waved. Emoji
won't reproduce that on the web — macOS/iOS renders flat rectangles and Windows renders no
flag at all — so the same Noto artwork is vendored here and rendered as images by
`$lib/components/region/RegionFlags.svelte`.

| File        | Source (github.com/googlefonts/noto-emoji)                              |
| ----------- | ----------------------------------------------------------------------- |
| `us.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1fa_1f1f8.svg`              |
| `eu.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1ea_1f1fa.svg`              |
| `de.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1e9_1f1ea.svg`              |
| `fr.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1eb_1f1f7.svg`              |
| `au.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1e6_1f1fa.svg`              |
| `uk.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1ec_1f1e7.svg`              |
| `jp.svg`    | `third_party/region-flags/waved-svg/emoji_u1f1ef_1f1f5.svg`              |
| `world.svg` | `svg/emoji_u1f310.svg` (🌐, the `world` region)                          |
| `other.svg` | `svg/emoji_u1f30d.svg` (🌍, stands in for the `other` region)            |

Two globes rather than one: `world` is a real region (a "(World)" release, playable anywhere)
while `other` is the none-of-the-above bucket, so they have to be distinguishable at a glance.

Licensing: the flag artwork under `third_party/region-flags/` is public domain or otherwise
exempt from copyright, per that directory's `LICENSE`. The globes are part of Noto Emoji, under
the Apache License 2.0.

The seven flags use `viewBox="0 0 1000 1000"` with the waved flag letterboxed inside; the globes
are `0 0 128 128`. A single square box (e.g. `h-4 w-4`) therefore sizes all nine consistently.
