"""SRT utilities: shift (for head trims), merge (for joined episodes), parse."""
import re

_TS = re.compile(r"(\d+):(\d\d):(\d\d)[,.](\d{1,3})\s*-->\s*(\d+):(\d\d):(\d\d)[,.](\d{1,3})")


def _fmt(t: float) -> str:
    t = max(0.0, t)
    h, r = divmod(t, 3600)
    m, s = divmod(r, 60)
    ms = int(round((s - int(s)) * 1000))
    if ms == 1000:          # 59.9996 must not print as ":59,1000"
        s, ms = int(s) + 1, 0
    return f"{int(h):02d}:{int(m):02d}:{int(s):02d},{ms:03d}"


def shift_srt(srt: str, out: str, delta: float) -> str:
    """Shift every cue in ``srt`` by ``delta`` seconds (negative = earlier), write ``out``.

    **A head trim must be paired with this.** ``-ss`` as an input option resets timestamps
    to zero while the ``ass`` filter's times are absolute — trim the picture without shifting
    the subtitles and every line lands ``head_trim`` seconds late (a 0.95 s trim is
    obvious to any viewer). Cues that end before 0 are dropped; cues crossing 0 are clamped.
    """
    block = []
    for raw in open(srt, encoding="utf-8-sig", errors="replace").read().splitlines():
        m = _TS.search(raw)
        if not m:
            block.append(raw)
            continue
        g = [int(x) for x in m.groups()]
        a = g[0] * 3600 + g[1] * 60 + g[2] + g[3] / 1000.0 + delta
        b = g[4] * 3600 + g[5] * 60 + g[6] + g[7] / 1000.0 + delta
        if b <= 0.02:                      # the whole cue sits inside the trimmed head
            block.append("__DROP__")
            continue
        block.append(f"{_fmt(a)} --> {_fmt(b)}")
    cues: list = []
    for ln in block:
        if _TS.search(ln) or ln == "__DROP__":
            cues.append([ln])
        elif cues:
            cues[-1].append(ln)
    body, n = [], 0
    for c in cues:
        if c[0] == "__DROP__":
            continue
        n += 1
        lines = [x for x in c[1:] if x.strip() and not x.strip().isdigit()]
        body += [str(n), c[0], *lines, ""]
    with open(out, "w", encoding="utf-8") as f:
        f.write("\n".join(body))
    return out


def parse_srt(path: str) -> list:
    """SRT → ``[(start, end, text)]``. Tolerant: index lines optional, blank-line blocks."""
    blocks, cur = [], []
    for line in open(path, encoding="utf-8-sig", errors="replace").read().splitlines():
        if line.strip():
            cur.append(line)
        elif cur:
            blocks.append(cur)
            cur = []
    if cur:
        blocks.append(cur)

    def secs(x):
        p = x.strip().replace(",", ".").split(":")
        return int(p[0]) * 3600 + int(p[1]) * 60 + float(p[2])

    cues = []
    for b in blocks:
        arrow = next((i for i, ln in enumerate(b) if "-->" in ln), None)
        if arrow is None:
            continue
        a, _, z = b[arrow].partition("-->")
        try:
            cues.append((secs(a), secs(z), "\n".join(b[arrow + 1:])))
        except (ValueError, IndexError):
            continue
    return cues


def merge_srt(first: str, second: str, offset: float, dest: str) -> int:
    """Append ``second`` shifted by ``offset`` seconds after ``first``; renumber.

    ``offset`` must be the **measured duration of the first episode file**, not the end of
    its last cue — an end card has no subtitles, so using the subtitle length would pull
    the whole second half early."""
    cues = parse_srt(first) + [(a + offset, z + offset, t) for a, z, t in parse_srt(second)]
    with open(dest, "w", encoding="utf-8") as f:
        for i, (a, z, t) in enumerate(cues, 1):
            f.write(f"{i}\n{_fmt(a)} --> {_fmt(z)}\n{t}\n\n")
    return len(cues)


_CUE_TIMES = re.compile(r"(\d+):(\d+):(\d+)[,.](\d+)\s*-->\s*(\d+):(\d+):(\d+)[,.](\d+)")


def _ms(h, m, s, ms):
    return ((int(h) * 60 + int(m)) * 60 + int(s)) * 1000 + int(ms)


def _ts(ms):
    return "%02d:%02d:%02d,%03d" % (ms // 3600000, ms // 60000 % 60, ms // 1000 % 60, ms % 1000)


def merge_srts(parts) -> str:
    """``[(srt_text, offset_s), …]`` → one continuously numbered SRT.

    Tolerant: empty parts and broken blocks are skipped — one bad block is not worth
    failing an episode master over. Never overlapping: when each part's last cue carries
    a hold-over past the part's end, a naive join stacks it on top of the next part's first
    cue and two lines burn at once. Cues are sorted by start and each end is clamped to
    ``next_start - 60 ms`` (keeping at least 300 ms on screen)."""
    cues = []
    for text, off in parts:
        off_ms = int(round(float(off) * 1000))
        for blk in re.split(r"\n\s*\n", (text or "").strip()):
            lines = blk.strip().split("\n")
            ti = next((i for i, x in enumerate(lines) if "-->" in x), None)
            if ti is None:
                continue
            m = _CUE_TIMES.search(lines[ti])
            if not m:
                continue
            body = lines[ti + 1:]
            if not any(x.strip() for x in body):
                continue
            g = m.groups()
            cues.append([_ms(*g[:4]) + off_ms, _ms(*g[4:]) + off_ms, body])
    cues.sort(key=lambda c: c[0])
    for i in range(len(cues) - 1):
        nxt = cues[i + 1][0]
        if cues[i][1] > nxt - 60:
            cues[i][1] = max(cues[i][0] + 300, nxt - 60)
    out = ["\n".join([str(n), f"{_ts(a)} --> {_ts(b)}"] + body)
           for n, (a, b, body) in enumerate(cues, 1)]
    return "\n\n".join(out) + ("\n" if out else "")
