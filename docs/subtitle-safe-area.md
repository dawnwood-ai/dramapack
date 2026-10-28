# Keeping burned subtitles inside the safe area and clear of the player bar

For vertical 9:16 short dramas, burn subtitles with a **bottom margin of 18% of frame
height** (346 px on 1080x1920) and **left/right margins of 16% of frame width** (173 px),
so the text box is **at most 70% of the frame width**. That keeps lines clear of
the player's progress bar and hover controls and of feed UI, and satisfies TikTok Drama
Center's subtitle safe-area rule (text box <= 70% of width). `dramapack master --srt` and
`dramapack package` apply this automatically, in real pixels.

## The ffmpeg pitfall that breaks every size you set

ffmpeg converts SRT to ASS on a default **384x288** canvas (`PlayResX/PlayResY`). libass
then scales every size by `video_height / PlayResY`, about 6.7x on 1920-high video. So
`subtitles=...:force_style='FontSize=22'` burns ~147 px glyphs and three lines smeared
across the middle of the frame, and margins are scaled too. dramapack converts SRT to ASS,
**pins PlayRes to the video size**, and writes the style in real pixels.

## The numbers dramapack uses

| Setting | Value | Why |
|---|---|---|
| Bottom margin | 18% of height (min 150 px) | A fixed ~8% sits exactly under player hover controls / progress bar and the feed's bottom UI |
| Side margins | 16% of width (min 60 px) | Text box <= 70% of width. A fixed 60 px let lines run to 89% width, and a whole season was flagged "Optimizable" |
| Font size | 52 px (at 1080 wide) | Readable on phones without covering faces |
| Style | white, bold, 4 px black outline + 2 px shadow, bottom-centre | Legible on any background |
| Font | Noto Sans CJK SC | Pinned so every machine renders the same glyphs (see below); free for commercial use |

## Pin the font family

ffmpeg-generated ASS defaults to `Fontname=Arial`. What libass renders then depends on the
machine's fontconfig: one machine maps Arial to Liberation Sans Bold, another falls back to
Noto, and the same font size comes out visibly larger on one than the other. Pinning a
family keeps every render identical. Arial is also not free for commercial use, which
`dramapack check-rights` flags. If the pinned font isn't installed, the rights check warns
you and also checks the substitute.

## Re-subtitling footage that already has burned subtitles

`dramapack master --cover-band 0.2` blurs and darkens the bottom 20% of the frame before
burning new subtitles: useful for localised versions of footage that came with burned-in
subtitles.

## Head trims must shift the subtitles

If you cut dead frames off the head (`--head-trim 0.95`), the subtitles must move with
the picture. `-ss` as an input option resets timestamps while the subtitle filter's times
are absolute, so every line would land late by the trim. dramapack shifts the SRT, drops
cues that fall entirely inside the trimmed head, and delivers the shifted SRT in the pack.

See also: [reference.md](reference.md).
