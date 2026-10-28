# Why short dramas should be mastered at -14 LUFS (and why not ffmpeg loudnorm)

Master vertical short dramas to **-14 LUFS integrated with one constant gain and a peak
limiter at -1 dBFS**. Most viewers watch on a phone speaker, and high-performing titles
on short-drama distribution networks measure around -12 to -14 LUFS, while raw AI renders
typically land at -20 to -27 LUFS: 6-13 dB quieter, which on a phone reads as "I can't
hear it". Do **not** use ffmpeg's `loudnorm` for this. On dialogue-with-pauses material it
silently switches to dynamic mode and lifts quiet passages and the noise floor by 30-50 dB,
turning a clean take into a hissy master. `dramapack master` and `dramapack package` do
the constant-gain version for you.

```bash
dramapack inspect ep01.mp4            # integrated LUFS, true peak, gain needed
dramapack master cut01.mp4 ep01.mp4 --srt 01.srt
```

## The numbers

| Material | Typical loudness |
|---|---|
| Raw AI-video renders / early masters | mean volume -24.7 to -27.4 dB |
| Competing vertical dramas | mean volume -16.0 to -21.5 dB |
| High-performing titles on distribution networks | about -12.4 LUFS |
| dramapack target | **-14 LUFS**, peak ceiling -1 dBFS |

An A/B listen of -15.8 vs -14.0 LUFS on phones settled the target: at -15.8 episodes
already sound "half as loud" next to the feed around them.

## Why not loudnorm

- Single-pass `loudnorm` is **dynamic**: it pushes short-term loudness toward the target in
  roughly 3-second windows, so pauses and room tone get pushed up.
- Two-pass `loudnorm ... linear=true` only *permits* linear mode. If the source loudness
  range (LRA) exceeds the target LRA (11) or the linear gain would break the true-peak
  ceiling, ffmpeg **silently falls back to dynamic** (the second pass prints
  `normalization_type=dynamic`).
- Dialogue-plus-silence short-drama takes have an LRA of 15-20, so the fallback is the
  norm. Measured on a real master: quiet passages +33 dB, the near-silent tail +49 dB, noise
  floor -76 -> -30 dBFS.

dramapack instead measures integrated LUFS, applies **one** `volume` gain (clamped to
-24...+20 dB so near-silent takes aren't pushed into audible noise) and an `alimiter` at
-1 dBFS. SNR is unchanged; only peaks above the ceiling are touched. The test suite pins
this: a three-step signal must be lifted by the same amount at every step.

## Measure on the dialogue, not on the mix

Integrated LUFS uses a relative gate. Once a music bed is laid, the bed in quiet passages
gets let through the gate and drags the measurement down 2-3 LU (a -14.8 LUFS cut measured
-18.4 after bedding). Normalising the mix would push dialogue 3-4 dB into the limiter.
dramapack measures the dry dialogue cut and applies that gain to the bedded mix.

## The music bed has to be audible on a phone

The optional procedural bed (`--bed tension|warm|suspense|dread|hope`) covers splice seams
(one measured seam dropped from a 40.8 dB to a 24.6 dB level jump). A first version that
kept all its energy under 300 Hz was inaudible on phones, which can't reproduce that
band, so the bed now carries midrange and **ducks under dialogue** via a sidechain
compressor instead. At the default -6 dB the bed adds only about +0.1 dB to the speech
band during lines.

See also: [reference.md](reference.md), [clean-master.md](clean-master.md).
