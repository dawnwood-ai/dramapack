# Music and font rights checklist for overseas short dramas

Before you send a short drama to an overseas distributor: **no major-label music** (Sony,
Universal, Warner and their imprints, since these catalogues are fingerprinted and claimed
automatically), only music that is **AI-generated or procedurally generated, public domain
(published more than 50 years ago, and the recording too), or licensed from small or
independent artists with written proof**, and **only fonts that are free for commercial
use** (or commercially licensed, with proof) for anything burned into the picture.
`dramapack check-rights` grades your declared music cues and every burned-in font red /
yellow / green, and the result goes into the delivery pack's `manifest.json`.

```bash
dramapack check-rights input/rights.json --input input/
```

This is a hygiene check, not legal advice: it sees only what you declare and the fonts
dramapack renders.

## Checklist

- [ ] Every music cue in every episode is declared in `rights.json` (use `"music": []` if
      there is genuinely no music).
- [ ] No cue's publisher, label or rights owner is a major label or its imprint.
- [ ] Licensed cues have the licence on file (`proof`: file path or URL) covering sync,
      the territories and the platforms you deliver to.
- [ ] Public-domain cues have a publication year > 50 years ago, **and** the recording is
      public domain or your own performance.
- [ ] AI-generated cues name the tool, and you keep its commercial-use terms.
- [ ] Every font in subtitles, title cards and end cards is free for commercial use or
      licensed with proof. ffmpeg's default subtitle font is Arial, which is not.
- [ ] The subtitle font is actually installed where you render. Otherwise the renderer
      substitutes another font, and that is the one in your video.

## How dramapack grades

| Grade | When |
|---|---|
| red | no `rights.json` or no `music` list; a cue with `unknown`/missing source; publisher/label/rights owner matches a major label; public domain published <= 50 years ago; a font not in the allowlist without a free licence or licence proof; a music file used in mastering but not declared |
| yellow | `licensed` without proof, or the proof file isn't found; `public_domain` without a year; a burned-in font that isn't installed (the substitute is checked too) |
| green | everything else; dramapack's own procedural music bed is auto-declared `procedural` |

## Font allowlist

Built in (prefix match, case-insensitive): Noto, Source Han Sans / Serif (and their
native-script names), Source Sans / Serif / Code, DejaVu, Liberation, Roboto, Open Sans,
Lato, Montserrat, Inter, Poppins, Oswald, Bebas Neue, Anton, Fira, IBM Plex, Ubuntu, LXGW
WenKai, Smiley Sans. Extend it per project with
`"font_allowlist": [...]` in `rights.json` or `--allow-font NAME`; add extra blocked
publishers with `"blocked_publishers": [...]`.

## Safe default

The procedural music bed (`--bed tension|warm|suspense|dread|hope`) is generated from
ffmpeg oscillators: no samples, no library, nothing to clear. It ducks under dialogue and
covers splice seams; see [short-drama-loudness-14-lufs.md](short-drama-loudness-14-lufs.md).

Schema: [reference.md#rightsjson](reference.md#rightsjson).
