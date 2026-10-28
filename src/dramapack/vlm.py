"""Optional vision-model checks for the audit: bring your own key, or run a local model.

**Off by default.** Runs only when the caller asks (``--vlm`` / ``vlm=True``) AND these
environment variables are all set:

    DRAMAPACK_VLM_BASE_URL   OpenAI-compatible base URL, e.g. https://api.openai.com/v1
    DRAMAPACK_VLM_API_KEY    the provider's key (any non-empty string for a local server)
    DRAMAPACK_VLM_MODEL      a vision-capable model name

Optional: ``DRAMAPACK_VLM_TIMEOUT`` (seconds per request, default 120) and
``DRAMAPACK_VLM_RETRIES`` (default 2).

Transport is Chat Completions (``POST {base}/chat/completions``) with images as base64
``data:`` URIs, so any OpenAI-compatible server works, including a fully offline one
(Ollama, vLLM). Standard library only (``urllib``). The key is sent only in the
``Authorization`` header to the configured URL and is scrubbed from every error message.

Frames: N evenly spaced + one frame just after each scene cut, capped
(``max_frames``), downscaled to 640 px on the long side, JPEG. One request per check set:

- ``visual``: deformed faces / hands / extra limbs, garbled on-screen text,
  flicker / smearing artifacts, a character's identity drifting between frames.
- ``compliance``: typical platform-policy flags (sexual content, graphic violence, minors
  in unsafe contexts, self-harm). Flags for human review, not legal advice.
- ``hook``: frame 0 only - is a person visible, is any text legible.

**Judging approach** (calibrated on AI-drama renders): ``yes`` needs concrete evidence the
model can point to (which frame, where, what); ``unsure`` is reserved for "the relevant
part is too small, blurred or out of frame". Normal lighting / angle / expression / makeup
changes are not identity drift; an outfit change alone does not prove a different person;
over-the-shoulder partial figures are not extra people; motion blur and film grain are not
artifacts; legible physical signs are not garbled text. ``unsure`` never grades red.
A model can be wrong both ways: red here means "a person should look", not "rejected".

Lip-sync is **not** checked: still frames cannot show it.
"""
import base64
import json
import os
import re
import subprocess
import sys
import time
import urllib.error
import urllib.request

ENV_BASE, ENV_KEY, ENV_MODEL = ("DRAMAPACK_VLM_BASE_URL", "DRAMAPACK_VLM_API_KEY",
                                "DRAMAPACK_VLM_MODEL")
DEFAULT_MAX_FRAMES = 12
EVEN_FRAMES = 6          # evenly spaced samples before the after-cut frames are added
AFTER_CUT_S = 0.3        # a frame right on the cut can be a blend of both shots
MIN_GAP_S = 0.5          # drop samples closer than this to an earlier one
FRAME_LONG_SIDE = 640    # enough to see hands and text; ~40-60 KB per JPEG
FF_TIMEOUT = 60
CHECKS = ("visual", "compliance", "hook")

GREEN, YELLOW, RED = "green", "yellow", "red"
_ORDER = {GREEN: 0, YELLOW: 1, RED: 2}

_COMMON = """You are a strict quality-control reviewer for short vertical dramas (often
AI-generated). You get still frames from ONE episode, in time order, each labelled with
its frame number and timestamp. Answer only the questions asked. No aesthetic opinions.

Rules for every answer:
- "yes" = you can point to concrete evidence: which frame, where in the picture, what you
  see. Evidence in a single frame, or in a small part of the frame, still counts as yes.
- "no" = you looked at every relevant frame and it is not there.
- "unsure" = ONLY when the relevant part is genuinely not visible (too small, blurred,
  occluded, out of frame). Do not retreat to unsure because something "might be style".
- Output ONE JSON object and nothing else. No markdown, no code fences.
- All free text in English, at most one sentence each."""

_VISUAL = _COMMON + """

Questions (answer each with "yes", "no" or "unsure"):
- anatomy: a clearly visible anatomy failure - extra or missing fingers or limbs, a melted
  or distorted face, broken joints, a hand fused into an object. Hands or limbs that are
  moving (motion-blurred), cut off by the frame edge, or too small to count fingers are
  NOT anatomy failures - answer "unsure" for them, not "yes".
- garbled_text: on-screen text that is garbled, misspelled gibberish or melted glyphs
  (captions, signs, screens, documents). Clean legible text, and burned subtitles that
  read correctly, are NOT a defect.
- artifacts: rendering artifacts - smeared or warping regions, flicker banding, blocky
  corruption, a frame half from another shot. Motion blur, film grain, depth of field and
  deliberate stylisation are NOT artifacts.
- identity_drift: the SAME character clearly changes identity between frames - different
  face structure, age or build, not just lighting, angle, expression or makeup. A changed
  outfit alone does not prove a different person; different characters in different
  shots are normal editing; an over-the-shoulder shoulder or back is not a new person.

JSON: {"anatomy": "...", "garbled_text": "...", "artifacts": "...",
"identity_drift": "...", "evidence": [{"check": "<question id>", "frame": <number>,
"note": "<what and where>"}]}  (evidence only for yes answers; [] otherwise)"""

_COMPLIANCE = _COMMON + """

Flag content that typical short-video platform policies restrict. Answer each with
"none", "mild" or "explicit" ("unsure" only if the relevant part is not visible):
- sexual: nudity or sexual activity. Kissing, embraces and swimwear are "mild" at most.
- violence: injury, blood, gore, weapons used on people. Slaps, shoves and staged fights
  without visible injury are "mild"; visible wounds, heavy blood or gore are "explicit".
- minors: a person who looks under 18 in a sexualised, dangerous or abusive situation
  ("explicit"); a child merely present in a normal scene is "none".
- self_harm: self-harm or suicide depicted or shown as method ("explicit"); implied or
  aftermath without detail is "mild".

This is a flag for human review, not a legal judgement. Do not flag based on story
context you imagine - only what is visible in the frames.

JSON: {"sexual": "...", "violence": "...", "minors": "...", "self_harm": "...",
"evidence": [{"check": "<category>", "frame": <number>, "note": "<what is visible>"}]}
(evidence only for mild / explicit answers; [] otherwise)"""

_HOOK = _COMMON + """

This is the FIRST frame of the episode - the frame a viewer sees before deciding to swipe.
Questions:
- person_visible: "yes" if at least one person's face or upper body is clearly visible
  (a character, not a tiny background figure), else "no".
- text: "none" if there is no on-screen text, "legible" if all text reads cleanly,
  "illegible" if any text is garbled, cut off or too small to read on a phone.

JSON: {"person_visible": "...", "text": "...", "note": "<one sentence on what the frame
shows>"}"""

#: check -> (system prompt, {question: allowed answers}, how answers map to levels)
SPECS = {
    "visual": (_VISUAL, {q: ("yes", "no", "unsure") for q in
                         ("anatomy", "garbled_text", "artifacts", "identity_drift")}),
    "compliance": (_COMPLIANCE, {q: ("none", "mild", "explicit", "unsure") for q in
                                 ("sexual", "violence", "minors", "self_harm")}),
    "hook": (_HOOK, {"person_visible": ("yes", "no", "unsure"),
                     "text": ("none", "legible", "illegible", "unsure")}),
}
# Levels per answer. Visual: a real anatomy / identity / text failure is what viewers
# screenshot and comment on (red); artifacts are often brief (yellow). Compliance:
# explicit = red (do not ship before a person reviews), mild = yellow (may need an age
# rating or a platform's sensitive-content flag). Hook: advisory only, yellow at most.
LEVELS = {
    "visual": {"anatomy": {"yes": RED}, "garbled_text": {"yes": RED},
               "artifacts": {"yes": YELLOW}, "identity_drift": {"yes": RED}},
    "compliance": {q: {"mild": YELLOW, "explicit": RED}
                   for q in ("sexual", "violence", "minors", "self_harm")},
    "hook": {"person_visible": {"no": YELLOW}, "text": {"illegible": YELLOW}},
}
KEY = {"visual": "vlm_visual", "compliance": "vlm_compliance", "hook": "vlm_hook"}


class VLMError(RuntimeError):
    """Transport / API failure (already retried)."""


class ReplyError(VLMError):
    """The model answered, but not with the JSON asked for (worth one re-ask)."""


def config_from_env(env=None) -> tuple:
    """-> ``(config | None, message)``. Never returns or prints the key's value."""
    env = os.environ if env is None else env
    missing = [k for k in (ENV_BASE, ENV_KEY, ENV_MODEL) if not (env.get(k) or "").strip()]
    if missing:
        return None, ("VLM checks skipped: set " + ", ".join(missing) +
                      " (see docs/short-drama-qc-local.md)")
    def num(k, d):
        try:
            return float(env.get(k) or d)
        except ValueError:
            return d
    cfg = {"base_url": env[ENV_BASE].strip().rstrip("/"), "api_key": env[ENV_KEY].strip(),
           "model": env[ENV_MODEL].strip(), "timeout": num("DRAMAPACK_VLM_TIMEOUT", 120.0),
           "retries": int(num("DRAMAPACK_VLM_RETRIES", 2))}
    return cfg, f"VLM checks: model {cfg['model']} at {cfg['base_url']}"


def scrub(text: str, key: str | None) -> str:
    """Remove the key (and any bearer token) from text that may be logged or returned."""
    text = str(text)
    if key:
        text = text.replace(key, "***")
    return re.sub(r"(?i)(bearer\s+)[A-Za-z0-9._\-]{8,}", r"\1***", text)


# ---- frames -------------------------------------------------------------------------

def sample_times(dur: float, cut_times, max_frames: int = DEFAULT_MAX_FRAMES) -> list:
    """Frame 0, ``EVEN_FRAMES`` evenly spaced, then one just after each scene cut (spread
    evenly over the episode when there are more cuts than room), capped at ``max_frames``."""
    max_frames = max(1, int(max_frames))
    if dur <= 0:
        return [0.0]
    end = max(0.0, dur - 0.1)
    even = [round(end * i / EVEN_FRAMES, 2) for i in range(EVEN_FRAMES)]
    after = [round(min(end, t + AFTER_CUT_S), 2) for t in sorted(cut_times or [])]
    picked: list = []

    def add(t):
        if all(abs(t - p) >= MIN_GAP_S for p in picked):
            picked.append(t)

    for t in even:
        add(t)
    room = max_frames - len(picked)
    if room > 0 and after:
        step = max(1, len(after) / room)
        for j in range(min(room, len(after))):
            add(after[int(j * step)])
    picked = sorted(picked)[:max_frames] if len(picked) > max_frames else sorted(picked)
    if 0.0 not in picked:          # frame 0 always: the hook check needs it
        picked = [0.0] + picked[:max_frames - 1]
    return picked


def grab_jpeg(exe: str, path: str, t: float) -> bytes:
    vf = (f"scale='if(gt(iw,ih),{FRAME_LONG_SIDE},-2)':'if(gt(iw,ih),-2,{FRAME_LONG_SIDE})'")
    r = subprocess.run([exe, "-v", "error", "-ss", f"{t:.3f}", "-i", path, "-frames:v", "1",
                        "-vf", vf, "-q:v", "4", "-f", "image2", "-c:v", "mjpeg", "pipe:1"],
                       capture_output=True, timeout=FF_TIMEOUT)
    if r.returncode or not r.stdout:
        raise VLMError(f"frame grab at {t:.2f}s failed")
    return r.stdout


# ---- transport ----------------------------------------------------------------------

def _post(cfg: dict, body: dict) -> dict:
    data = json.dumps(body).encode()
    req = urllib.request.Request(cfg["base_url"] + "/chat/completions", data=data,
                                 method="POST",
                                 headers={"Content-Type": "application/json",
                                          "Authorization": f"Bearer {cfg['api_key']}"})
    with urllib.request.urlopen(req, timeout=cfg["timeout"]) as r:  # noqa: S310
        return json.loads(r.read().decode("utf-8", "replace"))


def chat(cfg: dict, system: str, content: list, *, sleep=time.sleep) -> str:
    """One Chat Completions call with retries on 429 / 5xx / network errors. Returns the
    message text. Errors are raised as VLMError with the key scrubbed."""
    body = {"model": cfg["model"], "max_tokens": 1200,
            "messages": [{"role": "system", "content": system},
                         {"role": "user", "content": content}]}
    # No temperature / response_format: several compatible endpoints reject or ignore
    # them (some models only accept the default temperature). The prompt asks for JSON
    # and the reply is validated instead.
    last = "no attempt"
    for attempt in range(cfg.get("retries", 2) + 1):
        if attempt:
            sleep(min(30.0, 2.0 * 2 ** (attempt - 1)))
        try:
            d = _post(cfg, body)
            msg = (d.get("choices") or [{}])[0].get("message") or {}
            c = msg.get("content")
            if isinstance(c, list):    # some servers return content parts
                c = "".join(p.get("text", "") for p in c if isinstance(p, dict))
            if not isinstance(c, str):
                raise ReplyError("response has no message content")
            return c
        except urllib.error.HTTPError as e:
            try:
                detail = e.read().decode("utf-8", "replace")[:200]
            except Exception:  # noqa: BLE001
                detail = ""
            last = f"HTTP {e.code}: {detail}"
            if e.code not in (408, 409, 429) and e.code < 500:
                break                # 400/401/403/404: retrying will not help
        except (urllib.error.URLError, TimeoutError, OSError, ValueError) as e:
            last = f"{type(e).__name__}: {e}"
    raise VLMError(scrub(last, cfg.get("api_key")))


def parse_json(text: str) -> dict:
    """Model reply -> dict. Tolerates code fences and prose around one JSON object."""
    t = (text or "").strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    try:
        d = json.loads(t)
    except ValueError:
        a, b = t.find("{"), t.rfind("}")
        if a < 0 or b <= a:
            raise ReplyError("reply is not JSON") from None
        try:
            d = json.loads(t[a:b + 1])
        except ValueError:
            raise ReplyError("reply is not JSON") from None
    if not isinstance(d, dict):
        raise ReplyError("reply is not a JSON object")
    return d


def validate(check: str, d: dict) -> dict:
    """Strict: every question present with an allowed answer, else VLMError."""
    _, questions = SPECS[check]
    answers = {}
    for q, allowed in questions.items():
        v = str(d.get(q, "")).strip().lower()
        if v not in allowed:
            raise ReplyError(f"{check}: missing or invalid answer for {q!r}")
        answers[q] = v
    ev = d.get("evidence") if isinstance(d.get("evidence"), list) else []
    evidence = [{"check": str(e.get("check", ""))[:40], "frame": e.get("frame"),
                 "note": str(e.get("note", ""))[:200]} for e in ev if isinstance(e, dict)]
    return {"answers": answers, "evidence": evidence[:20], "note": str(d.get("note") or "")[:200]}


def grade_check(check: str, answers: dict) -> tuple:
    """-> (level, findings). ``unsure`` never raises the level."""
    findings, level = [], GREEN
    for q, v in answers.items():
        lv = LEVELS[check].get(q, {}).get(v)
        if lv:
            findings.append({"check": check, "item": q, "answer": v, "level": lv})
            if _ORDER[lv] > _ORDER[level]:
                level = lv
    return level, findings


# ---- runner -------------------------------------------------------------------------

def _img(b: bytes) -> dict:
    return {"type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64," + base64.b64encode(b).decode()}}


def plan(n_files: int, max_frames: int) -> dict:
    return {"requests_per_file": len(CHECKS), "max_frames_per_file": max_frames,
            "files": n_files, "requests": len(CHECKS) * n_files,
            "images_max": n_files * (2 * max_frames + 1)}


def run_checks(cfg: dict, exe: str, path: str, dur: float, cut_times, *,
               max_frames: int = DEFAULT_MAX_FRAMES, log=None, chat_fn=None) -> dict:
    """Sample frames, run the three check sets, return audit fields. A failed check set
    (network, malformed reply) is reported in ``vlm_errors`` and graded nothing - a broken
    checker must not block delivery, and must not pass silently either."""
    log = log or (lambda *a: print(*a, file=sys.stderr, flush=True))
    chat_fn = chat_fn or chat
    times = sample_times(dur, cut_times, max_frames)
    frames = []
    for t in times:
        try:
            frames.append((t, grab_jpeg(exe, path, t)))
        except (VLMError, subprocess.TimeoutExpired) as e:
            log(f"vlm: {e}")
    out: dict = {"vlm_frames": [t for t, _ in frames], "vlm_findings": [],
                 "vlm_evidence": [], "vlm_errors": []}
    if not frames:
        out["vlm_errors"].append("no frames could be extracted")
        return out
    labelled = []
    for n, (t, b) in enumerate(frames):
        labelled += [{"type": "text", "text": f"[frame {n} at {t:.2f}s]"}, _img(b)]
    inputs = {"visual": labelled, "compliance": labelled,
              "hook": [{"type": "text", "text": "[frame 0 at 0.00s]"}, _img(frames[0][1])]}
    for check in CHECKS:
        system = SPECS[check][0]
        res, err = None, None
        for _ in range(2):                # one re-ask on a malformed reply
            try:
                res = validate(check, parse_json(chat_fn(cfg, system, inputs[check])))
                break
            except ReplyError as e:
                err = str(e)
            except VLMError as e:         # transport: chat() already retried
                err = str(e)
                break
        if res is None:
            err = scrub(err or "no reply", cfg.get("api_key"))
            out["vlm_errors"].append(f"{check}: {err}")
            log(f"vlm {check} skipped: {err}")
        if res is None:
            continue
        level, findings = grade_check(check, res["answers"])
        out[KEY[check]] = level
        out[f"{KEY[check]}_answers"] = res["answers"]
        for f in findings:
            evs = [e for e in res["evidence"] if e["check"] == f["item"]]
            if evs:
                f["frame"] = evs[0]["frame"]
                fr = evs[0]["frame"]
                if isinstance(fr, int) and 0 <= fr < len(frames):
                    f["t"] = frames[fr][0]
                f["note"] = evs[0]["note"]
            out["vlm_findings"].append(f)
        if check == "hook" and res["note"]:
            out["vlm_hook_note"] = res["note"]
    return out
