"""Designed Living: floor plan, Sweet Home 3D model or room photos -> styled rooms, mood boards and a walkthrough
website (standard library only).

    python app.py               start it (http://127.0.0.1:4800) and open the browser
    python app.py --no-browser  start it without opening the browser
    python app.py --selftest    the offline checks (no keys, no model calls, a scratch folder)

It binds 127.0.0.1 only and serves web/ plus its own /api routes. Its keys live in config.json next to this file
(git-ignored, never served, never written into an exported page). Houses live in Houses/ next to it (git-ignored), or
under the folder config `data_folder` names. Taken out of Jarvis 2.0's House Plan Build (Faiek, 2026-11-24).
"""
import base64
import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import housedesign
import houseplan
import photorooms
import usage

APP = Path(__file__).resolve().parent
WEB = APP / "web"
CONFIG = APP / "config.json"
HOST, DEFAULT_PORT = "127.0.0.1", 4800
NAME = "Designed Living"
CLAUDE_API = "https://api.anthropic.com/v1/messages"
DEFAULT_CLAUDE = "claude-sonnet-5-5"
PLAN_MAX_TOKENS = 32000
CLAUDE_TIMEOUT_S = 600
TEST_TIMEOUT_S = 15
MAX_JSON_BYTES = 4 * 1024 * 1024
PREVIEW_CSP = ("default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data: blob:; "
               "connect-src data: blob:; worker-src blob:; font-src data:")
SECRET_WORDS = re.compile(r"key|token|secret|password", re.I)
STARTS = ("plan", "obj", "photos")

# Settings: (key, label, kind). Keys are secret: never sent to the page whole.
FIELDS = [
    ("gemini_api_key", "Gemini key", "secret"),
    ("anthropic_api_key", "Anthropic key", "secret"),
    ("claude_model", "Claude model for reading plans", "text"),
    ("image_model", "Room photos (Nano Banana Flash)", "text"),
    ("house_pro_model", "\"Make it better\" (Nano Banana Pro)", "text"),
    ("house_plan_model", "Gemini model for reading plans", "text"),
    ("house_read_model", "Gemini model that reads the photos back", "text"),
    ("house_cutout_model", "Gemini model that cuts the furniture out of the photos", "text"),
    ("data_folder", "Where houses are kept", "text"),
    ("brand", "Your name or business (top left of every website)", "text"),
]
LOCK = threading.Lock()


# ---------------------------------------------------------------- config
def load_config():
    try:
        data = json.loads(CONFIG.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except FileNotFoundError:
        return {}
    except (OSError, ValueError):
        print("config.json can't be read; fix it or delete it (your keys are in it).", file=sys.stderr, flush=True)
        return {}


def save_config(changes):
    with LOCK:
        if CONFIG.exists():
            try:
                cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                raise houseplan.HouseError("config.json can't be read, so it wasn't touched. Fix it first.", 409)
        else:
            cfg = {}
        known = {k for k, _, _ in FIELDS}
        for k, v in changes.items():
            if k not in known:
                continue
            v = str(v or "").strip()
            if v:
                cfg[k] = v
            else:
                cfg.pop(k, None)
        tmp = CONFIG.with_name(".config.json.tmp")
        tmp.write_text(json.dumps(cfg, indent=1), encoding="utf-8")
        try:
            os.chmod(tmp, 0o600)
        except OSError:
            pass
        os.replace(tmp, CONFIG)
    return cfg


def data_root(cfg=None):
    cfg = cfg or load_config()
    folder = str(cfg.get("data_folder") or "").strip()
    return Path(folder).expanduser() if folder else APP


def settings_view(cfg=None):
    cfg = cfg or load_config()
    out = {}
    for key, label, kind in FIELDS:
        value = str(cfg.get(key) or "")
        if kind == "secret":
            out[key] = {"label": label, "kind": kind, "set": bool(value),
                        "shown": f"set, ending {value[-4:]}" if value else "not set"}
        else:
            out[key] = {"label": label, "kind": kind, "value": value}
    defaults = {"claude_model": DEFAULT_CLAUDE, "image_model": "newest Nano Banana Flash Google lists",
                "house_pro_model": "newest Nano Banana Pro Google lists", "house_plan_model": housedesign.LOCATE_MODEL,
                "house_read_model": housedesign.READ_MODEL,
                "house_cutout_model": housedesign.CUT_MODEL, "data_folder": str(APP)}
    return {"fields": out, "defaults": defaults, "houses_folder": str(houseplan.root(data_root(cfg)))}


def secrets(cfg):
    found = []

    def walk(value, name=""):
        if isinstance(value, dict):
            for k, v in value.items():
                walk(v, str(k))
        elif isinstance(value, str) and SECRET_WORDS.search(name) and len(value) >= 12:
            found.append(value)
    walk(cfg)
    return found


def gemini_key(cfg):
    return str(cfg.get("gemini_api_key") or "").strip()


def claude_key(cfg):
    return str(cfg.get("anthropic_api_key") or "").strip()


# ---------------------------------------------------------------- Claude (raw HTTPS, streamed; no SDK to install)
def claude_stream(cfg, body, timeout=CLAUDE_TIMEOUT_S, opener=None):
    """POST /v1/messages with stream: true -> {"text", "model", "stop_reason", "usage"}."""
    key = claude_key(cfg)
    if not key:
        raise houseplan.HouseError("Reading a floor plan with Claude needs your Anthropic key (Settings).", 503)
    req = urllib.request.Request(CLAUDE_API, data=json.dumps({**body, "stream": True}).encode(), method="POST",
                                 headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                          "content-type": "application/json", "User-Agent": "Designed-Living/1.0"})
    text, model, stop, use = [], body.get("model"), None, {}
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
            for raw in resp:
                line = raw.decode("utf-8", "replace").strip()
                if not line.startswith("data:"):
                    continue
                try:
                    ev = json.loads(line[5:].strip())
                except ValueError:
                    continue
                kind = ev.get("type")
                if kind == "message_start":
                    msg = ev.get("message") or {}
                    model = msg.get("model") or model
                    use.update(msg.get("usage") or {})
                elif kind == "content_block_delta" and (ev.get("delta") or {}).get("type") == "text_delta":
                    text.append(ev["delta"].get("text") or "")
                elif kind == "message_delta":
                    stop = (ev.get("delta") or {}).get("stop_reason") or stop
                    use.update({k: v for k, v in (ev.get("usage") or {}).items() if v is not None})
                elif kind == "error":
                    raise houseplan.HouseError(f"Claude stopped: {(ev.get('error') or {}).get('message', '')[:160]}",
                                               502)
    except urllib.error.HTTPError as exc:
        try:
            words = json.loads(exc.read()).get("error", {}).get("message", "")
        except (ValueError, OSError, AttributeError):
            words = ""
        raise houseplan.HouseError(f"Claude said no ({exc.code}{': ' + words[:160] if words else ''}).", 502)
    except (urllib.error.URLError, OSError) as exc:
        raise houseplan.HouseError("I couldn't reach Claude.", 502) from exc
    return {"text": "".join(text), "model": model, "stop_reason": stop, "usage": use}


def claude_plan(cfg, data, media):
    """Claude reads the floor plan picture or PDF straight into walls, rooms and doors (a checked plan). Thinking on
    and effort high: the read is a measuring job (Jarvis, 2026-11-23: without it rooms were skipped and stretched)."""
    model = str(cfg.get("claude_model") or DEFAULT_CLAUDE).strip()
    block = {"type": "document" if media == "application/pdf" else "image",
             "source": {"type": "base64", "media_type": media, "data": base64.b64encode(data).decode("ascii")}}
    got = claude_stream(cfg, {"model": model, "max_tokens": PLAN_MAX_TOKENS, "system": housedesign.PLAN_RULES,
                              "messages": [{"role": "user", "content": [block, {"type": "text",
                                                                                "text": "Read this floor plan."}]}],
                              "thinking": {"type": "adaptive"}, "output_config": {"effort": "high"}})
    usage.record("plan", got["model"], got["usage"])
    if got["stop_reason"] == "refusal":
        raise houseplan.HouseError("Claude wouldn't read that picture.")
    try:
        plan = housedesign.parse_plan(got["text"])
    except housedesign.DesignError as exc:
        raise houseplan.HouseError(exc.message)
    plan["read_by"] = got["model"] or model
    return plan


def image_type(data):
    kind = housedesign.kind_of(data)
    return {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}.get(kind)


def read_plan(hid, cfg=None, locate=None, root=None, claude=None):
    """The house's floor plan picture (or PDF) -> plan JSON. Both readers at once when both keys are there: Claude
    measures the rooms from the dimension lines, Gemini boxes the doors, windows, furniture and outside spaces, and
    housedesign.merge_reads puts Gemini's onto Claude's rooms. Either alone if only it can run, or if the other fails.
    `locate`, `claude` and `root` stand in for Gemini, Claude and the data folder in the self-test."""
    cfg = cfg if cfg is not None else load_config()
    root = root or data_root(cfg)
    path = houseplan.house_dir(root, hid)
    picture = houseplan.plan_picture(path)
    if not picture:
        raise houseplan.HouseError("There's no floor plan picture in this house. Upload one first.")
    data = picture.read_bytes()
    media = image_type(data) or ("application/pdf" if data[:5] == b"%PDF-" else None)
    if not media:
        raise houseplan.HouseError(f"{picture.name} isn't a picture or PDF I can read.")
    inner = housedesign.pdf_picture(data) if media == "application/pdf" else (data, media)
    key = gemini_key(cfg)
    can_claude = bool(claude) or bool(claude_key(cfg))
    size = (housedesign.picture_size(inner[0]) if inner and inner[1] in ("image/jpeg", "image/png", "image/webp")
            else None)
    can_gemini = bool(size) and bool(key or locate)
    if not can_gemini and not can_claude:
        raise houseplan.HouseError("Reading a plan needs a Gemini or an Anthropic key (Settings).", 503)
    if not can_gemini:
        plan = (claude or claude_plan)(cfg, data, media)
        print(f"Claude read the floor plan of {hid!r}: {len(plan['walls'])} walls, {len(plan['rooms'])} rooms",
              flush=True)
        return houseplan.save_plan(root, hid, plan)
    got = {}

    def claude_read():
        try:
            got["claude"] = (claude or claude_plan)(cfg, data, media)
        except houseplan.HouseError as exc:
            got["claude_error"] = exc
        except Exception as exc:                          # never lose the Gemini read to a Claude problem
            got["claude_error"] = houseplan.HouseError(f"Claude couldn't read it ({type(exc).__name__}).", 502)

    worker = threading.Thread(target=claude_read, daemon=True) if can_claude else None
    if worker:
        worker.start()
    gemini, gemini_error = None, None
    try:
        found = locate(inner[0], inner[1]) if locate else housedesign.locate_plan(
            inner[0], inner[1], key, str(cfg.get("house_plan_model") or "").strip() or None,
            record=lambda model, use: usage.record_gemini("plan", model, use))
        gemini = housedesign.plan_from_boxes(found, *size)
    except housedesign.DesignError as exc:
        gemini_error = houseplan.HouseError(exc.message, exc.status)
    if worker:
        worker.join()
    first = got.get("claude")
    if first and gemini:
        merged, how = housedesign.merge_reads(first, gemini)
        try:
            plan = housedesign.clean_plan(merged, note=True, move=False)
        except housedesign.DesignError:
            plan = first
        print(f"Claude and Gemini read the floor plan of {hid!r}: {len(plan['walls'])} walls, {len(plan['rooms'])} "
              f"spaces, {len(plan['openings'])} doors and windows, {len(plan['items'])} pieces of furniture; "
              f"{how['matched']} rooms in both", flush=True)
    elif first:
        plan = first
        plan["unsure"] = ((plan.get("unsure") or "") + f" Gemini couldn't help: {gemini_error.message}").strip()[:600]
    elif gemini:
        try:
            plan = housedesign.clean_plan(gemini, note=True, move=False)
        except housedesign.DesignError as exc:
            raise houseplan.HouseError(exc.message, exc.status)
        if got.get("claude_error"):
            plan["unsure"] = (f"Claude couldn't measure the rooms ({got['claude_error'].message}), so the sizes are "
                              f"Gemini's. " + (plan.get("unsure") or "")).strip()[:600]
    else:
        raise got.get("claude_error") or gemini_error
    return houseplan.save_plan(root, hid, plan)


# ---------------------------------------------------------------- design runs (a background thread per house)
WORK = {}                     # house id -> {running, done, total, room, errors, model}
WORK_LOCK = threading.Lock()


def work_of(hid):
    with WORK_LOCK:
        work = WORK.get(hid)
        return {**work, "errors": list(work["errors"])} if work else None


def design_start(hid, names=None, pro=False, cfg=None, make=None, read=None, root=None, restyle=None, cut=None):
    """Design the named rooms (all of them by default). From a plan or model: a new photo per room, then furniture.
    From photos: your photo of each room redesigned. make/read/restyle stand in for Gemini in the self-test."""
    cfg = cfg if cfg is not None else load_config()
    key = gemini_key(cfg)
    root = root or data_root(cfg)
    path = houseplan.house_dir(root, hid)
    state = houseplan.read_state(path)
    photos = photorooms.is_photos(state)
    rooms = (list(state.get("rooms") or []) if photos
             else houseplan.clean_rooms(state.get("rooms"), state.get("size")))
    if names:
        rooms = [r for r in rooms if r["name"] in names]
    if not rooms:
        raise houseplan.HouseError("Upload your room photos first." if photos else
                                   "Name the rooms first: draw a box over each one on the plan.")
    if not key and not (make or restyle):
        raise houseplan.HouseError("Designing rooms needs your Gemini key (Settings).", 503)
    with WORK_LOCK:
        if (WORK.get(hid) or {}).get("running"):
            raise houseplan.HouseError("This house is already being designed.", 409)
        WORK[hid] = {"running": True, "done": 0, "total": len(rooms), "room": rooms[0]["name"], "errors": [],
                     "model": "pro" if pro else "flash"}
    design = houseplan.design_of(state)
    feature = "photos" if photos else "design"
    wall = float(state.get("wall_height") or houseplan.DEFAULT_WALL)
    snaps = {} if photos else {r["name"]: (houseplan.snap_of(path, state, r["name"]) or (None,))[0] for r in rooms}

    def record(model, use):
        usage.record_gemini(feature, model, use)

    def run():
        try:
            flash, best = (None, None) if (make or restyle) else housedesign.image_models(key)
            model = (str(cfg.get("house_pro_model") or "").strip() or best) if pro else \
                (str(cfg.get("image_model") or "").strip() or flash)
            for room in rooms:
                with WORK_LOCK:
                    WORK[hid]["room"] = room["name"]
                try:
                    words, palette = houseplan.room_style(design, room["name"])
                    if photos:
                        before, mime = photorooms.source(root, hid, room["name"])
                        prompt = housedesign.restyle_prompt(room["name"], words, palette, design.get("wish") or "")
                        data, ext = (restyle or housedesign.restyle_photo)(before, mime, prompt, key, model, record)
                    elif snaps.get(room["name"]):          # the white model's snapshot of this room
                        prompt = housedesign.snapshot_prompt(room, words, palette, wall, design.get("wish") or "")
                        data, ext = (restyle or housedesign.restyle_photo)(snaps[room["name"]], "image/jpeg", prompt,
                                                                           key, model, record)
                    else:
                        prompt = housedesign.photo_prompt(room, words, palette, wall, design.get("wish") or "")
                        data, ext = (make or housedesign.make_photo)(prompt, key, model, record)
                    try:
                        seen = (read or housedesign.read_photo)(data, ext, key, cfg.get("house_read_model") or None,
                                                                record)
                    except housedesign.DesignError as exc:
                        print(f"couldn't read the {room['name']} photo back ({exc.message})", file=sys.stderr,
                              flush=True)
                        seen = None
                    if photos:
                        photorooms.store(root, hid, room["name"], data, ext, seen, "pro" if pro else "flash")
                    else:
                        houseplan.store_photo(root, hid, room["name"], data, ext, seen, "pro" if pro else "flash")
                        cut_room(root, hid, room["name"], data, ext, key, cfg, record, cut)
                except (housedesign.DesignError, houseplan.HouseError) as exc:
                    with WORK_LOCK:
                        WORK[hid]["errors"].append(f"{room['name']}: {exc.message}")
                with WORK_LOCK:
                    WORK[hid]["done"] += 1
            if not photos:
                houseplan.furnish_house(root, hid)
        except Exception as exc:             # the thread must always say it stopped
            print(f"the design run crashed: {exc!r}", file=sys.stderr, flush=True)
            with WORK_LOCK:
                WORK[hid]["errors"].append("Something went wrong; the app's window says what.")
        finally:
            with WORK_LOCK:
                WORK[hid]["running"] = False

    threading.Thread(target=run, name=f"design-{hid}", daemon=True).start()
    return {"started": True, "rooms": [r["name"] for r in rooms]}


def cut_room(root, hid, name, data, ext, key, cfg, record, cut=None):
    """The furniture cut out of a room's photo, for the walkthrough. Best effort: without it the pieces are drawn."""
    try:
        cuts = (cut or housedesign.cut_photo)(data, ext, key, cfg.get("house_cutout_model") or None, record)
    except housedesign.DesignError as exc:
        print(f"couldn't cut the furniture out of the {name} photo ({exc.message})", file=sys.stderr, flush=True)
        return False
    houseplan.store_cuts(root, hid, name, cuts)
    return True


def cuts_start(hid, cfg=None, root=None, cut=None):
    """Cut the furniture out of every designed photo that has no cut-outs yet (photos made before cut-outs were)."""
    cfg = cfg if cfg is not None else load_config()
    key = gemini_key(cfg)
    root = root or data_root(cfg)
    path = houseplan.house_dir(root, hid)
    state = houseplan.read_state(path)
    d = houseplan.design_of(state)
    rooms = [r["name"] for r in state.get("rooms") or []
             if (d["rooms"].get(r["name"]) or {}).get("photo") and houseplan.cuts_of(path, r["name"]) is None]
    if not rooms:
        raise houseplan.HouseError("Every designed room already has its cut-outs.")
    if not key and not cut:
        raise houseplan.HouseError("Cutting out the furniture needs your Gemini key (Settings).", 503)
    with WORK_LOCK:
        if (WORK.get(hid) or {}).get("running"):
            raise houseplan.HouseError("This house is already being designed.", 409)
        WORK[hid] = {"running": True, "done": 0, "total": len(rooms), "room": rooms[0], "errors": [], "model": "cut"}

    def record(model, use):
        usage.record_gemini("design", model, use)

    def run():
        try:
            for name in rooms:
                with WORK_LOCK:
                    WORK[hid]["room"] = name
                try:
                    data, ctype = houseplan.photo(root, hid, name)
                    ext = {"image/jpeg": "jpg", "image/webp": "webp"}.get(ctype, "png")
                    if not cut_room(root, hid, name, data, ext, key, cfg, record, cut):
                        with WORK_LOCK:
                            WORK[hid]["errors"].append(f"{name}: Gemini couldn't cut the furniture out.")
                except houseplan.HouseError as exc:
                    with WORK_LOCK:
                        WORK[hid]["errors"].append(f"{name}: {exc.message}")
                with WORK_LOCK:
                    WORK[hid]["done"] += 1
        except Exception as exc:             # the thread must always say it stopped
            print(f"the cut-out run crashed: {exc!r}", file=sys.stderr, flush=True)
            with WORK_LOCK:
                WORK[hid]["errors"].append("Something went wrong; the app's window says what.")
        finally:
            with WORK_LOCK:
                WORK[hid]["running"] = False

    threading.Thread(target=run, name=f"cuts-{hid}", daemon=True).start()
    return {"started": True, "rooms": rooms}


# ---------------------------------------------------------------- the API
def house_view(root, hid):
    path = houseplan.house_dir(root, hid)
    state = houseplan.read_state(path)
    if photorooms.is_photos(state):
        photorooms.sync(root, hid)
        out = houseplan.view(root, hid)
        out["photos"] = photorooms.view(root, hid)["rooms"]
    else:
        out = houseplan.view(root, hid)
    return {**out, "work": work_of(hid)}


def api_get(route, query):
    cfg = load_config()
    root = data_root(cfg)
    hid = (query.get("id") or [""])[0]
    if route == "/api/houses":
        return 200, {"houses": houseplan.houses(root)}
    if route == "/api/house":
        return 200, house_view(root, hid)
    if route == "/api/gallery":
        return 200, {"photos": houseplan.gallery(root)}
    if route == "/api/styles":
        return 200, {"styles": housedesign.styles_view(), "default": housedesign.DEFAULT_STYLE}
    if route == "/api/settings":
        return 200, settings_view(cfg)
    if route == "/api/costs":
        return 200, usage.summary()
    if route == "/api/preview":
        html = houseplan.preview(root, hid, (query.get("snap") or [""])[0] == "1")
        houseplan.no_secrets(html, secrets(cfg))
        return 200, html
    return 404, {"error": "Not found."}


def api_post(route, body):
    cfg = load_config()
    root = data_root(cfg)
    if route == "/api/settings":
        changes = {k: v for k, v in body.items() if k in {f for f, _, _ in FIELDS}}
        return 200, settings_view(save_config(changes))
    if route == "/api/settings/test":
        return 200, test_keys(cfg)
    action, hid = str(body.get("action") or ""), str(body.get("id") or "")
    if action == "create":
        start = body.get("start") if body.get("start") in STARTS else "plan"
        hid = houseplan.create(root, body.get("title"))
        path = houseplan.house_dir(root, hid)
        state = houseplan.read_state(path)
        state["start"] = start
        if start == "photos":
            state["kind"] = photorooms.KIND
        if not state.get("brand") and cfg.get("brand"):
            state["brand"] = str(cfg["brand"])[:60]
        houseplan.save_state(path, state)
        return 200, {"id": hid}
    if action == "process":
        return 200, houseplan.process(root, hid)
    if action == "save":
        changes = {k: body[k] for k in ("title", "subtitle", "brand", "rooms", "entrance", "wall_height", "unit",
                                        "design") if k in body}
        state = houseplan.read_state(houseplan.house_dir(root, hid))
        if photorooms.is_photos(state):
            if isinstance(body.get("names"), dict):
                photorooms.rename(root, hid, body["names"])
            changes.pop("rooms", None)
            changes.pop("entrance", None)
        houseplan.save(root, hid, changes)
        return 200, house_view(root, hid)
    if action == "export":
        return 200, houseplan.export(root, hid, secrets(cfg))
    if action == "remove":
        with WORK_LOCK:
            if (WORK.get(hid) or {}).get("running"):
                return 409, {"error": "This house is being designed. Wait for it to finish first."}
        return 200, houseplan.remove(root, hid)
    if action == "read_plan":
        read_plan(hid, cfg, root=root)
        return 200, house_view(root, hid)
    if action == "plan":
        if not isinstance(body.get("plan"), dict):
            return 400, {"error": "Send the plan."}
        try:
            houseplan.edit_plan(root, hid, body["plan"])
        except housedesign.DesignError as exc:
            return exc.status, {"error": exc.message}
        return 200, house_view(root, hid)
    if action == "design":
        rooms = body.get("rooms")
        names = [str(n) for n in rooms][:houseplan.MAX_ROOMS] if isinstance(rooms, list) else None
        return 200, design_start(hid, names, bool(body.get("pro")), cfg, root=root)
    if action == "cutouts":
        return 200, cuts_start(hid, cfg, root)
    if action == "snapshot":                   # one room's white-model snapshot, sent on by the editor page
        image = str(body.get("image") or "")
        head, _, b64 = image.partition(",")
        if head != "data:image/jpeg;base64" or not b64:
            return 400, {"error": "Send the snapshot as a JPEG."}
        try:
            data = base64.b64decode(b64, validate=True)
        except ValueError:
            return 400, {"error": "Send the snapshot as a JPEG."}
        return 200, houseplan.store_snap(root, hid, str(body.get("room") or ""), data, body.get("view"))
    if action == "furnish":
        houseplan.furnish_house(root, hid)
        return 200, house_view(root, hid)
    if action == "moodboard":
        state = houseplan.read_state(houseplan.house_dir(root, hid))
        return 200, (photorooms.save_moodboard(root, hid) if photorooms.is_photos(state)
                     else houseplan.save_moodboard(root, hid))
    if action == "open":
        path = houseplan.house_dir(root, hid)
        state = houseplan.read_state(path)
        what = body.get("what")
        target = (houseplan.moodboard_path(path, state) if what == "moodboard"
                  else path if what == "folder" else houseplan.export_path(path, state))
        if not target.exists():
            return 404, {"error": "Make the mood board PDF first." if what == "moodboard"
                         else "Export the website first."}
        launch(target)
        return 200, {"ok": True}
    return 400, {"error": "Unknown action."}


def launch(path):
    try:
        if sys.platform == "win32":
            os.startfile(str(path))                          # noqa: the file's own app, as a double-click would
        else:
            import subprocess
            subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as exc:
        raise houseplan.HouseError(f"I couldn't open {Path(path).name}: {exc.strerror or exc}.", 500)


def test_keys(cfg):
    """One small real call per key: the model list (free)."""
    out = {}
    key = gemini_key(cfg)
    if key:
        req = urllib.request.Request(housedesign.GEMINI_API + "/v1beta/models?pageSize=1",
                                     headers={"x-goog-api-key": key, "User-Agent": "Designed-Living/1.0"})
        out["gemini"] = _try(req)
    else:
        out["gemini"] = {"ok": False, "said": "Not set."}
    key = claude_key(cfg)
    if key:
        model = str(cfg.get("claude_model") or DEFAULT_CLAUDE).strip()
        req = urllib.request.Request(f"https://api.anthropic.com/v1/models/{urllib.parse.quote(model, safe='')}",
                                     headers={"x-api-key": key, "anthropic-version": "2023-06-01",
                                              "User-Agent": "Designed-Living/1.0"})
        out["anthropic"] = _try(req)
    else:
        out["anthropic"] = {"ok": False, "said": "Not set."}
    out["at"] = time.strftime("%H:%M")
    return out


def _try(req):
    try:
        with urllib.request.urlopen(req, timeout=TEST_TIMEOUT_S) as resp:
            resp.read(64 * 1024)
        return {"ok": True, "said": "Working."}
    except urllib.error.HTTPError as exc:
        return {"ok": False, "said": {400: "The key was refused (400).", 401: "The key was refused (401).",
                                      403: "The key isn't allowed to do this (403).",
                                      404: "The model name isn't known (404)."}.get(exc.code, f"Error {exc.code}.")}
    except (urllib.error.URLError, OSError):
        return {"ok": False, "said": "Couldn't reach the service."}


# ---------------------------------------------------------------- the server
class Handler(SimpleHTTPRequestHandler):
    server_version = "DesignedLiving/1.0"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, directory=str(WEB), **kwargs)

    def log_message(self, fmt, *args):
        if args and str(args[1] if len(args) > 1 else "").startswith(("4", "5")):
            sys.stderr.write("%s\n" % (fmt % args))

    def own_host(self):
        port = self.server.server_address[1]
        return (self.headers.get("Host") or "") in (f"127.0.0.1:{port}", f"localhost:{port}")

    def own_origin(self):
        port = self.server.server_address[1]
        return (self.headers.get("Origin") or "") in (f"http://127.0.0.1:{port}", f"http://localhost:{port}")

    def send_json(self, status, data):
        body = json.dumps(data).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            self.wfile.write(body)
        except OSError:
            pass

    def send_bytes(self, data, ctype, csp=None):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        if csp:
            self.send_header("Content-Security-Policy", csp)
        self.end_headers()
        try:
            self.wfile.write(data)
        except OSError:
            pass

    def end_headers(self):
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        super().end_headers()

    def do_HEAD(self):
        if not self.own_host():
            return self.send_json(403, {"error": "Not allowed."})
        return super().do_HEAD()

    def do_GET(self):
        if not self.own_host():                     # DNS rebinding: only our own Host may read anything
            return self.send_json(403, {"error": "Not allowed."})
        split = urllib.parse.urlsplit(self.path)
        route, query = split.path, urllib.parse.parse_qs(split.query)
        if route == "/api/photo":
            hid, room = (query.get("id") or [""])[0], (query.get("room") or [""])[0]
            try:
                root = data_root()
                which = (query.get("which") or [""])[0]
                if which == "before":
                    data, ctype = photorooms.source(root, hid, room)
                elif which == "snap":
                    data, ctype = houseplan.snap_photo(root, hid, room)
                else:
                    data, ctype = houseplan.photo(root, hid, room)
            except houseplan.HouseError as exc:
                return self.send_json(exc.status, {"error": exc.message})
            return self.send_bytes(data, ctype)
        if route.startswith("/api/"):
            try:
                status, out = api_get(route, query)
            except houseplan.HouseError as exc:
                return self.send_json(exc.status, {"error": exc.message})
            if isinstance(out, str):
                return self.send_bytes(out.encode("utf-8"), "text/html; charset=utf-8", PREVIEW_CSP)
            return self.send_json(status, out)
        if route == "/":
            self.path = "/index.html"
        return super().do_GET()

    def do_POST(self):
        if not self.own_host() or not self.own_origin():   # only our own pages may change anything
            return self.send_json(403, {"error": "Not allowed from this page."})
        split = urllib.parse.urlsplit(self.path)
        route = split.path
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            return self.send_json(400, {"error": "Bad length."})
        if route == "/api/upload":
            if length > houseplan.MAX_UPLOAD_BYTES:
                return self.send_json(413, {"error": f"That file is over {houseplan.MAX_UPLOAD_BYTES // 1024 // 1024} MB."})
            hid = urllib.parse.parse_qs(split.query).get("id", [""])[0]
            name = urllib.parse.unquote(self.headers.get("X-Filename") or "")
            data = self.rfile.read(length) if length > 0 else b""
            try:
                return self.send_json(200, {"file": houseplan.add_file(data_root(), hid, name, data)})
            except houseplan.HouseError as exc:
                return self.send_json(exc.status, {"error": exc.message})
        if route not in ("/api/house", "/api/settings", "/api/settings/test"):
            return self.send_json(404, {"error": "Not found."})
        if length > MAX_JSON_BYTES or "json" not in (self.headers.get("Content-Type") or ""):
            return self.send_json(400, {"error": "Send JSON."})
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
            if not isinstance(body, dict):
                raise ValueError
        except ValueError:
            return self.send_json(400, {"error": "Send JSON."})
        try:
            status, out = api_post(route, body)
        except houseplan.HouseError as exc:
            status, out = exc.status, {"error": exc.message}
        except housedesign.DesignError as exc:
            status, out = exc.status, {"error": exc.message}
        return self.send_json(status, out)


# ---------------------------------------------------------------- self-test
def selftest():
    import tempfile
    said, problems = [], []
    with tempfile.TemporaryDirectory() as scratch:
        said += list(houseplan.selftest(scratch))
    problems += [f"housedesign: {p}" for p in housedesign.selftest()]
    with tempfile.TemporaryDirectory() as scratch:
        said += photorooms.selftest(scratch)
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==")
    asked = []

    def make(prompt, key, model, record):
        asked.append(prompt)
        return png, "png"

    def read(data, ext, key, model, record):
        return housedesign.clean_read(json.dumps({"items": [{"kind": "sofa", "hex": "#777777"}]}))

    def wait(hid):
        for _ in range(100):
            work = work_of(hid)
            if work and not work["running"]:
                break
            time.sleep(0.1)
        with WORK_LOCK:
            return WORK.pop(hid, None) or {}

    with tempfile.TemporaryDirectory() as tmp:
        hid = houseplan.create(tmp, "Selftest house")
        plan = {"walls": [{"id": "s", "a": [0, 0], "b": [9, 0]}, {"id": "e", "a": [9, 0], "b": [9, 6]},
                          {"id": "n", "a": [9, 6], "b": [0, 6]}, {"id": "w", "a": [0, 6], "b": [0, 0]}],
                "openings": [{"wall": "s", "from": 4, "to": 4.9, "kind": "door", "name": "front door"}],
                "rooms": [{"name": "Living room", "x": [0, 5], "y": [0, 6]}, {"name": "Kitchen", "x": [5, 9], "y": [0, 6]}]}
        houseplan.save_plan(tmp, hid, housedesign.parse_plan(json.dumps(plan)))
        cut = lambda data, ext, key, model, record: housedesign.clean_cuts(json.dumps(
            [{"box_2d": [400, 100, 800, 600], "label": "sofa", "mask": "data:image/png;base64,"
              + base64.b64encode(png).decode()}, {"box_2d": [1, 2, 3, 4], "label": "sofa"},
             {"box_2d": [100, 100, 300, 300], "label": "spaceship"}]))
        design_start(hid, None, False, {}, make, read, tmp, cut=cut)
        work = wait(hid)
        design = houseplan.view(tmp, hid)["design"]["rooms"]
        if work.get("running") or work.get("errors") or len(asked) != 2:
            problems.append(f"the design run: {work}, {len(asked)} photo(s) asked for")
        elif not all(r["photo"] and r["items"] for r in design.values()):
            problems.append(f"a room has no photo or furniture: {design}")
        elif "#777777" not in json.dumps(houseplan.house_data(tmp, hid)["design"]):
            problems.append("the colours read from the photo didn't reach the walkthrough")
        elif [c["kind"] for c in houseplan.house_data(tmp, hid)["design"]["rooms"]["Living room"]["cuts"]] != ["sofa"]:
            problems.append("the furniture cut out of the photo didn't reach the walkthrough")
        elif sorted(g["room"] for g in houseplan.gallery(tmp)) != ["Kitchen", "Living room"]:
            problems.append(f"the gallery of designed rooms: {houseplan.gallery(tmp)}")
        else:
            said.append("a plan house designed with stand-ins: a photo, palette, furniture and cut-outs per room")
        # the white model: snapshots taken, each room designed from its own, stale once the house changes shape
        jpg = b"\xff\xd8\xff\xe0" + b"white model" * 20
        snap = houseplan.house_data(tmp, hid, snap=True)
        houseplan.store_snap(tmp, hid, "Living room", jpg, {"p": [1, 1, 1.6], "l": [4, 5, 0.7], "fov": 60})
        sent = []
        design_start(hid, ["Living room"], False, {}, make, read, tmp, cut=cut,
                     restyle=lambda pic, mime, prompt, key, model, record: (sent.append((pic, prompt)) or (png, "png")))
        work = wait(hid)
        path = houseplan.house_dir(tmp, hid)
        walk = houseplan.house_data(tmp, hid)["design"]["rooms"]
        if not snap.get("snap") or snap.get("cutouts") is not False or any(
                "photo" in r for r in snap["design"]["rooms"].values()):
            problems.append("the white model page still carries the photos")
        elif work.get("errors") or len(sent) != 1 or sent[0][0] != jpg or "white 3D model" not in sent[0][1]:
            problems.append(f"the room wasn't designed from its snapshot: {work}, {len(sent)}")
        elif walk["Living room"].get("view", {}).get("p") != [1.0, 1.0, 1.6] or "view" in walk["Kitchen"]:
            problems.append(f"the tour doesn't stop where the snapshot was taken: {walk['Living room'].get('view')}")
        else:
            houseplan.save(tmp, hid, {"wall_height": 3.0})
            if houseplan.snap_of(path, houseplan.read_state(path), "Living room") is not None:
                problems.append("a snapshot of the old house shape was still used")
            else:
                said.append("the white model: a room designed from its snapshot, retaken when the house changes")
        # a photos house redesigned with a stand-in for Nano Banana
        hid = houseplan.create(tmp, "Selftest photos")
        path = houseplan.house_dir(tmp, hid)
        state = houseplan.read_state(path)
        state["kind"] = photorooms.KIND
        houseplan.save_state(path, state)
        houseplan.add_file(tmp, hid, "lounge.png", png)
        photorooms.sync(tmp, hid)
        seen = []
        design_start(hid, None, False, {}, None, read, tmp,
                     restyle=lambda pic, mime, prompt, key, model, record: (seen.append(prompt) or (png, "png")))
        work = wait(hid)
        rooms = photorooms.view(tmp, hid)["rooms"]
        if work.get("errors") or not seen or "Keep the room itself" not in seen[0] or not rooms[0]["photo"]:
            problems.append(f"the photos run: {work}, {rooms}")
        else:
            said.append("a photos house redesigned with a stand-in: the room kept, the style changed")
        # a floor plan picture read with stand-ins for both readers
        hid = houseplan.create(tmp, "Selftest picture house")
        houseplan.add_file(tmp, hid, "plan.png", png)
        found = {"outline": [0, 0, 1000, 1000], "width_mm": 9000, "depth_mm": 6000,
                 "spaces": [{"name": "Living", "area_m2": 27, "box": [0, 0, 1000, 500], "outside": False,
                             "floor": "wood", "open_to": ["Kitchen"]},
                            {"name": "Kitchen", "area_m2": 27, "box": [0, 500, 1000, 1000], "outside": False,
                             "floor": "tile"}],
                 "openings": [{"kind": "door", "box": [995, 200, 1000, 300], "front": True},
                              {"kind": "window", "box": [0, 600, 5, 900]}],
                 "furniture": [{"kind": "sofa", "box": [100, 50, 160, 400]}]}
        try:
            got = read_plan(hid, {}, lambda data, mime: dict(found), tmp)
            if [r["name"] for r in got["house"]["rooms"]] != ["Living", "Kitchen"]:
                problems.append(f"the picture plan read: {got['house']['rooms']}")
            else:
                said.append("a floor plan picture read with a stand-in for Gemini")
        except houseplan.HouseError as exc:
            problems.append(f"the picture plan: {exc.message}")
    # the Claude stream parser, against a canned stream
    canned = [b'event: message_start\n', b'data: {"type":"message_start","message":{"model":"claude-x",'
              b'"usage":{"input_tokens":10}}}\n', b'data: {"type":"content_block_delta","delta":{"type":"text_delta",'
              b'"text":"Hel"}}\n', b'data: {"type":"content_block_delta","delta":{"type":"text_delta","text":"lo"}}\n',
              b'data: {"type":"message_delta","delta":{"stop_reason":"end_turn"},"usage":{"output_tokens":3}}\n']

    class Canned:
        def __init__(self, req, timeout):
            assert json.loads(req.data)["stream"] is True

        def __enter__(self):
            return iter(canned)

        def __exit__(self, *a):
            return False
    got = claude_stream({"anthropic_api_key": "sk-test"}, {"model": "m"}, opener=Canned)
    if got["text"] != "Hello" or got["usage"].get("output_tokens") != 3 or got["model"] != "claude-x":
        problems.append(f"the Claude stream: {got}")
    else:
        said.append("Claude's streamed answer read back whole")
    if secrets({"gemini_api_key": "AIzaSyTESTTESTTEST", "brand": "Faiek Designs"}) != ["AIzaSyTESTTESTTEST"]:
        problems.append("a key wasn't found in the config")
    for line in said:
        print("pass:", line)
    for line in problems:
        print("FAIL:", line)
    print(f"{len(said)} pass, {len(problems)} fail")
    return not problems


def main():
    if "--selftest" in sys.argv:
        sys.exit(0 if selftest() else 1)
    port = DEFAULT_PORT
    for arg in sys.argv[1:]:
        if arg.startswith("--port="):
            port = int(arg.split("=", 1)[1])
    server = ThreadingHTTPServer((HOST, port), Handler)
    url = f"http://{HOST}:{port}/"
    print(f"{NAME} is running at {url} (Ctrl+C to stop). Houses: {houseplan.root(data_root())}", flush=True)
    if "--no-browser" not in sys.argv:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopped.")


if __name__ == "__main__":
    main()
