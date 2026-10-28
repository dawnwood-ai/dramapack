"""``dramapack`` command line: master | package | audit | check-rights | inspect | mcp.

Exit codes (stable):
  0  success; nothing red (yellow findings / non-blocking gaps are still 0)
  1  completed, but the result is red (audit red metric, rights red, or
     ``package --strict`` with gaps or a red rights check)
  2  usage error (bad arguments)
  3  runtime failure (ffmpeg missing, unreadable input, encode failed)

With ``--json`` the only thing on stdout is one JSON object (progress goes to stderr).
Failures print ``{"ok": false, "error": "..."}``.
"""
import argparse
import json
import sys

from . import api
from . import master as M
from .provenance import PROVENANCE, footer_line

EXIT_OK, EXIT_RED, EXIT_USAGE, EXIT_FAIL = 0, 1, 2, 3


def _emit(a, res: dict, human) -> None:
    if a.json:
        print(json.dumps(res, ensure_ascii=False, indent=2))
    else:
        human(res)


def _cmd_master(a) -> int:
    end_card = None
    if a.end_card_title or a.end_card_line:
        end_card = {"title": a.end_card_title or "", "lines": a.end_card_line or [],
                    "site": a.end_card_site or ""}
    res = api.master_episode(a.input, a.output, srt=a.srt, burn=not a.no_burn, bed=a.bed,
                             music=a.music, music_db=a.music_db, head_trim=a.head_trim,
                             end_card=end_card, card_secs=a.card_secs, cover_band=a.cover_band,
                             subtitle_font=a.subtitle_font, normalize=not a.no_normalize)
    _emit(a, res, lambda r: print(f"wrote {r['output']} ({r['spec'].get('duration_s')} s)"))
    return EXIT_OK


def _cmd_package(a) -> int:
    eps = [int(x) for x in a.episodes.split(",")] if a.episodes else None
    res = api.build_package(a.input_dir, a.output_dir, show=a.show, rights=a.rights,
                            title=a.title, studio=a.studio, language=a.language, bed=a.bed,
                            music=a.music, masters_ready=a.masters_ready, episodes=eps,
                            platform_pairs=a.platform_pairs, clean=not a.no_clean,
                            covers=not a.no_covers, timeline=not a.no_timeline,
                            keep_work=a.keep_work)

    def human(r):
        print(f"\n{len(r['episodes'])} episodes -> {r['output_dir']}  [{r['status']}]")
        print(f"rights check: {r['rights_status']}")
        for g in r["gaps"]:
            print(f"  gap: {g}")
        for n in r["notes"]:
            print(f"  note: {n}")
        print(footer_line())

    _emit(a, res, human)
    if res["status"] == "red" or (a.strict and res["gaps"]):
        return EXIT_RED
    return EXIT_OK


def _cmd_audit(a) -> int:
    from .audit import format_table
    bounds = [float(x) for x in a.bounds.split(",")] if a.bounds else None
    res = api.audit_files(a.files, cut=a.cut, bounds=bounds, speech=not a.no_speech,
                          hook_plugin=a.hook_plugin, srt=a.srt, align=not a.no_align,
                          srt_lang=a.srt_lang, vlm=a.vlm, vlm_max_frames=a.vlm_max_frames)

    def human(r):
        for s in r["skipped"]:
            print(f"skipped: {s}", file=sys.stderr)
        print(format_table(r["rows"]))

    _emit(a, res, human)
    return EXIT_RED if res["status"] == "red" else EXIT_OK


def _cmd_rights(a) -> int:
    from .rights import format_report
    res = api.check_rights(a.rights, input_dir=a.input, bed=a.bed, music=a.music,
                           subtitle_font=None if a.no_mastering_fonts else a.subtitle_font,
                           end_card=a.end_card and not a.no_mastering_fonts,
                           allow_fonts=a.allow_font or ())
    _emit(a, res, lambda r: print(format_report(r)))
    return EXIT_RED if res["status"] == "red" else EXIT_OK


def _cmd_inspect(a) -> int:
    res = api.inspect_file(a.file)

    def human(r):
        for k, v in r.items():
            if k not in ("ok",):
                print(f"{k:28} {v}")

    _emit(a, res, human)
    return EXIT_OK


def _cmd_mcp(a) -> int:
    from .mcp_server import run
    run()
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    ap = argparse.ArgumentParser(
        prog="dramapack",
        description=f"dramapack {PROVENANCE['version']} by Dawnwood — short-drama delivery "
                    f"packs, mastering, acceptance audit and rights check. {PROVENANCE['url']}",
        epilog="exit codes: 0 ok, 1 red result, 2 usage error, 3 runtime failure")
    ap.add_argument("--version", action="version", version=f"%(prog)s {PROVENANCE['version']}")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, **kw):
        p = sub.add_parser(name, **kw)
        p.add_argument("--json", action="store_true",
                       help="print one JSON object on stdout (progress goes to stderr)")
        return p

    m = add("master", help="master one episode (subtitles, -14 LUFS, bed, end card)")
    m.add_argument("input")
    m.add_argument("output")
    m.add_argument("--srt", help="subtitles to burn in")
    m.add_argument("--no-burn", action="store_true", help="clean master: do not burn subtitles")
    m.add_argument("--bed", choices=M.BED_MOODS, help="lay a procedural music bed of this mood")
    m.add_argument("--music", help="your own music bed file (declare it in rights.json)")
    m.add_argument("--music-db", type=float, default=M.MUSIC_DB)
    m.add_argument("--head-trim", type=float, default=0.0, help="cut N seconds off the head")
    m.add_argument("--end-card-title")
    m.add_argument("--end-card-line", action="append", help="CTA line (repeatable)")
    m.add_argument("--end-card-site")
    m.add_argument("--card-secs", type=float, default=M.CARD_SECS)
    m.add_argument("--cover-band", type=float, default=0.0,
                   help="blur this fraction of the frame bottom first (re-subtitling)")
    m.add_argument("--subtitle-font", default=M.SUB_FONT)
    m.add_argument("--no-normalize", action="store_true")
    m.set_defaults(func=_cmd_master)

    p = add("package", help="build a platform delivery pack from an input folder")
    p.add_argument("input_dir")
    p.add_argument("output_dir")
    p.add_argument("--show", help="show.json (default: <input_dir>/show.json)")
    p.add_argument("--rights", help="rights.json (default: <input_dir>/rights.json)")
    p.add_argument("--title")
    p.add_argument("--studio")
    p.add_argument("--language")
    p.add_argument("--bed", choices=M.BED_MOODS, help="procedural music bed mood")
    p.add_argument("--music", help="your own music bed file")
    p.add_argument("--masters-ready", action="store_true",
                   help="NN.mp4 are finished subtitled masters (clean master from NN.cut.mp4)")
    p.add_argument("--episodes", help="comma-separated episode numbers (default: all)")
    p.add_argument("--platform-pairs", action="store_true",
                   help="also build two-episodes-per-file platform cuts")
    p.add_argument("--no-clean", action="store_true")
    p.add_argument("--no-covers", action="store_true")
    p.add_argument("--no-timeline", action="store_true")
    p.add_argument("--keep-work", action="store_true", help="keep the _work scratch folder")
    p.add_argument("--strict", action="store_true",
                   help="exit 1 when the pack has any gap (red results always exit 1)")
    p.set_defaults(func=_cmd_package)

    u = add("audit", help="acceptance audit against short-drama benchmarks")
    u.add_argument("files", nargs="+")
    u.add_argument("--cut", help="raw cut of the (single) master: grade each on its own metrics")
    u.add_argument("--bounds", help="splice points in seconds, comma-separated (seam metric)")
    u.add_argument("--no-speech", action="store_true", help="skip faster-whisper entirely (speech metrics and subtitle alignment)")
    u.add_argument("--hook-plugin", metavar="MODULE:FUNC",
                   help="optional hook-window checker f(path, ffmpeg) -> {fails, warns, note}")
    u.add_argument("--srt", help="subtitles of the (single) file for alignment "
                                 "(default: same-name .srt next to each file)")
    u.add_argument("--srt-lang", help="subtitle language code (enables the text check "
                                      "when it matches the audio)")
    u.add_argument("--no-align", action="store_true",
                   help="skip subtitle/speech alignment")
    u.add_argument("--vlm", action="store_true",
                   help="vision-model checks with your own endpoint: needs DRAMAPACK_VLM_BASE_URL, "
                        "DRAMAPACK_VLM_API_KEY, DRAMAPACK_VLM_MODEL (sends sampled frames there)")
    u.add_argument("--vlm-max-frames", type=int, default=12,
                   help="cap on frames sampled per file for --vlm (default 12)")
    u.set_defaults(func=_cmd_audit)

    r = add("check-rights", help="grade declared music and fonts red/yellow/green")
    r.add_argument("rights", nargs="?", help="rights.json")
    r.add_argument("--input", help="input folder (rights.json default, *.ass font scan)")
    r.add_argument("--bed", choices=M.BED_MOODS, help="procedural bed in use (auto-declared)")
    r.add_argument("--music", help="music file used in mastering (must be declared)")
    r.add_argument("--subtitle-font", default=M.SUB_FONT)
    r.add_argument("--end-card", action="store_true", help="include the end-card font")
    r.add_argument("--no-mastering-fonts", action="store_true",
                   help="don't check the fonts this tool burns in")
    r.add_argument("--allow-font", action="append", help="extend the font allowlist")
    r.set_defaults(func=_cmd_rights)

    i = add("inspect", help="measured specs + integrated LUFS / true peak of a media file")
    i.add_argument("file")
    i.set_defaults(func=_cmd_inspect)

    s = sub.add_parser("mcp", help="run the MCP server on stdio (for AI agents)")
    s.set_defaults(func=_cmd_mcp, json=False)
    return ap


def main(argv=None) -> int:
    a = build_parser().parse_args(argv)
    try:
        return a.func(a)
    except Exception as e:  # noqa: BLE001
        msg = f"{type(e).__name__}: {e}"
        if getattr(a, "json", False):
            print(json.dumps({"ok": False, "error": msg}))
        else:
            print(f"dramapack: error: {msg}", file=sys.stderr)
        return EXIT_FAIL


if __name__ == "__main__":
    sys.exit(main())
