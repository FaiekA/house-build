"""House Build: a house model (an OBJ from Sweet Home 3D or any 3D program, or a plan in the plan JSON)
becomes a scroll-animated walkthrough website, ONE offline HTML file. Standard library only, and no model call.

Each house is a folder in Houses/<name>/ (the houses folder, see app.py): house.json (the rooms you named, the front door, the
size), model/ (the files as they came, never changed), lines.json (the plan drawing, worked out from the model) and
the finished "<title> walkthrough.html". The 3D engine is houseplan/walkthrough-template.html, built once in the cloud
(houseplan/engine/, npm there, never here); the app only writes the house's data into its one JSON slot.

    python houseplan.py                  the offline checks
    python houseplan.py MODEL.obj|.zip   what the app reads from a model (size, wall height, plan lines)
"""
import base64
import io
import json
import math
import os
import re
import sys
import time
import zipfile
import zlib
from pathlib import Path

import housedesign
import printing

FOLDER = "Houses"                           # inside the app's data folder (config `houses_folder`)
TEMPLATE = Path(__file__).resolve().parent / "houseplan" / "walkthrough-template.html"
SLOT = "/*__HOUSE_JSON__*/"
MODEL_DIR = "model"
MAX_UPLOAD_BYTES = 150 * 1024 * 1024        # one file dropped on the page
MAX_MODEL_BYTES = 300 * 1024 * 1024         # everything in a house's model folder
MAX_EXPORT_BYTES = 200 * 1024 * 1024        # the finished page (a browser struggles past this)
MAX_ROOMS = 24
MAX_LINES = 40000                           # plan lines drawn on the sheet
MODEL_EXTS = {".obj", ".mtl", ".zip", ".json", ".pdf"}   # a .pdf (or a picture on its own) is a floor plan to read
DESIGN_DIR = "design"                        # the room photos the designer made (never in model/: they'd be textures)
PICTURE_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png", ".webp": "image/webp",
                 ".gif": "image/gif", ".bmp": "image/bmp"}
UNITS = {"m": 1.0, "cm": 0.01, "mm": 0.001, "in": 0.0254, "ft": 0.3048}
CUT_HEIGHT = 1.2                            # where the plan is "cut" through the model, like an architect's plan
WALL_GUESS = (2.1, 3.6)                     # wall heights looked for in a model
DEFAULT_WALL = 2.6
BAD = re.compile(r'[<>:"/\\|?*\x00-\x1f]')
MAX_NAME = 80


class HouseError(Exception):
    """Something the app can say."""

    def __init__(self, message, status=400):
        super().__init__(message)
        self.status = status

    @property
    def message(self):
        return str(self)


# ---------------------------------------------------------------- folders
def root(files_root):
    return Path(files_root) / FOLDER


def folder_name(title):
    """A safe folder name from the client's name ("The Naidoo house" -> "The Naidoo house")."""
    name = BAD.sub(" ", str(title or "")).strip(" .")
    name = re.sub(r"\s+", " ", name)[:60].strip(" .")
    if not name:
        raise HouseError("Give the house a name first.")
    return name


def house_dir(files_root, house_id):
    """The folder of one house; refuses anything that isn't a plain name inside Houses."""
    house_id = str(house_id or "")
    if (not house_id or len(house_id) > MAX_NAME or BAD.search(house_id) or ".." in house_id
            or house_id != house_id.strip(" .")):
        raise HouseError("That isn't one of your houses.", 404)
    base = root(files_root).resolve()
    path = (base / house_id).resolve()
    if path.parent != base:
        raise HouseError("That isn't one of your houses.", 404)
    return path


def write_atomic(path, data):
    path = Path(path)
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_bytes(data if isinstance(data, bytes) else data.encode("utf-8"))
    os.replace(tmp, path)


def read_state(path):
    try:
        return json.loads((Path(path) / "house.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise HouseError("That house's details can't be read.", 404)


def save_state(path, state):
    state["updated"] = time.strftime("%Y-%m-%d %H:%M")
    write_atomic(Path(path) / "house.json", json.dumps(state, indent=1, ensure_ascii=False))


def create(files_root, title):
    """A new house folder; a name already in use gets " (2)"."""
    name = folder_name(title)
    base = root(files_root)
    base.mkdir(parents=True, exist_ok=True)
    candidate, n = name, 2
    while (base / candidate).exists():
        candidate, n = f"{name} ({n})", n + 1
    newest = houses(files_root)
    brand = newest[0].get("brand", "") if newest else ""     # your name or business, as on your last house
    path = base / candidate
    (path / MODEL_DIR).mkdir(parents=True)
    save_state(path, {"id": candidate, "title": str(title).strip()[:80], "subtitle": "", "brand": brand, "rooms": [],
                      "entrance": None, "unit": "auto", "wall_height": None, "size": None,
                      "created": time.strftime("%Y-%m-%d %H:%M")})
    return candidate


def houses(files_root):
    """Every house, newest change first."""
    out = []
    base = root(files_root)
    if not base.is_dir():
        return out
    for path in base.iterdir():
        if not path.is_dir() or path.name.startswith(".") or not (path / "house.json").exists():
            continue
        try:
            state = read_state(path)
        except HouseError:
            continue
        page = export_path(path, state)
        out.append({"id": path.name, "title": state.get("title") or path.name, "updated": state.get("updated", ""),
                    "rooms": len(state.get("rooms") or []), "model": bool(model_files(path)), "brand": state.get("brand") or "",
                    "exported": page.name if page.exists() else "",
                    "kind": state.get("kind") or "", "start": state.get("start") or "",
                    "style": housedesign.STYLES.get((state.get("design") or {}).get("style") or "", {}).get("name", ""),
                    "palette": [p.get("hex") for p in ((state.get("design") or {}).get("palette")
                                                       or housedesign.palette_of(housedesign.DEFAULT_STYLE))][:4],
                    "_changed": (path / "house.json").stat().st_mtime})
    out.sort(key=lambda h: h.pop("_changed"), reverse=True)
    return out


def remove(files_root, house_id, recycle=None):
    """A house's whole folder goes to the Recycle Bin (Windows, a fixed drive), never deleted for good. Elsewhere, or
    when Windows has no bin for that drive, it is moved to Houses/.deleted/ (hidden from the list). `recycle`
    stands in for the Recycle Bin in the self-test."""
    path = house_dir(files_root, house_id)
    if not (path / "house.json").exists():
        raise HouseError("That house isn't there any more.", 404)
    if recycle is None and os.name == "nt":
        import recycle as bin_
        recycle = bin_.to_bin
    if recycle:
        try:
            recycle(path)
            return {"removed": house_id, "where": "the Recycle Bin"}
        except OSError:
            pass
    keep = root(files_root) / ".deleted"
    keep.mkdir(parents=True, exist_ok=True)
    target, n = keep / path.name, 2
    while target.exists():
        target, n = keep / f"{path.name} ({n})", n + 1
    path.rename(target)
    return {"removed": house_id, "where": "Houses\\.deleted"}


def model_files(path):
    folder = Path(path) / MODEL_DIR
    return sorted(p for p in folder.iterdir() if p.is_file()) if folder.is_dir() else []


def add_file(files_root, house_id, name, data):
    """Keep one uploaded file in the house's model folder, as it came (a file of the same name is replaced)."""
    path = house_dir(files_root, house_id)
    read_state(path)
    clean = BAD.sub("_", Path(str(name or "")).name).strip(" .")
    ext = Path(clean).suffix.lower()
    if not clean or (ext not in MODEL_EXTS and ext not in PICTURE_TYPES):
        raise HouseError("Send an OBJ (with its MTL and pictures), a zip of them, a plan .json, or a floor plan "
                         "picture or PDF.")
    if len(data) > MAX_UPLOAD_BYTES:
        raise HouseError(f"That file is over {MAX_UPLOAD_BYTES // 1024 // 1024} MB.", 413)
    folder = path / MODEL_DIR
    folder.mkdir(exist_ok=True)
    used = sum(p.stat().st_size for p in model_files(path) if p.name != clean)
    if used + len(data) > MAX_MODEL_BYTES:
        raise HouseError(f"This house's files would be over {MAX_MODEL_BYTES // 1024 // 1024} MB.", 413)
    write_atomic(folder / clean, data)
    return clean


# ---------------------------------------------------------------- reading the model
def gather(path):
    """The model's parts from its folder: obj text, mtl text, pictures {name: bytes}, or a plan JSON."""
    obj, mtl, pictures, plan = None, [], {}, None

    def take(name, data):
        nonlocal obj, plan
        ext = Path(name).suffix.lower()
        base = Path(name).name
        if ext == ".obj" and (obj is None or len(data) > len(obj[1])):
            obj = (base, data)
        elif ext == ".mtl":
            mtl.append(data.decode("utf-8", "replace"))
        elif ext in PICTURE_TYPES:
            pictures[base] = data
        elif ext == ".json" and plan is None:
            plan = data

    for file in model_files(path):
        data = file.read_bytes()
        if file.suffix.lower() == ".zip":
            try:
                with zipfile.ZipFile(io.BytesIO(data)) as z:
                    total = 0
                    for info in z.infolist():
                        if info.is_dir() or "__MACOSX" in info.filename:
                            continue
                        total += info.file_size
                        if total > MAX_MODEL_BYTES:
                            raise HouseError("The zip unpacks to more than this tool can take.", 413)
                        take(info.filename.replace("\\", "/"), z.read(info))
            except zipfile.BadZipFile:
                raise HouseError(f"{file.name} isn't a zip that can be opened.")
        else:
            take(file.name, data)
    return obj, "\n".join(mtl), pictures, plan


def obj_vertices(text):
    for line in text.splitlines():
        if line.startswith("v "):
            parts = line.split()
            try:
                yield float(parts[1]), float(parts[2]), float(parts[3])
            except (IndexError, ValueError):
                continue


def guess_unit(span):
    """A house is 4 to 60 metres across: the unit that makes this model so."""
    for unit in ("m", "cm", "mm"):
        if 3 <= span * UNITS[unit] <= 120:
            return unit
    return "m"


def wall_height(heights):
    """The most common height between WALL_GUESS: where wall tops and ceilings sit."""
    bins = {}
    for h in heights:
        if WALL_GUESS[0] <= h <= WALL_GUESS[1]:
            k = round(h * 20) / 20
            bins[k] = bins.get(k, 0) + 1
    return max(bins, key=lambda k: (bins[k], -k)) if bins else DEFAULT_WALL


def normalise(text, unit="auto"):
    """The OBJ moved into plan metres: x east, plan y north (-Z in the file), floor at 0; vertex = (x, h, -y).
    Returns (new text, facts)."""
    pts = list(obj_vertices(text))
    if len(pts) < 3:
        raise HouseError("That OBJ has no shape in it.")
    xs, ys, zs = [p[0] for p in pts], [p[1] for p in pts], [p[2] for p in pts]
    span = max(max(xs) - min(xs), max(zs) - min(zs))
    unit = unit if unit in UNITS else guess_unit(span)
    s = UNITS[unit]
    x0, y0, z1 = min(xs), min(ys), max(zs)
    out = []
    for line in text.splitlines():
        if line.startswith("v "):
            parts = line.split()
            try:
                x, y, z = float(parts[1]), float(parts[2]), float(parts[3])
            except (IndexError, ValueError):
                continue
            out.append(f"v {(x - x0) * s:.4f} {(y - y0) * s:.4f} {(z - z1) * s:.4f}")
        elif line.startswith("mtllib"):
            continue
        else:
            out.append(line)
    size = [round((max(xs) - x0) * s, 3), round((z1 - min(zs)) * s, 3)]
    heights = [(y - y0) * s for y in ys]
    return "\n".join(out), {"unit": unit, "size": size, "height": round((max(ys) - y0) * s, 3),
                            "wall_height": wall_height(heights), "vertices": len(pts)}


def faces(text):
    """Triangles of the (normalised) OBJ as plan points (x, y, h), faces fanned."""
    verts = []
    for line in text.splitlines():
        if line.startswith("v "):
            p = line.split()
            verts.append((float(p[1]), -float(p[3]), float(p[2])))
        elif line.startswith("f "):
            idx = []
            for tok in line.split()[1:]:
                try:
                    i = int(tok.split("/")[0])
                except ValueError:
                    continue
                idx.append(i - 1 if i > 0 else len(verts) + i)
            for k in range(1, len(idx) - 1):
                tri = (idx[0], idx[k], idx[k + 1])
                if all(0 <= i < len(verts) for i in tri):
                    yield tuple(verts[i] for i in tri)


def cut_lines(text, height=CUT_HEIGHT):
    """The model cut through at `height`, seen from above: the lines an architect's plan shows."""
    seen, lines = set(), []
    for tri in faces(text):
        pts = []
        for a, b in ((tri[0], tri[1]), (tri[1], tri[2]), (tri[2], tri[0])):
            if (a[2] - height) * (b[2] - height) < 0:
                t = (height - a[2]) / (b[2] - a[2])
                pts.append((a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t))
        if len(pts) != 2:
            continue
        (x0, y0), (x1, y1) = pts
        if math.hypot(x1 - x0, y1 - y0) < 0.01:
            continue
        key = tuple(sorted(((round(x0, 2), round(y0, 2)), (round(x1, 2), round(y1, 2)))))
        if key in seen:
            continue
        seen.add(key)
        lines.append([key[0][0], key[0][1], key[1][0], key[1][1]])
        if len(lines) >= MAX_LINES:
            break
    return lines


def plan_rooms(plan):
    """The plan's rooms for the tour: inside ones only (a patio or yard is drawn, never walked to)."""
    rooms = []
    for r in plan.get("rooms") or []:
        if r.get("outside") or r.get("part_of"):
            continue
        try:
            room = {"name": str(r["name"])[:40], "x": [float(r["x"][0]), float(r["x"][1])],
                    "y": [float(r["y"][0]), float(r["y"][1])], "note": str(r.get("note") or "")[:200]}
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if isinstance(r.get("area"), (int, float)) and r["area"] > 0:
            room["area"] = r["area"]
        rooms.append(room)
    return rooms[:MAX_ROOMS]


def plan_size(plan):
    xs = [p[0] for w in plan.get("walls") or [] for p in (w["a"], w["b"])]
    ys = [p[1] for w in plan.get("walls") or [] for p in (w["a"], w["b"])]
    if not xs:
        raise HouseError("That plan has no walls in it.")
    return [round(max(xs), 3), round(max(ys), 3)], min(xs), min(ys)


def plan_entrance(plan, size):
    walls = {w["id"]: w for w in plan.get("walls") or []}
    doors = [o for o in plan.get("openings") or [] if o.get("kind") in ("door", "sliding", "opening")
             and o.get("wall") in walls]
    doors.sort(key=lambda o: 0 if "front" in str(o.get("name", "")).lower() else 1)
    for o in doors:
        w = walls[o["wall"]]
        (ax, ay), (bx, by) = w["a"], w["b"]
        L = math.hypot(bx - ax, by - ay) or 1
        m = (o["from"] + o["to"]) / 2
        x, y = ax + (bx - ax) / L * m, ay + (by - ay) / L * m
        if ("front" in str(o.get("name", "")).lower() or w.get("t", 0) >= 0.18
                or min(x, y, size[0] - x, size[1] - y) < 0.3):          # the front door, else one on an outside wall
            return {"x": round(x, 3), "y": round(y, 3)}
    return {"x": round(size[0] / 2, 3), "y": 0}


def process(files_root, house_id):
    """Read the house's model folder: size, wall height, the plan drawing, and rooms/door from a plan JSON."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    obj, _mtl, pictures, plan = gather(path)
    if obj:
        text, facts = normalise(obj[1].decode("utf-8", "replace"), state.get("unit") or "auto")
        lines = cut_lines(text, min(CUT_HEIGHT, facts["wall_height"] * 0.45))
        write_atomic(path / "lines.json", json.dumps(lines))
        state.update({"kind": "obj", "size": facts["size"], "found_unit": facts["unit"],
                      "found_wall_height": facts["wall_height"], "pictures": len(pictures), "obj": obj[0]})
        if not state.get("wall_height"):
            state["wall_height"] = facts["wall_height"]
        if not state.get("entrance"):
            state["entrance"] = {"x": round(facts["size"][0] / 2, 3), "y": 0}
    elif plan:
        try:
            data = json.loads(plan.decode("utf-8"))
        except ValueError:
            raise HouseError("That .json isn't a house plan.")
        size, _, _ = plan_size(data)
        state.update({"kind": "plan", "size": size, "wall_height": data.get("wall_height") or DEFAULT_WALL})
        if not state.get("rooms"):
            state["rooms"] = plan_rooms(data)
        if not state.get("entrance"):
            state["entrance"] = plan_entrance(data, size)
        write_atomic(path / "lines.json", "[]")
    elif plan_picture(path):
        raise HouseError("That's a floor plan picture: press \"Read my floor plan\" and Claude will turn it into walls "
                         "and rooms.", 409)
    else:
        raise HouseError("There's no OBJ or plan in this house yet. Drop the model's files in first.")
    save_state(path, state)
    return view(files_root, house_id)


def plan_picture(path):
    """The floor plan picture or PDF to read, when the house has no OBJ and no plan JSON: the biggest one."""
    files = model_files(path)
    if any(p.suffix.lower() in (".obj", ".json", ".zip") and p.name != PICTURE_PLAN for p in files):
        return None
    pics = [p for p in files if p.suffix.lower() in PICTURE_TYPES or p.suffix.lower() == ".pdf"]
    return max(pics, key=lambda p: p.stat().st_size) if pics else None


PICTURE_PLAN = "plan from picture.json"


def save_plan(files_root, house_id, plan):
    """A plan read from the picture becomes the house's plan JSON (the picture is kept beside it). The furniture it
    draws is placed straight away."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    write_atomic(path / MODEL_DIR / PICTURE_PLAN, json.dumps(plan, indent=1, ensure_ascii=False))
    state["rooms"], state["entrance"], state["plan_unsure"] = [], None, plan.get("unsure") or ""
    state["plan_read_by"] = plan.get("read_by") or ""
    if isinstance(state.get("design"), dict):
        state["design"]["rooms"] = {}             # a new reading: the old rooms' furniture is gone with them
    save_state(path, state)
    process(files_root, house_id)
    if plan.get("items") and furnishing(read_state(path)):
        return furnish_house(files_root, house_id)
    return view(files_root, house_id)


def plan_file(path):
    """The house's plan JSON file in model/ (a plan read from a picture, or one uploaded), or None."""
    files = [p for p in model_files(path) if p.suffix.lower() == ".json"]
    return next((p for p in files if p.name == PICTURE_PLAN), files[0] if files else None)


def edit_plan(files_root, house_id, plan):
    """The page's fix tools: the edited walls, doors, windows and furniture replace the plan JSON. The rooms you
    named and the front door stay; the size follows the walls; the furniture follows."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    target = plan_file(path)
    if state.get("kind") != "plan" or not target:
        raise HouseError("Only a house built from a plan can have its walls edited here.")
    try:
        old = json.loads(target.read_bytes().decode("utf-8"))
    except (OSError, ValueError):
        old = {}
    merged = {**old, **{k: plan[k] for k in ("walls", "openings", "items", "rooms") if k in plan}}
    clean = housedesign.clean_plan(merged, move=False)
    clean["unsure"] = old.get("unsure") or ""
    if old.get("read_by"):
        clean["read_by"] = old["read_by"]
    write_atomic(target, json.dumps(clean, indent=1, ensure_ascii=False))
    size, _, _ = plan_size(clean)
    state["size"] = size
    save_state(path, state)
    if (state.get("design") or {}).get("rooms") or (clean.get("items") and furnishing(state)):
        return furnish_house(files_root, house_id)
    return view(files_root, house_id)


def view(files_root, house_id):
    """What the page needs: the state, the plan lines and the plan walls to draw the top view."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    try:
        lines = json.loads((path / "lines.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        lines = []
    plan = None
    if state.get("kind") == "plan":
        _, _, _, raw = gather(path)
        try:
            plan = json.loads(raw.decode("utf-8")) if raw else None
        except ValueError:
            plan = None
    page = export_path(path, state)
    picture = plan_picture(path) if state.get("kind") in (None, "plan") else None   # read (again)
    return {"house": state, "lines": lines, "plan": plan, "files": [p.name for p in model_files(path)],
            "plan_picture": picture.name if picture else "", "styles": {k: v["name"] for k, v in housedesign.STYLES.items()},
            "design": design_view(path, state), "exported": page.name if page.exists() else "",
            "moodboard": moodboard_path(path, state).name if moodboard_path(path, state).exists() else ""}


# ---------------------------------------------------------------- saving what the page edits
def clean_rooms(rooms, size):
    out = []
    for r in (rooms or [])[:MAX_ROOMS]:
        try:
            x0, x1 = sorted(float(v) for v in r["x"])
            y0, y1 = sorted(float(v) for v in r["y"])
        except (KeyError, TypeError, ValueError):
            continue
        name = re.sub(r"\s+", " ", str(r.get("name") or "")).strip()[:40]
        if not name or x1 - x0 < 0.5 or y1 - y0 < 0.5:
            continue
        if size:
            x0, x1 = max(0.0, x0), min(float(size[0]), x1)
            y0, y1 = max(0.0, y0), min(float(size[1]), y1)
        room = {"name": name, "x": [round(x0, 3), round(x1, 3)], "y": [round(y0, 3), round(y1, 3)],
                "note": str(r.get("note") or "").strip()[:200]}
        try:
            area = float(r.get("area") or 0)
        except (TypeError, ValueError):
            area = 0
        if 0 < area < 2000:
            room["area"] = round(area, 2)          # the size written on the plan, shown beside the box's
        out.append(room)
    return out


def save(files_root, house_id, changes):
    """The page's edits: title, subtitle, brand (top left of the website), rooms (in tour order), front door, wall height, unit."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    reprocess = False
    if "title" in changes:
        state["title"] = str(changes["title"] or "").strip()[:80] or state["title"]
    if "subtitle" in changes:
        state["subtitle"] = str(changes["subtitle"] or "").strip()[:300]
    if "brand" in changes:
        state["brand"] = re.sub(r"\s+", " ", str(changes["brand"] or "")).strip()[:60]
    if "rooms" in changes:
        state["rooms"] = clean_rooms(changes["rooms"], state.get("size"))
    if "entrance" in changes and isinstance(changes["entrance"], dict):
        try:
            state["entrance"] = {"x": round(float(changes["entrance"]["x"]), 3),
                                 "y": round(float(changes["entrance"]["y"]), 3)}
        except (KeyError, TypeError, ValueError):
            raise HouseError("The front door needs a place on the plan.")
    if "wall_height" in changes:
        try:
            h = float(changes["wall_height"])
        except (TypeError, ValueError):
            raise HouseError("The wall height is a number of metres, like 2.6.")
        if not 1.8 <= h <= 6:
            raise HouseError("Walls between 1.8 and 6 metres, please.")
        state["wall_height"] = round(h, 2)
    if isinstance(changes.get("design"), dict):
        set_design(state, changes["design"])
    if "unit" in changes and changes["unit"] != state.get("unit"):
        if changes["unit"] not in UNITS and changes["unit"] != "auto":
            raise HouseError("The unit is m, cm, mm, in or ft.")
        state["unit"], reprocess = changes["unit"], True
    save_state(path, state)
    if reprocess and state.get("kind") == "obj":
        process(files_root, house_id)
    if (("rooms" in changes or "entrance" in changes or "palette" in (changes.get("design") or {})
         or "style" in (changes.get("design") or {}) or "room_style" in (changes.get("design") or {})) and (state.get("design") or {}).get("rooms")):
        return furnish_house(files_root, house_id)          # the furniture follows the rooms (free)
    return view(files_root, house_id)


# ---------------------------------------------------------------- the designer (housedesign.py)
# state["design"]: {style, wish, palette, furnish, recolour, rooms: {room name: {photo, model, read, items, checks,
# floor, walls, made}}}. Photos live in design/<room>.png. Furniture and checks are worked out here, free.
def design_of(state):
    d = state.get("design")
    if not isinstance(d, dict):
        d = {}
    d.setdefault("style", housedesign.DEFAULT_STYLE)
    if d["style"] not in housedesign.STYLES:
        d["style"] = housedesign.DEFAULT_STYLE
    d.setdefault("wish", "")
    if not d.get("palette"):
        d["palette"] = housedesign.palette_of(d["style"])
    d.setdefault("furnish", None)              # None: yes for a plan, no for a model (it has its own furniture)
    d.setdefault("recolour", True)
    d.setdefault("rooms", {})
    state["design"] = d
    return d


def room_style(d, room_name):
    """(style words, palette) for one room: its own style if one is picked, else the house's."""
    own = ((d.get("rooms") or {}).get(room_name) or {}).get("style")
    if own in housedesign.STYLES and own != d["style"]:
        return housedesign.STYLES[own]["words"], housedesign.palette_of(own)
    return housedesign.STYLES[d["style"]]["words"], d["palette"]


def set_design(state, changes):
    d = design_of(state)
    if isinstance(changes.get("room_style"), dict):           # {room name: style key, or "" for the house's}
        names = {r.get("name") for r in state.get("rooms") or []}
        for name, key in changes["room_style"].items():
            if name not in names:
                continue
            rd = d["rooms"].setdefault(name, {})
            if key in housedesign.STYLES and key != d["style"]:
                rd["style"] = key
            else:
                rd.pop("style", None)
    if "style" in changes and changes["style"] in housedesign.STYLES and changes["style"] != d["style"]:
        d["style"] = changes["style"]
        d["palette"] = housedesign.palette_of(d["style"])
    if "wish" in changes:
        d["wish"] = re.sub(r"\s+", " ", str(changes["wish"] or "")).strip()[:300]
    if "palette" in changes:
        d["palette"] = housedesign.clean_palette(changes["palette"]) or housedesign.palette_of(d["style"])
    for k in ("furnish", "recolour"):
        if k in changes:
            d[k] = None if changes[k] is None else bool(changes[k])


def furnishing(state):
    d = design_of(state)
    return d["furnish"] if d["furnish"] is not None else state.get("kind") == "plan"


def photo_path(path, room_name, ext="png"):
    return Path(path) / DESIGN_DIR / f"{folder_name(room_name) or 'room'}.{ext}"


def store_photo(files_root, house_id, room_name, data, ext, read, model):
    """A room's designed photo and what was read from it; then the house is furnished again."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    d = design_of(state)
    for old in (path / DESIGN_DIR).glob(f"{folder_name(room_name) or 'room'}.*") if (path / DESIGN_DIR).is_dir() else []:
        old.unlink()
    target = photo_path(path, room_name, ext)
    target.parent.mkdir(exist_ok=True)
    write_atomic(target, data)
    d["rooms"][room_name] = {**d["rooms"].get(room_name, {}), "photo": target.name, "model": model, "read": read,
                             "made": time.strftime("%Y-%m-%d %H:%M")}
    save_state(path, state)
    return furnish_house(files_root, house_id)


def furnish_house(files_root, house_id):
    """Place every room's furniture (from its photo, else its kit) and run the layout checks. No model call."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    d = design_of(state)
    rooms = clean_rooms(state.get("rooms"), state.get("size"))
    doors, plan = None, None
    if state.get("kind") == "plan":
        _, _, _, raw = gather(path)
        try:
            plan = json.loads(raw.decode("utf-8")) if raw else None
            doors = housedesign.plan_doors(plan) if plan else None
        except ValueError:
            doors = None
    floors = {r.get("name"): r.get("floor") for r in (plan or {}).get("rooms") or []}
    for room in rooms:
        rd = d["rooms"].setdefault(room["name"], {})
        read = rd.get("read")
        kinds, colours = housedesign.kinds_from_read(room, read)
        own = room_style(d, room["name"])[1]
        palette = read["palette"] if read and read.get("palette") else own
        here = housedesign.room_doors(room, rooms, doors, state.get("entrance"))
        drawn = housedesign.plan_items(plan, room)
        if drawn:                                    # the plan draws its furniture: keep it where it's drawn
            items, results = housedesign.items_layout(room, drawn, here, palette, colours)
        else:
            items, results = housedesign.design_room(room, kinds, here, palette, colours)
        room = {**room, "floor": floors.get(room["name"])}
        rd.update({"items": items, "checks": results, "floor": housedesign.floor_of(room, read, own),
                   "walls": (read or {}).get("walls") or housedesign.pick(own, "walls", "#f1ede5")})
    save_state(path, state)
    return view(files_root, house_id)


def design_view(path, state):
    """The designer's state for the page (photos by name; the page loads them from /houseplan/photo)."""
    d = design_of(dict(state))
    names = [r["name"] for r in state.get("rooms") or []]
    rooms = {}
    for name in names:
        rd = d["rooms"].get(name) or {}
        rooms[name] = {"photo": bool(rd.get("photo") and (Path(path) / DESIGN_DIR / rd["photo"]).exists()),
                       "model": rd.get("model") or "", "made": rd.get("made") or "",
                       "palette": (rd.get("read") or {}).get("palette") or [],
                       "style": rd.get("style") or "", "style_palette": room_style(d, name)[1] if rd.get("style") else [],
                       "items": len(rd.get("items") or []), "checks": rd.get("checks") or []}
    return {"style": d["style"], "wish": d["wish"], "palette": d["palette"], "furnish": furnishing(state),
            "furnish_set": d["furnish"] is not None, "recolour": d["recolour"], "rooms": rooms,
            "cost": {"flash": housedesign.COST_FLASH_C, "pro": housedesign.COST_PRO_C}}


def photo(files_root, house_id, room_name):
    """(bytes, media type) of a room's designed photo."""
    path = house_dir(files_root, house_id)
    rd = design_of(read_state(path))["rooms"].get(room_name) or {}
    target = Path(path) / DESIGN_DIR / str(rd.get("photo") or "")
    if not rd.get("photo") or not target.is_file() or target.parent != Path(path) / DESIGN_DIR:
        raise HouseError("That room has no design yet.", 404)
    return target.read_bytes(), PICTURE_TYPES.get(target.suffix.lower(), "image/png")


def design_data(path, state, rooms):
    """What the walkthrough gets: the palette, and per room its photo (a mood board), colours and furniture."""
    d = state.get("design")
    if not isinstance(d, dict) or not d.get("rooms"):
        return None
    d = design_of(state)
    out = {"palette": d["palette"], "walls": housedesign.pick(d["palette"], "walls", "#f1ede5"),
           "furnish": furnishing(state), "recolour": bool(d["recolour"]), "rooms": {}}
    for room in rooms:
        rd = d["rooms"].get(room["name"])
        if not rd:
            continue
        entry = {"palette": (rd.get("read") or {}).get("palette") or room_style(d, room["name"])[1][:5],
                 "floor": rd.get("floor"),
                 "walls": rd.get("walls"), "items": rd.get("items") or []}
        target = Path(path) / DESIGN_DIR / str(rd.get("photo") or "")
        if rd.get("photo") and target.is_file():
            entry["photo"] = (f"data:{PICTURE_TYPES.get(target.suffix.lower(), 'image/png')};base64,"
                              + base64.b64encode(target.read_bytes()).decode("ascii"))
        out["rooms"][room["name"]] = entry
    return out


# ---------------------------------------------------------------- the finished page
def export_path(path, state):
    return Path(path) / f"{folder_name(state.get('title') or Path(path).name)} walkthrough.html"


def house_data(files_root, house_id):
    """The JSON the walkthrough engine reads."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    if not state.get("size"):
        raise HouseError("Drop the model in first.")
    rooms = clean_rooms(state.get("rooms"), state["size"])
    if not rooms:
        raise HouseError("Name at least one room first: draw a box over it on the plan.")
    data = {"version": 1, "title": state.get("title") or path.name, "subtitle": state.get("subtitle") or "",
            "brand": state.get("brand") or "", "size": state["size"], "wall_height": state.get("wall_height") or DEFAULT_WALL, "rooms": rooms,
            "entrance": state.get("entrance") or {"x": state["size"][0] / 2, "y": 0}}
    obj, mtl, pictures, plan = gather(path)
    if state.get("kind") == "obj" and obj:
        text, _ = normalise(obj[1].decode("utf-8", "replace"), state.get("unit") or "auto")
        data["model"] = {"obj": text, "mtl": mtl,
                         "files": {name: f"data:{PICTURE_TYPES[Path(name).suffix.lower()]};base64,"
                                         + base64.b64encode(raw).decode("ascii") for name, raw in pictures.items()}}
        try:
            data["lines"] = json.loads((path / "lines.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            data["lines"] = cut_lines(text)
    elif plan:
        data["plan"] = json.loads(plan.decode("utf-8"))
    else:
        raise HouseError("There's no model or plan in this house yet.")
    design = design_data(path, state, rooms)
    if design:
        data["design"] = design
    return data


def page_html(data, template=None):
    """The walkthrough page with the house in its slot. `</` is escaped so the data can never close the script."""
    template = template if template is not None else TEMPLATE.read_text(encoding="utf-8")
    if template.count(SLOT) != 1:
        raise HouseError("The walkthrough template is missing or damaged; pull Designed Living again.", 500)
    blob = json.dumps(data, ensure_ascii=False, separators=(",", ":")).replace("</", "<\\/").replace("<!--", "<\\!--")
    return template.replace(SLOT, blob)


def no_secrets(html, secrets):
    """Refuse a page that holds any of your keys (they must never reach a client)."""
    for secret in secrets:
        if secret and len(secret) >= 12 and secret in html:
            raise HouseError("That page would contain one of your keys, so it was not saved.", 500)


def export(files_root, house_id, secrets=()):
    path = house_dir(files_root, house_id)
    state = read_state(path)
    html = page_html(house_data(files_root, house_id))
    no_secrets(html, secrets)
    data = html.encode("utf-8")
    if len(data) > MAX_EXPORT_BYTES:
        raise HouseError(f"The page would be {len(data) // 1024 // 1024} MB, too big to open. Export a lighter model "
                         "(fewer furniture pieces or smaller pictures).", 413)
    target = export_path(path, state)
    write_atomic(target, data)
    return {"file": target.name, "path": str(target), "mb": round(len(data) / 1024 / 1024, 1)}


def preview(files_root, house_id):
    """The page as it would be exported, without saving it."""
    return page_html(house_data(files_root, house_id))


# ---------------------------------------------------------------- the mood board PDF (Faiek, 2026-11-24)
# A4 landscape: a cover (the house, its style and palette, the plan) and one page per designed room (its photo, named
# swatches, floor and walls, the furniture list and the checks). Written by hand like printing.note_pdf: the
# base-14 fonts and the photo as it was made (JPEG as is, PNG's own compressed rows), no compiled dependency.
MOOD_PAGE = (842.0, 595.0)


def _png_image(data):
    """PNG bytes -> (width, height, colours, filter dict extras, stream) for a PDF image, or None."""
    import struct
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        return None
    pos, idat, head = 8, bytearray(), None
    while pos + 8 <= len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        chunk = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            head = struct.unpack(">IIBBBBB", chunk)
        elif kind == b"IDAT":
            idat += chunk
        elif kind == b"IEND":
            break
        pos += 12 + n
    if not head or not idat:
        return None
    w, h, depth, ctype, _, _, interlace = head
    if depth != 8 or interlace or ctype not in (0, 2, 4, 6):
        return None
    if ctype in (0, 2):                         # grey or RGB: PDF reads PNG's own predicted rows as they are
        colours = 1 if ctype == 0 else 3
        return w, h, colours, (b" /DecodeParms << /Predictor 15 /Colors %d /BitsPerComponent 8 /Columns %d >>"
                               % (colours, w)), bytes(idat)
    bpp = 2 if ctype == 4 else 4                # with alpha: unfilter, drop the alpha onto white
    raw = zlib.decompress(bytes(idat))
    stride = w * bpp
    prev = bytearray(stride)
    out = bytearray()
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        if f == 1:
            for i in range(bpp, stride):
                line[i] = (line[i] + line[i - bpp]) & 255
        elif f == 2:
            line = bytearray((a + b) & 255 for a, b in zip(line, prev))
        elif f == 3:
            for i in range(stride):
                line[i] = (line[i] + ((line[i - bpp] if i >= bpp else 0) + prev[i]) // 2) & 255
        elif f == 4:
            for i in range(stride):
                a = line[i - bpp] if i >= bpp else 0
                b, c = prev[i], (prev[i - bpp] if i >= bpp else 0)
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        prev = line
        colours = bpp - 1
        for i in range(0, stride, bpp):
            al = line[i + bpp - 1]
            for k in range(colours):
                out.append((line[i + k] * al + 255 * (255 - al)) // 255)
    return w, h, bpp - 1, b"", zlib.compress(bytes(out), 6)


def _pdf_image(data):
    """A photo -> (width, height, PDF image object bytes) or None if it can't be placed (it is then left out)."""
    if data[:2] == b"\xff\xd8":
        size = housedesign.picture_size(data)
        if not size:
            return None
        grey = False
        pos = 2
        while pos + 9 < len(data):                       # the frame header says how many colours
            if data[pos] != 0xFF:
                break
            marker, n = data[pos + 1], int.from_bytes(data[pos + 2:pos + 4], "big")
            if marker in (0xC0, 0xC1, 0xC2):
                grey = data[pos + 9] == 1
                break
            pos += 2 + n
        space = b"/DeviceGray" if grey else b"/DeviceRGB"
        return size[0], size[1], (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s "
                                  b"/BitsPerComponent 8 /Filter /DCTDecode /Length %d >>\nstream\n"
                                  % (size[0], size[1], space, len(data)) + data + b"\nendstream")
    got = _png_image(data)
    if not got:
        return None
    w, h, colours, parms, stream = got
    space = b"/DeviceGray" if colours == 1 else b"/DeviceRGB"
    return w, h, (b"<< /Type /XObject /Subtype /Image /Width %d /Height %d /ColorSpace %s /BitsPerComponent 8 "
                  b"/Filter /FlateDecode%s /Length %d >>\nstream\n" % (w, h, space, parms, len(stream))
                  + stream + b"\nendstream")


class _Sheet:
    """One landscape page's drawing operators."""

    def __init__(self):
        self.ops, self.images = [], []

    def text(self, x, y, s, size=10, font="F1", grey=0.0, limit=None):
        data = printing.encode(str(s))
        if limit:
            while data and printing.width(data, font, size) > limit:
                data = data[:-4] + b"..." if len(data) > 4 else b""
        self.ops.append(b"%.2f g BT /%s %.1f Tf %.2f %.2f Td " % (grey, font.encode(), size, x, y)
                        + printing.pdf_string(data) + b" Tj ET 0 g")
        return printing.width(data, font, size)

    def wrap(self, x, y, s, size, limit, font="F1", grey=0.0, lines=3):
        words, line, n = str(s).split(), "", 0
        for word in words + [None]:
            test = (line + " " + word).strip() if word else line
            if word and printing.width(printing.encode(test), font, size) <= limit:
                line = test
                continue
            if line:
                self.text(x, y, line, size, font, grey, limit)
                y -= size * 1.35
                n += 1
                if n >= lines:
                    break
            line = word or ""
        return y

    def rect(self, x, y, w, h, hexcode=None, stroke=None):
        if hexcode:
            r, g, b = (int(hexcode[i:i + 2], 16) / 255 for i in (1, 3, 5))
            self.ops.append(b"%.3f %.3f %.3f rg %.2f %.2f %.2f %.2f re f 0 g" % (r, g, b, x, y, w, h))
        if stroke is not None:
            self.ops.append(b"%.2f G 0.6 w %.2f %.2f %.2f %.2f re S 0 G" % (stroke, x, y, w, h))

    def line(self, x0, y0, x1, y1, grey=0.2, width=0.8):
        self.ops.append(b"%.2f G %.2f w %.2f %.2f m %.2f %.2f l S 0 G" % (grey, width, x0, y0, x1, y1))

    def image(self, obj, x, y, w, h):
        name = b"Im%d" % (len(self.images) + 1)
        self.images.append((name, obj))
        self.ops.append(b"q %.2f 0 0 %.2f %.2f %.2f cm /%s Do Q" % (w, h, x, y, name))


def _swatches(sheet, x, y, palette, width, size=9):
    """Named swatches in a column from (x, y) down; returns the y below them."""
    for p in palette:
        sheet.rect(x, y - 16, 30, 18, p["hex"], 0.75)
        sheet.text(x + 38, y - 5, p.get("name") or p["hex"], size, "F2", 0.1, width - 40)
        sheet.text(x + 38, y - 15, f"{p['hex']}  {p.get('use') or ''}".strip(), size - 1.5, "F1", 0.45, width - 40)
        y -= 26
    return y


def _plan_drawing(sheet, data, x, y, w, h):
    """The plan seen from above, fitted in the box: walls (or the model's cut lines) and each room's name."""
    W, D = data["size"]
    k = min(w / max(W, 0.1), h / max(D, 0.1))
    ox, oy = x + (w - W * k) / 2, y + (h - D * k) / 2
    plan = data.get("plan") or {}
    segs = [(wl["a"][0], wl["a"][1], wl["b"][0], wl["b"][1]) for wl in plan.get("walls") or []
            if isinstance(wl, dict) and wl.get("a") and wl.get("b")]
    if not segs:
        segs = [tuple(l) for l in (data.get("lines") or [])[:6000]]
    for r in data["rooms"]:
        sheet.rect(ox + r["x"][0] * k, oy + r["y"][0] * k, (r["x"][1] - r["x"][0]) * k, (r["y"][1] - r["y"][0]) * k,
                   None, 0.82)
    for x0, y0, x1, y1 in segs:
        sheet.line(ox + x0 * k, oy + y0 * k, ox + x1 * k, oy + y1 * k, 0.15, 1.6 if plan else 0.5)
    for r in data["rooms"]:
        cx, cy = ox + (r["x"][0] + r["x"][1]) / 2 * k, oy + (r["y"][0] + r["y"][1]) / 2 * k
        room_w = (r["x"][1] - r["x"][0]) * k
        name = printing.encode(r["name"])
        size = 7.5 if printing.width(name, "F1", 7.5) <= room_w - 4 else 6
        sheet.text(cx - min(printing.width(name, "F1", size), room_w - 4) / 2, cy - 2, r["name"], size, "F1", 0.3,
                   max(room_w - 4, 20))


def _furniture_list(items):
    counts = {}
    for i in items or []:
        if i.get("kind") in ("pendant",):
            continue
        label = str(i.get("label") or i.get("kind") or "").replace("_", " ").strip()
        if label:
            label = label[:1].upper() + label[1:]
            counts[label] = counts.get(label, 0) + 1
    return [f"{k} x{n}" if n > 1 else k for k, n in counts.items()]


def moodboard_pdf(files_root, house_id):
    """The house's mood board as PDF bytes: a cover and one page per room."""
    path = house_dir(files_root, house_id)
    state = read_state(path)
    data = house_data(files_root, house_id)
    d = design_of(state)
    if not any((d["rooms"].get(r["name"]) or {}).get("photo") for r in data["rooms"]):
        raise HouseError("Design at least one room first (step 3), then print the mood board.")
    PW, PH = MOOD_PAGE
    M = 40
    pages = []
    cover = _Sheet()
    if data.get("brand"):
        cover.text(M, PH - M - 4, data["brand"].upper(), 9, "F2", 0.45, 360)
    cover.text(M, PH - M - 40, data["title"], 26, "F2", 0.08, 380)
    y = PH - M - 62
    if data.get("subtitle"):
        y = cover.wrap(M, y, data["subtitle"], 10.5, 360, "F3", 0.35, 3) - 4
    cover.text(M, y - 6, "Mood board", 13, "F2", 0.2)
    style = housedesign.STYLES[d["style"]]
    cover.text(M, y - 24, f"House style: {style['name']}", 10, "F1", 0.3, 360)
    if d.get("wish"):
        y = cover.wrap(M, y - 38, f"The owner asked for: {d['wish']}", 9, 360, "F3", 0.4, 2) + 9
    else:
        y -= 24
    cover.text(M, y - 26, "House palette", 9, "F2", 0.45)
    y = _swatches(cover, M, y - 34, d["palette"], 360)
    others = sorted({(d["rooms"].get(r["name"]) or {}).get("style") for r in data["rooms"]} - {None, d["style"]})
    for key in others:
        if key in housedesign.STYLES and y > M + 40:
            names = [r["name"] for r in data["rooms"] if (d["rooms"].get(r["name"]) or {}).get("style") == key]
            y = cover.wrap(M, y - 8, f"{housedesign.STYLES[key]['name']}: {', '.join(names)}", 8.5, 360, "F1", 0.4, 2)
    _plan_drawing(cover, data, 430, M + 20, PW - 430 - M, PH - 2 * M - 30)
    cover.text(430, M + 4, f"{data['size'][0]:.1f} x {data['size'][1]:.1f} m, {len(data['rooms'])} rooms", 8, "F1",
               0.45)
    pages.append(cover)
    for r in data["rooms"]:
        rd = d["rooms"].get(r["name"]) or {}
        target = Path(path) / DESIGN_DIR / str(rd.get("photo") or "")
        if not rd.get("photo") or not target.is_file():
            continue
        sheet = _Sheet()
        sheet.text(M, PH - M - 20, r["name"], 20, "F2", 0.08, 520)
        words, palette = room_style(d, r["name"])
        own = rd.get("style") if rd.get("style") in housedesign.STYLES else d["style"]
        size = f"{r['x'][1] - r['x'][0]:.1f} x {r['y'][1] - r['y'][0]:.1f} m"
        sheet.text(M, PH - M - 38, f"{housedesign.STYLES[own]['name']}  |  {size}", 9.5, "F1", 0.4, 520)
        box_w, box_h = 520, PH - 2 * M - 70
        img = _pdf_image(target.read_bytes())
        if img:
            iw, ih, obj = img
            k = min(box_w / iw, box_h / ih)
            sheet.image(obj, M, M + 10 + (box_h - ih * k), iw * k, ih * k)
        else:
            sheet.rect(M, M + 10, box_w, box_h, None, 0.7)
            sheet.text(M + 12, M + box_h / 2, "This photo's format can't go into a PDF; see the design folder.", 9,
                       "F3", 0.4)
        x, cw = M + box_w + 24, PW - M - box_w - 24 - M
        y = PH - M - 62
        read = rd.get("read") or {}
        sheet.text(x, y, "Palette", 9, "F2", 0.45)
        y = _swatches(sheet, x, y - 8, (read.get("palette") or palette)[:6], cw, 8.5)
        floor = rd.get("floor") or {}
        if floor.get("hex"):
            sheet.rect(x, y - 13, 14, 12, floor["hex"], 0.75)
            sheet.text(x + 20, y - 10, f"Floor: {floor.get('material') or ''} {floor['hex']}".strip(), 8.5, "F1", 0.25,
                       cw - 20)
            y -= 18
        if rd.get("walls"):
            sheet.rect(x, y - 13, 14, 12, rd["walls"], 0.75)
            sheet.text(x + 20, y - 10, f"Walls: {rd['walls']}", 8.5, "F1", 0.25, cw - 20)
            y -= 18
        pieces = _furniture_list(rd.get("items"))
        if pieces:
            y -= 8
            sheet.text(x, y, "Furniture", 9, "F2", 0.45)
            y -= 13
            for p in pieces:
                if y < M + 60:
                    sheet.text(x, y, "...", 8.5, "F1", 0.35)
                    y -= 11
                    break
                sheet.text(x, y, f"- {p}", 8.5, "F1", 0.2, cw)
                y -= 11
        bad = [c["text"].replace(r["name"] + ": ", "") for c in rd.get("checks") or [] if not c.get("ok")]
        if bad and y > M + 30:
            y -= 6
            sheet.text(x, y, "To look at", 9, "F2", 0.45)
            y -= 12
            for t in bad[:3]:
                y = sheet.wrap(x, y, t, 8, cw, "F1", 0.35, 2) - 2
                if y < M + 20:
                    break
        pages.append(sheet)
    total = len(pages)
    for n, sheet in enumerate(pages, 1):
        foot = f"{data['title']}  |  mood board  |  page {n} of {total}"
        sheet.text(M, 20, foot, 7.5, "F1", 0.5, PW - 2 * M)
    return _mood_file(pages, f"{data['title']} mood board")


def _mood_file(pages, title):
    objects = {1: b"<< /Type /Catalog /Pages 2 0 R >>"}
    fonts = {name: 3 + i for i, name in enumerate(printing.FONTS)}
    for name, num in fonts.items():
        objects[num] = (b"<< /Type /Font /Subtype /Type1 /BaseFont /" + printing.FONTS[name][0].encode()
                        + b" /Encoding /WinAnsiEncoding >>")
    font_dict = b"<< " + b" ".join(b"/%s %d 0 R" % (n.encode(), num) for n, num in fonts.items()) + b" >>"
    n, kids = 3 + len(fonts), []
    for sheet in pages:
        page_num, content_num = n, n + 1
        n += 2
        xobj = []
        for name, obj in sheet.images:
            objects[n] = obj
            xobj.append(b"/%s %d 0 R" % (name, n))
            n += 1
        res = b"<< /Font " + font_dict + (b" /XObject << " + b" ".join(xobj) + b" >>" if xobj else b"") + b" >>"
        objects[page_num] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.0f %.0f] /Resources %s /Contents %d 0 R >>"
                             % (MOOD_PAGE[0], MOOD_PAGE[1], res, content_num))
        content = zlib.compress(b"\n".join(sheet.ops), 9)
        objects[content_num] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(content) + content + b"\nendstream"
        kids.append(b"%d 0 R" % page_num)
    objects[2] = b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d >>" % len(pages)
    objects[n] = b"<< /Title " + printing._text_string(title) + b" /Producer (Designed Living) >>"
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objects[num] + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (n + 1)
    for num in range(1, n + 1):
        out += b"%010d 00000 n \n" % offsets[num]
    out += b"trailer\n<< /Size %d /Root 1 0 R /Info %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (n + 1, n, xref)
    return bytes(out)


def moodboard_path(path, state):
    return Path(path) / f"{folder_name(state.get('title') or Path(path).name)} mood board.pdf"


def save_moodboard(files_root, house_id):
    """Writes '<house> mood board.pdf' next to the website (replaced each time: it is made from the house)."""
    path = house_dir(files_root, house_id)
    data = moodboard_pdf(files_root, house_id)
    target = moodboard_path(path, read_state(path))
    write_atomic(target, data)
    return {"file": target.name, "path": str(target), "kb": len(data) // 1024}



# ---------------------------------------------------------------- checks
def _png(w, h, ctype):
    """A tiny PNG for the checks (Paeth-filtered rows, so the unfilter is tried too)."""
    import struct
    bpp = {2: 3, 6: 4}[ctype]
    rows = b"".join(b"\x04" + bytes((x * 60 + y * 30 + c * 10) % 256 for x in range(w) for c in range(bpp))
                    for y in range(h))

    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, ctype, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b""))


TEST_OBJ = """# a 10 x 8 m box house in centimetres, one inside wall, Y up
v 0 0 0
v 1000 0 0
v 1000 0 -800
v 0 0 -800
v 0 260 0
v 1000 260 0
v 1000 260 -800
v 0 260 -800
v 600 0 0
v 600 0 -800
v 600 260 -800
v 600 260 0
f 1 2 6 5
f 2 3 7 6
f 3 4 8 7
f 4 1 5 8
f 9 10 11 12
f 1 4 3 2
"""


def selftest(scratch=None):
    """Offline checks on a scratch folder: create, upload, read, name rooms, export, refusals."""
    import tempfile
    tmp = Path(scratch or tempfile.mkdtemp(prefix="houseplan-"))
    said = []
    hid = create(tmp, "Test house")
    assert create(tmp, "Test house") == "Test house (2)"
    for name in ("Müller house", "Ngcobo – home", "(Smith) house", "O’Brien’s"):
        made = create(tmp, name)
        assert house_dir(tmp, made).is_dir() and read_state(house_dir(tmp, made))["title"] == name, name
    for bad in ("../x", "..", "a/b", "", "C:\\x", ".hidden", "x "):
        try:
            house_dir(tmp, bad)
            raise AssertionError(f"{bad!r} was let in")
        except HouseError:
            pass
    zbuf = io.BytesIO()
    with zipfile.ZipFile(zbuf, "w") as z:
        z.writestr("house/test.obj", TEST_OBJ)
        z.writestr("house/test.mtl", "newmtl wall\nKd 0.9 0.9 0.9\nmap_Kd wall.png\n")
        z.writestr("house/wall.png", base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg=="))
    add_file(tmp, hid, "house.zip", zbuf.getvalue())
    try:
        add_file(tmp, hid, "run.exe", b"MZ")
        raise AssertionError("a program was accepted")
    except HouseError:
        pass
    got = process(tmp, hid)["house"]
    assert got["found_unit"] == "cm" and got["size"] == [10.0, 8.0], got
    assert abs(got["wall_height"] - 2.6) < 0.06, got["wall_height"]
    lines = view(tmp, hid)["lines"]
    assert len(lines) >= 5, lines                         # four outside walls and the inside one, cut at 1.2 m
    said.append(f"read a 10 x 8 m model in cm: {len(lines)} plan lines, walls {got['wall_height']} m")
    try:
        export(tmp, hid)
        raise AssertionError("exported with no rooms")
    except HouseError:
        pass
    save(tmp, hid, {"rooms": [{"name": "Living room", "x": [0, 6], "y": [0, 8]},
                              {"name": "Bedroom", "x": [6, 10], "y": [0, 8]}, {"name": "", "x": [0, 1], "y": [0, 1]}],
                    "entrance": {"x": 3, "y": 0}, "brand": "  Faiek   Designs ", "title": "Test </script><script>alert(1)</script> house"})
    template = f"<html><script id=\"house-data\" type=\"application/json\">{SLOT}</script></html>"
    html = page_html(house_data(tmp, hid), template)
    assert "</script><script>alert" not in html and html.count("</script>") == 1
    data = house_data(tmp, hid)
    assert data["brand"] == "Faiek Designs", data["brand"]
    assert len(data["rooms"]) == 2 and data["model"]["files"]["wall.png"].startswith("data:image/png;base64,")
    try:
        no_secrets(html.replace("Living", "sk-ant-0123456789abcdef"), ["sk-ant-0123456789abcdef"])
        raise AssertionError("a key was let through")
    except HouseError:
        pass
    said.append("rooms saved, the page's data can't break out of its script, a key in the page is refused")
    gone = create(tmp, "Delete me")
    binned = []
    assert remove(tmp, gone, recycle=lambda p: binned.append(p))["where"] == "the Recycle Bin" and binned
    gone = create(tmp, "Delete me too")
    def no_bin(p):
        raise OSError("no bin")
    assert remove(tmp, gone, recycle=no_bin)["where"].endswith(".deleted")
    assert not house_dir(tmp, gone).exists() and gone not in [h["id"] for h in houses(tmp)]
    said.append("a house goes to the Recycle Bin, else a hidden .deleted folder, and leaves the list")
    plan_id = create(tmp, "Plan house")
    assert read_state(house_dir(tmp, plan_id))["brand"] == "Faiek Designs"     # a new house takes your last name
    said.append("names with accents, dashes and brackets work; your name on the website carries to the next house")
    plan = {"wall_height": 2.7, "walls": [{"id": "s", "a": [0, 0], "b": [8, 0], "t": 0.2}, {"id": "n", "a": [0, 6], "b": [8, 6], "t": 0.2},
                                           {"id": "w", "a": [0, 0], "b": [0, 6], "t": 0.2}, {"id": "e", "a": [8, 0], "b": [8, 6], "t": 0.2}],
            "openings": [{"wall": "s", "from": 3, "to": 4, "kind": "door", "name": "Front door"}],
            "rooms": [{"name": "Open plan", "x": [0, 8], "y": [0, 6]}]}
    add_file(tmp, plan_id, "plan.json", json.dumps(plan).encode())
    got = process(tmp, plan_id)["house"]
    assert got["kind"] == "plan" and got["entrance"] == {"x": 3.5, "y": 0.0} and got["rooms"][0]["name"] == "Open plan", got
    said.append("a plan .json gives its rooms and front door")
    pal = housedesign.palette_of("scandi")
    save(tmp, plan_id, {"design": {"style": "scandi", "wish": "  a reading   corner "}})
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==")
    read = housedesign.clean_read(json.dumps({"palette": pal[:5], "floor": {"material": "wood", "hex": "#c8a57a"},
                                              "walls": "#f3f1ec", "items": [{"kind": "sofa", "hex": "#888888"},
                                                                            {"kind": "dining_table", "hex": "#aa8866"}]}))
    got = store_photo(tmp, plan_id, "Open plan", png, "png", read, "flash")
    room = got["design"]["rooms"]["Open plan"]
    assert room["photo"] and room["items"] >= 2 and room["checks"] and got["design"]["wish"] == "a reading corner", got["design"]
    data = house_data(tmp, plan_id)["design"]
    assert data["furnish"] and data["rooms"]["Open plan"]["photo"].startswith("data:image/png;base64,")
    assert any(i["kind"] == "sofa" and i.get("c") == "#888888" for i in data["rooms"]["Open plan"]["items"])
    assert photo(tmp, plan_id, "Open plan")[1] == "image/png"
    save(tmp, plan_id, {"rooms": [{"name": "Open plan", "x": [0, 8], "y": [0, 6]}, {"name": "Study", "x": [5, 8], "y": [3, 6]}]})
    assert "Study" in view(tmp, plan_id)["design"]["rooms"]
    said.append("a room's design photo, its palette and furniture (placed and checked) reach the walkthrough")
    got = save(tmp, plan_id, {"design": {"room_style": {"Study": "spa", "Nowhere": "spa"}}})
    study = got["design"]["rooms"]["Study"]
    assert study["style"] == "spa" and study["style_palette"][0]["name"] == "Stone white", study
    assert "Nowhere" not in got["design"]["rooms"]
    st = read_state(house_dir(tmp, plan_id))
    assert room_style(design_of(st), "Study")[0] == housedesign.STYLES["spa"]["words"]
    assert room_style(design_of(st), "Open plan")[1] == design_of(st)["palette"]
    got = save(tmp, plan_id, {"design": {"room_style": {"Study": ""}}})
    assert not got["design"]["rooms"]["Study"]["style"]
    said.append("one room can take its own style and palette (a spa bathroom), and go back to the house's")
    got = save_moodboard(tmp, plan_id)
    pdf = Path(got["path"]).read_bytes()
    assert pdf.startswith(b"%PDF-1.7") and pdf.count(b"/Type /Page ") == 2 and b"/Subtype /Image" in pdf, got
    assert view(tmp, plan_id)["moodboard"] == got["file"]
    for data in (_png(2, 2, 2), _png(2, 2, 6)):
        w, h, colours, _, stream = _png_image(data)
        assert (w, h, colours) == (2, 2, 3) and stream
    said.append("the mood board PDF: a cover with the plan and palette, then a page per designed room with its photo")
    pic_id = create(tmp, "Picture house")
    add_file(tmp, pic_id, "plan.png", png)
    try:
        process(tmp, pic_id)
        raise AssertionError("a plan picture was read without Claude")
    except HouseError as exc:
        assert exc.status == 409
    assert view(tmp, pic_id)["plan_picture"] == "plan.png"
    walls = [{"id": "s", "a": [0, 0], "b": [9, 0]}, {"id": "e", "a": [9, 0], "b": [9, 7]},
             {"id": "n", "a": [9, 7], "b": [0, 7]}, {"id": "w", "a": [0, 7], "b": [0, 0]}]
    got = save_plan(tmp, pic_id, housedesign.parse_plan(json.dumps(
        {"walls": walls, "openings": [{"wall": "s", "from": 4, "to": 4.9, "kind": "door", "name": "front door"}],
         "rooms": [{"name": "Lounge", "x": [0, 9], "y": [0, 7]}]})))["house"]
    assert got["kind"] == "plan" and got["rooms"][0]["name"] == "Lounge" and got["entrance"]["y"] == 0, got
    said.append("a floor plan picture waits for Claude to read it, then becomes walls, rooms and a front door")
    if TEMPLATE.exists():
        out = export(tmp, hid)
        assert (house_dir(tmp, hid) / out["file"]).exists()
        said.append(f"exported the real template: {out['file']}, {out['mb']} MB")
    return said


if __name__ == "__main__":
    if len(sys.argv) > 1:
        raw = Path(sys.argv[1]).read_bytes()
        if sys.argv[1].lower().endswith(".zip"):
            with zipfile.ZipFile(io.BytesIO(raw)) as z:
                raw = max((z.read(n) for n in z.namelist() if n.lower().endswith(".obj")), key=len)
        text, facts = normalise(raw.decode("utf-8", "replace"))
        print(json.dumps(facts, indent=1))
        print(len(cut_lines(text, min(CUT_HEIGHT, facts["wall_height"] * 0.45))), "plan lines")
    else:
        for line in selftest():
            print("ok:", line)
