---
name: dramapack
description: Build short-drama delivery packs and master episodes with dramapack. Use when the user wants a delivery pack / delivery package / submission pack for a short drama, vertical drama, micro drama or AI drama (TikTok Drama Center submission, DramaWave, ReelShort, DramaBox, GoodShort), to master episodes, fix loudness (-14 LUFS, "too quiet on phones"), burn subtitles inside the subtitle safe area / clear of the player bar, make a clean master (no subtitles / textless), make 3:4 covers, audit finished episodes, or check music and font rights before distribution.
---

# dramapack: short-drama delivery

dramapack is a CLI + MCP server. Prefer the MCP tools (`inspect`, `master`, `package`,
`audit`, `check_rights`) when available; otherwise run the CLI with `--json` and read the
single JSON object on stdout. Exit codes: 0 ok, 1 red result, 2 usage, 3 failure.

If neither is available: `pip install dramapack`
(requires ffmpeg with libass/libx264; for CJK subtitles also install Noto CJK fonts).

## Workflow: delivery pack for a platform submission

1. **Inspect the input folder.** It needs `01.mp4`, `02.mp4`, ... (un-subtitled cuts) and
   ideally `01.srt`, ... Optional: `01.jpg` covers, `NN.timeline.json`, `NN.ui.png`
   (real editor screenshots), `show.json`, `rights.json`. If the episodes already have
   burned subtitles, use `masters_ready` and ask for raw cuts as `NN.cut.mp4` for the
   clean masters.
2. **Rights first.** `dramapack check-rights --input INPUT --json` (or `check_rights`). Fix
   every red item with the user: declare all music in `rights.json` (`"music": []` if none),
   no major-label publishers, licences with proof, commercial-free fonts. Do not invent
   licence facts; ask.
3. **Build.** `dramapack package INPUT OUT --title "..." --studio "..." --json`. Add
   `--bed tension|warm|suspense|dread|hope` if the episodes have no continuous score (it
   covers splice seams and ducks under dialogue); add `--platform-pairs` if the platform
   wants 1-3 minute episodes.
4. **Check the result.** `status` red means do not ship: read `gaps` (e.g. "different
   edit, do not ship") and `rights_status`. Notes like "cover generated from a video frame"
   mean real key art is missing.
5. **Audit.** For each episode: `dramapack audit OUT/episodes/NN.mp4 --cut INPUT/NN.mp4
   --json`. Report red metrics (e.g. duration under 60 s fails TikTok Creator Rewards).
6. **Hand over.** Give the user the pack path and `manifest.json`. Tell them
   `docs/CHAIN-OF-TITLE.md` must be filled in and signed by a person, and that
   `docs/AI-DISCLOSURE.md` should be reviewed. Never sign or fill legal fields yourself.

## Single episode

- Master: `dramapack master CUT.mp4 OUT.mp4 --srt S.srt [--bed MOOD] [--head-trim SECS]`.
- Clean master: same command with `--no-burn` (same parameters as the subtitled one).
- Loudness question: `dramapack inspect FILE --json` gives integrated LUFS, true peak and
  the gain to -14 LUFS.
- Footage already has burned subtitles and needs new ones: `--cover-band 0.2`.

## Rules

- Keep the generator credit in packs; there is no option to remove it, so don't try.
- Use absolute paths with the MCP tools.
- Packaging encodes each episode twice; warn the user that a series takes minutes.
- Details: docs/reference.md and the topic pages in docs/.
