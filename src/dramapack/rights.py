"""Rights hygiene check for music and fonts (``check-rights``).

Distributors of overseas short dramas publish copyright standards that converge on the
same rules:

* **Music**: avoid anything controlled by the major labels / their publishing arms (Sony,
  Universal, Warner and their imprints) — those catalogues are fingerprinted and claimed
  automatically on every platform. Prefer public-domain works (published > 50 years ago),
  music licensed from small/independent artists with written proof, or AI-generated /
  procedurally generated music.
* **Fonts**: every font rendered into the picture must be free for commercial use (or
  commercially licensed, with proof).

This module checks a declaration file (``rights.json``, schema in the README) plus the
fonts this tool itself renders, and grades each item red / yellow / green. It is a
hygiene check, not legal advice: it can only see what you declare and what it renders.
"""
import datetime
import json
import os
import re
import shutil
import subprocess

MUSIC_SOURCES = ("generated", "procedural", "public_domain", "licensed", "unknown")

#: Publishers / labels / rights owners that are red regardless of the declared source.
#: Matched case-insensitively against ``publisher``, ``label`` and ``rights_owner``.
#: Extend per project with ``"blocked_publishers": [...]`` in rights.json.
MAJOR_LABEL_PATTERNS = (
    # Sony
    r"\bsony\b", r"\bcolumbia records\b", r"\brca records\b", r"\bepic records\b",
    r"\barista\b", r"\blegacy recordings\b", r"\bsony/atv\b",
    # Universal
    r"\buniversal music\b", r"\bumg\b", r"\buniversal production music\b",
    r"\binterscope\b", r"\bdef jam\b", r"\brepublic records\b", r"\bisland records\b",
    r"\bcapitol records\b", r"\bmotown\b", r"\bgeffen\b", r"\bpolydor\b", r"\bdecca\b",
    r"\bdeutsche grammophon\b", r"\bvirgin music\b", r"\bemi\b",
    # Warner
    r"\bwarner\b", r"\bwmg\b", r"\batlantic records\b", r"\belektra\b",
    r"\bparlophone\b", r"\bwarner chappell\b", r"\bnonesuch\b",
)

#: Native-script aliases are written as \u escapes (the source stays ASCII); each carries
#: its English family name in the licence note.
#: Font families known to be free for commercial use (embedding in video included).
#: Matched case-insensitively as a prefix of the family name, so "Noto" covers
#: "Noto Sans CJK SC", "Noto Serif", etc. Extend with ``"font_allowlist"`` in rights.json
#: or ``--allow-font`` on the command line.
FONT_ALLOWLIST = {
    "Noto": "SIL OFL 1.1",
    "Source Han Sans": "SIL OFL 1.1",
    "Source Han Serif": "SIL OFL 1.1",
    "\u601d\u6e90\u9ed1\u4f53": "SIL OFL 1.1 (Source Han Sans)",
    "\u601d\u6e90\u5b8b\u4f53": "SIL OFL 1.1 (Source Han Serif)",
    "Source Sans": "SIL OFL 1.1",
    "Source Serif": "SIL OFL 1.1",
    "Source Code": "SIL OFL 1.1",
    "DejaVu": "Bitstream Vera / public domain",
    "Liberation": "SIL OFL 1.1",
    "Roboto": "Apache 2.0 / OFL",
    "Open Sans": "SIL OFL 1.1",
    "Lato": "SIL OFL 1.1",
    "Montserrat": "SIL OFL 1.1",
    "Inter": "SIL OFL 1.1",
    "Poppins": "SIL OFL 1.1",
    "Oswald": "SIL OFL 1.1",
    "Bebas Neue": "SIL OFL 1.1",
    "Anton": "SIL OFL 1.1",
    "Fira": "SIL OFL 1.1",
    "IBM Plex": "SIL OFL 1.1",
    "Ubuntu": "Ubuntu Font Licence 1.0",
    "LXGW WenKai": "SIL OFL 1.1",
    "\u971e\u9e5c\u6587\u6977": "SIL OFL 1.1 (LXGW WenKai)",
    "Smiley Sans": "SIL OFL 1.1",
    "\u5f97\u610f\u9ed1": "SIL OFL 1.1 (Smiley Sans)",
}

#: Licence identifiers that make a *declared* font acceptable without an allowlist entry.
FREE_FONT_LICENSES = ("ofl", "sil open font", "apache", "ufl", "ubuntu font", "mit",
                      "cc0", "public domain", "bitstream vera", "gpl with font exception")

RED, YELLOW, GREEN = "red", "yellow", "green"
_ORDER = {GREEN: 0, YELLOW: 1, RED: 2}

#: Public-domain rule of thumb used by distributors: published more than 50 years ago.
#: (Terms vary by country — and a PD *composition* can still have a copyrighted
#: *recording*; the check reminds about both.)
PD_MIN_AGE_YEARS = 50


def _finding(level: str, kind: str, item: str, msg: str, **extra) -> dict:
    return {"level": level, "kind": kind, "item": item, "message": msg, **extra}


def _is_url(s: str) -> bool:
    return bool(re.match(r"^https?://", s or "", re.I))


def _major_label_hit(cue: dict, extra_patterns=()) -> str | None:
    fields = " | ".join(str(cue.get(k) or "") for k in ("publisher", "label", "rights_owner"))
    for pat in tuple(MAJOR_LABEL_PATTERNS) + tuple(extra_patterns):
        if re.search(pat if pat.startswith(r"\b") else re.escape(pat), fields, re.I):
            return pat.replace(r"\b", "")
    return None


def check_music_cue(cue: dict, *, base_dir: str = ".", blocked=(), year=None) -> dict:
    name = cue.get("cue") or cue.get("title") or "(unnamed cue)"
    src = str(cue.get("source") or "").strip().lower()
    hit = _major_label_hit(cue, blocked)
    if hit:
        return _finding(RED, "music", name,
                        f"publisher/label matches major-label pattern '{hit}' — distributors "
                        "reject major-label catalogue (automatic Content ID claims)",
                        source=src or None)
    if src not in MUSIC_SOURCES or src == "unknown":
        return _finding(RED, "music", name,
                        "music source is unknown or undeclared — declare one of "
                        "generated | procedural | public_domain | licensed",
                        source=src or None)
    if src == "licensed":
        proof = str(cue.get("proof") or "").strip()
        if not proof:
            return _finding(YELLOW, "music", name,
                            "licensed without proof — add a licence file path or URL in 'proof'",
                            source=src)
        if not _is_url(proof) and not os.path.exists(os.path.join(base_dir, proof)):
            return _finding(YELLOW, "music", name, f"licence proof not found: {proof}",
                            source=src, proof=proof)
        return _finding(GREEN, "music", name, "licensed, proof on file", source=src, proof=proof)
    if src == "public_domain":
        y = cue.get("year")
        now = year or datetime.date.today().year
        if not y:
            return _finding(YELLOW, "music", name,
                            "public domain claimed without a publication 'year'; also confirm "
                            "the *recording* (not only the composition) is public domain",
                            source=src)
        if now - int(y) <= PD_MIN_AGE_YEARS:
            return _finding(RED, "music", name,
                            f"published {y}: not more than {PD_MIN_AGE_YEARS} years ago, so not "
                            "safely public domain", source=src)
        return _finding(GREEN, "music", name,
                        f"public domain (published {y}); recording must also be PD or own "
                        "performance", source=src)
    if src == "generated":
        tool = cue.get("tool")
        msg = f"AI-generated ({tool})" if tool else \
            "AI-generated — name the 'tool' and keep its commercial-use terms on file"
        return _finding(GREEN, "music", name, msg, source=src)
    return _finding(GREEN, "music", name, "procedurally generated", source=src)


def font_allowed(name: str, allowlist: dict) -> str | None:
    n = (name or "").strip().lower()
    for fam, lic in allowlist.items():
        if n.startswith(fam.lower()):
            return lic
    return None


def check_font(font: dict, allowlist: dict, *, base_dir: str = ".") -> dict:
    name = font.get("name") or "(unnamed font)"
    origin = font.get("origin") or "declared"
    lic = font_allowed(name, allowlist)
    if lic:
        f = _finding(GREEN, "font", name, f"commercially free ({lic})", origin=origin)
    else:
        declared = str(font.get("license") or "").lower()
        proof = str(font.get("proof") or "")
        has_proof = bool(proof) and (_is_url(proof) or os.path.exists(os.path.join(base_dir, proof)))
        if declared and any(k in declared for k in FREE_FONT_LICENSES):
            f = _finding(GREEN, "font", name, f"declared free licence: {font.get('license')}",
                         origin=origin)
        elif declared and has_proof:
            f = _finding(GREEN, "font", name, f"commercial licence on file ({font.get('license')})",
                         origin=origin)
        else:
            f = _finding(RED, "font", name,
                         "font not in the commercial-free allowlist and no free licence / "
                         "licence proof declared", origin=origin)
    if font.get("substituted_by"):
        f["level"] = max(f["level"], YELLOW, key=_ORDER.get)
        f["message"] += (f"; not installed — renderer substitutes '{font['substituted_by']}' "
                         "(check that font too, and install the declared one)")
    return f


def ass_font_names(text: str) -> list:
    """Font family names used by an ASS script: Style lines and inline ``\\fn`` overrides."""
    names = []
    fmt = None
    for ln in text.splitlines():
        if ln.startswith("Format:") and "Fontname" in ln:
            fmt = [x.strip() for x in ln[len("Format:"):].split(",")]
        elif ln.startswith("Style:"):
            vals = ln[len("Style:"):].strip().split(",")
            idx = fmt.index("Fontname") if fmt and "Fontname" in fmt else 1
            if len(vals) > idx:
                names.append(vals[idx].strip().lstrip("@"))
    names += [m.strip().lstrip("@") for m in re.findall(r"\\fn([^\\}]+)", text)]
    out = []
    for n in names:
        if n and n not in out:
            out.append(n)
    return out


def fc_substitute(family: str) -> str | None:
    """The family fontconfig will actually render for ``family`` when it differs
    (libass resolves through fontconfig). None if identical or fc-match is unavailable."""
    if not shutil.which("fc-match"):
        return None
    try:
        r = subprocess.run(["fc-match", "-f", "%{family}", family], capture_output=True,
                           text=True, timeout=10)
    except Exception:  # noqa: BLE001
        return None
    got = [x.strip() for x in (r.stdout or "").split(",") if x.strip()]
    if not got:
        return None
    if any(g.lower() == family.lower() for g in got):
        return None
    return got[0]


def _card_font_family(path: str | None) -> str | None:
    if not path:
        return None
    try:
        from PIL import ImageFont  # noqa: PLC0415
        return ImageFont.truetype(path, 20).getname()[0]
    except Exception:  # noqa: BLE001
        return os.path.basename(path)


def load_rights(path: str | None) -> dict | None:
    if not path or not os.path.exists(path):
        return None
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def check_rights(rights_path: str | None = None, *, input_dir: str | None = None,
                 bed_mood: str | None = None, external_music: str | None = None,
                 subtitle_font: str | None = None, card_font_path: str | None = None,
                 extra_allow_fonts=(), check_installed: bool = True) -> dict:
    """Grade music and fonts. Returns ``{"status", "summary", "findings", "rights_file"}``.

    * ``bed_mood``: the procedural bed this tool renders — auto-declared ``procedural``.
    * ``external_music``: a music file passed to mastering; it must be declared in
      rights.json (matched by ``file`` basename) or it is red.
    * ``subtitle_font`` / ``card_font_path``: fonts this tool burns into the picture.
    * ``input_dir``: ``*.ass`` files there are scanned for font names.
    """
    rights = load_rights(rights_path)
    base = os.path.dirname(os.path.abspath(rights_path)) if rights_path else (input_dir or ".")
    findings: list = []
    blocked = tuple((rights or {}).get("blocked_publishers") or ())
    allow = dict(FONT_ALLOWLIST)
    for n in list((rights or {}).get("font_allowlist") or []) + list(extra_allow_fonts or []):
        allow[str(n)] = "project allowlist"

    # --- music
    cues = list((rights or {}).get("music") or [])
    if bed_mood:
        cues.append({"cue": f"music bed ({bed_mood}, rendered by dramapack)",
                     "source": "procedural", "auto": True})
    if rights is None:
        findings.append(_finding(RED, "music", "(all episodes)",
                                 "no rights.json — music in the source episodes is undeclared. "
                                 "Declare every cue (or \"music\": [] if there is none)"))
    elif "music" not in rights:
        findings.append(_finding(RED, "music", "(all episodes)",
                                 "rights.json has no \"music\" list — music is undeclared"))
    if external_music:
        bn = os.path.basename(external_music)
        if not any(os.path.basename(str(c.get("file") or "")) == bn for c in cues):
            findings.append(_finding(RED, "music", bn,
                                     "music file used in mastering is not declared in rights.json "
                                     "(add a cue with \"file\": \"" + bn + "\")"))
    for c in cues:
        findings.append(check_music_cue(c, base_dir=base, blocked=blocked))

    # --- fonts
    fonts: list = [dict(f, origin="declared") for f in (rights or {}).get("fonts") or []]
    seen = {str(f.get("name", "")).lower() for f in fonts}

    def add(name, origin):
        if name and name.lower() not in seen:
            seen.add(name.lower())
            fonts.append({"name": name, "origin": origin})

    if subtitle_font:
        add(subtitle_font, "burned subtitles (mastering)")
    fam = _card_font_family(card_font_path)
    if card_font_path:
        add(fam, "end card (mastering)")
    if input_dir and os.path.isdir(input_dir):
        for fn in sorted(os.listdir(input_dir)):
            if fn.lower().endswith(".ass"):
                txt = open(os.path.join(input_dir, fn), encoding="utf-8-sig", errors="replace").read()
                for n in ass_font_names(txt):
                    add(n, f"ASS style ({fn})")
    for f in fonts:
        if check_installed and f.get("origin") != "declared" and "end card" not in f["origin"]:
            sub = fc_substitute(f["name"])
            if sub:
                f["substituted_by"] = sub
        findings.append(check_font(f, allow, base_dir=base))
        if f.get("substituted_by"):   # the substitute is what actually gets burned in
            findings.append(check_font({"name": f["substituted_by"],
                                        "origin": f"substitute for {f['name']}"}, allow))

    status = max((f["level"] for f in findings), key=_ORDER.get, default=GREEN)
    summary = {lvl: sum(1 for f in findings if f["level"] == lvl) for lvl in (RED, YELLOW, GREEN)}
    return {"status": status, "summary": summary, "findings": findings,
            "rights_file": os.path.basename(rights_path) if rights else None}


def format_report(res: dict) -> str:
    mark = {RED: "RED   ", YELLOW: "YELLOW", GREEN: "green "}
    lines = [f"rights check: {res['status'].upper()}  "
             f"({res['summary'][RED]} red, {res['summary'][YELLOW]} yellow, "
             f"{res['summary'][GREEN]} green)"]
    for f in sorted(res["findings"], key=lambda x: -_ORDER[x["level"]]):
        lines.append(f"  {mark[f['level']]} {f['kind']:<5} {f['item']}: {f['message']}")
    return "\n".join(lines)
