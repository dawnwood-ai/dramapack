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
pip install "git+https://github.com/dawnwood-ai/dramapack"
# input/: 01.mp4 02.mp4 ... 01.srt 02.srt ... (optional: 01.jpg, show.json, rights.json)
dramapack check-rights --input input/            # fix red items first
dramapack package input/ out/ --title "My Show" --studio "My Studio" --bed tension
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
