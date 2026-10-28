# What is a clean master and why short-drama distributors ask for it

A **clean master** (also called a textless or no-subtitle master) is the finished episode
with **no burned-in subtitles** but otherwise identical to the subtitled master: same edit,
same frames, same mix, same loudness. Distributors and platforms ask for it so they can
burn their own subtitles, translate into other languages (dubbing and localisation), and
re-layout text for their player. dramapack builds it with the **same mastering chain with
subtitles switched off**, and checks that its duration matches the subtitled master.

```bash
dramapack package input/ out/          # writes episodes/NN.mp4 and clean/NN.mp4
dramapack master cut01.mp4 clean01.mp4 --no-burn   # a single clean master
```

## A clean master is not the raw cut

The raw cut has no subtitles, but it also has no loudness normalisation, no music bed and
no end card. Handing it over ships a file 5-11 dB quieter than the subtitled version with
every splice seam exposed, and a different length if the subtitled master has a head trim
or end card. **Clean master = master minus subtitles, not master minus mastering.**

## Both versions must be the same edit

If the clean and subtitled masters differ in length, a platform comparing them concludes
they are different edits. dramapack:

- builds both from the same input with the same parameters (head trim, end card, bed) in
  one run, and records both durations in `manifest.json`;
- reports a gap ending "different edit, do not ship" if they differ by more than 1 second;
- with `--masters-ready` (you already have subtitled masters) rebuilds the clean master
  from `NN.cut.mp4` and **infers** head trim and end card from the master's measured
  duration. Options added to a show later shouldn't produce a clean master seconds
  longer than an older subtitled one. If nothing matches within 0.75 s it falls back to no
  trim / no card rather than inventing a new edit.

## Two-episodes-per-file platform cuts

Some platforms specify 1-3 minutes per episode while social cuts run about a minute.
`--platform-pairs` joins consecutive delivered episodes (and their clean masters) with a
re-encode at the seam (a stream-copied join can drop frames or slip A/V sync), so every
frame is identical to the per-episode files. The second SRT is offset by the first file's
**measured duration**, not by its last cue; end cards carry no subtitles.

See also: [tiktok-drama-center-delivery-package.md](tiktok-drama-center-delivery-package.md).
