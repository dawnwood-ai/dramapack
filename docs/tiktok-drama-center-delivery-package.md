# How to build a TikTok Drama Center delivery package for a short drama

Run `dramapack package input/ out/` on a folder of numbered episode cuts (`01.mp4`,
`02.mp4`, ... plus `01.srt`, ...). You get the stack that short-drama platforms such as
TikTok Drama Center, DramaWave, ReelShort, DramaBox and GoodShort ask for: numbered
subtitled masters with **same-name SRT files**, a **clean master without subtitles** for
every episode, **3:4 covers at least 350x500**, edit-timeline evidence, a chain-of-title
template, an AI-production disclosure, and a `manifest.json` with measured specs and a
music/font rights check. Subtitles are burned inside the safe area (text box at most 70%
of frame width) and loudness is normalised to -14 LUFS.

Requirements change and differ per platform; always compare against the current spec in
the platform's partner portal. The pack covers the intersection most platforms share.

## 60-second version

```bash
pip install dramapack
# input/: 01.mp4 02.mp4 ... 01.srt 02.srt ... (optional: 01.jpg, show.json, rights.json)
dramapack check-rights --input input/            # fix red items first
dramapack package input/ out/ --title "My Show" --studio "My Studio" --bed tension \
    --target tiktok-dc
dramapack audit out/episodes/01.mp4 --cut input/01.mp4
```

## What each part of the pack is for

| Platform asks for | dramapack produces | Notes |
|---|---|---|
| Numbered episodes | `episodes/01.mp4`, `02.mp4`, ... | Zero-padded so they sort |
| Subtitle files | `episodes/01.srt` | **Same name** as the video; platforms pair by file name. Shifted if you trimmed the head |
| Subtitles inside the safe area | burned into `episodes/` | 18% bottom margin, 16% side margins: text box <= 70% width. See [subtitle-safe-area.md](subtitle-safe-area.md) |
| Clean / textless master | `clean/01.mp4` | Same chain, subtitles off; duration checked against the subtitled file. See [clean-master.md](clean-master.md) |
| Vertical cover | `covers/01.jpg` | 3:4, >= 350x500, cropped from the top so faces survive |
| Edit evidence | `timeline/01.png` + `01.edl.csv`, `timeline/ui/` | Rendered timeline is labelled as rendered; your real editor screenshots go in `timeline/ui/` |
| Chain of title | `docs/CHAIN-OF-TITLE.md` | Template left blank; a person fills it in and signs it |
| AI disclosure | `docs/AI-DISCLOSURE.md` | Review before sending |
| Specs | `manifest.json` | Measured from the files, plus the rights check |
| 1-3 min per episode | `platform/` (`--platform-pairs`) | Joins two consecutive episodes per file, same frames |
| No black bars (DC "Can be improved", code 4) | edge lift on every video (`--target tiktok-dc`) | A dark band on any one side for > 3.5 s is flagged, not only letterboxing; `audit` reports it as `edge_dark` |
| Episode cover | 1 s cover still at the head (`--target tiktok-dc`) | Drama Center's default episode cover is frame 0; SRTs are shifted 1 s to match |

## TikTok Drama Center: what `--target tiktok-dc` adds

Two reasons episodes came back "Can be improved" that a generic pack does not handle:

- **Black bars (code 4).** Drama Center flags a dark *band along one edge*, not just
  full-frame black: a 20 px band (at 1080 wide) darker than mean luma 12 for more than
  about 3.5 s on any one side, or a thin black column such as the 2 px a 1078-wide AI
  render picks up when padded to 1080. `--target tiktok-dc` crops a few px off the edges,
  scales back, and lifts every edge to a dark grey with a 160 px ramp (only pixels darker
  than the ramp change). Run `dramapack audit` on your source cuts to see which episodes
  would have been flagged (`edge_dark`). `--no-edge-lift` turns it off.
- **Default episode cover = frame 0.** Picking a keyframe in Drama Center is a manual step
  per episode. The pack prepends a 1 s still of the episode cover (`NN.jpg`, else
  `cover.jpg`, else a frame from the cut) so frame 0 is the cover; the SRT is shifted to
  match. Supply real key art as `NN.jpg`. `--no-cover-head` turns it off.

**Subtitle-area flags.** Drama Center's subtitle detector is noisy: it can flag subtitles
that are inside the 70%-width safe area dramapack burns to. If the subtitles in
`episodes/` are what got flagged, re-uploading the same file often clears it.

## Before you send it

- **Rights**: `manifest.json` -> `rights.status` must not be `red`. See
  [music-font-rights-checklist.md](music-font-rights-checklist.md).
- **Gaps**: the pack README lists "Known gaps in this build". A gap that says "do not
  ship" means the clean and subtitled masters are different edits.
- **Chain of title**: describe the rights holder exactly as it legally exists today. Never
  submit it unsigned; the tool will not sign it for you.
- **Edit evidence**: if a platform asks for an NLE screenshot showing tracks and cut
  points, supply real screenshots as `NN.ui.png`. Never pass the rendered timeline off as a
  screenshot.

## Already have finished masters?

Use `--masters-ready`: `NN.mp4` are copied as-is, and if you add the raw cut as
`NN.cut.mp4` the clean master is rebuilt from it, with head trim and end card inferred
from the master's measured length so both versions stay the same edit.

See also: [reference.md](reference.md) for every flag and file format.
