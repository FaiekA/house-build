"""House Plan Build's designer: a palette for the house, one designed photo per room (Gemini's Nano Banana image
models), what each photo holds (its colours and furniture), the furniture placed in the 3D house, and free layout checks.
Standard library only. The model calls themselves are made here through `urllib`, but only when server.py asks, with
the key and a `record` for the cost center; everything else (palettes, furniture, placing, checks) is free code.

Two ways in (Faiek, 2026-11-22): a Sweet Home 3D model (it keeps its own furniture unless you ask for more, and can be
painted in the palette) or a floor plan picture (Claude reads it into plan JSON: `PLAN_RULES`, `parse_plan`).
The lessons of the "Floor Plan to 3D House" video: one house palette of named materials, light in layers, real
furniture sizes, styled like people live there, furniture as items in the plan data (one source of truth), and checks
after furnishing: walking routes between the doors, kitchen work triangle and aisles (NKBA), bathroom clearances (IRC).

    python housedesign.py            the offline checks
"""
import base64
import json
import math
import re
import sys
import urllib.error
import urllib.parse
import urllib.request

GEMINI_API = "https://generativelanguage.googleapis.com"
USER_AGENT = "Designed-Living/1.0"
FLASH_FALLBACK = "gemini-2.5-flash-image"           # Nano Banana
PRO_FALLBACK = "gemini-3-pro-image-preview"          # Nano Banana Pro
READ_MODEL = "gemini-flash-latest"                   # reads the photo back (config `house_read_model` overrides)
PHOTO_TIMEOUT_S = 90
READ_TIMEOUT_S = 40
CUT_TIMEOUT_S = 60
MAX_PHOTO_BYTES = 12 * 1024 * 1024
COST_FLASH_C, COST_PRO_C = 4, 13                     # cents a photo, about (shown on the page before you press)
USES = ("walls", "floor", "wood", "fabric", "metal", "stone", "accent")
FLOORS = ("wood", "stone", "tile", "carpet", "concrete")
HEX = re.compile(r"^#[0-9a-fA-F]{6}$")


class DesignError(Exception):
    def __init__(self, message, status=400):
        super().__init__(message)
        self.message, self.status = message, status


# ---------------------------------------------------------------- styles and the house palette
# Each style: words for the photo prompt and a palette of named materials (the video's "one house palette").
STYLES = {
    "cape-coastal": {"name": "Modern Cape coastal", "words": "modern Cape coastal, airy, natural textures, sea light",
                     "palette": [("Limewash white", "#efebe3", "walls"), ("Light oak", "#c9a77c", "floor"),
                                 ("Natural linen", "#d9cfbf", "fabric"), ("Sea-glass blue", "#8fb3b5", "accent"),
                                 ("Rope and rattan", "#b08a5a", "wood"), ("Brushed brass", "#b8955a", "metal")]},
    "warm-minimal": {"name": "Warm minimal", "words": "warm minimalist, calm, quiet luxury, few well-made pieces",
                     "palette": [("Warm white", "#f1ece4", "walls"), ("Travertine", "#d8c9b1", "stone"),
                                 ("Light oak", "#c8a57a", "floor"), ("Natural linen", "#dcd2c2", "fabric"),
                                 ("Smoked walnut", "#5b4332", "wood"), ("Matte black", "#2a2826", "metal")]},
    "scandi": {"name": "Scandinavian", "words": "Scandinavian, bright, pale woods, soft wool, simple shapes",
               "palette": [("Soft white", "#f3f1ec", "walls"), ("Pale ash", "#d8c3a0", "floor"),
                           ("Oat wool", "#cfc4b2", "fabric"), ("Dusty sage", "#9aa98f", "accent"),
                           ("Birch", "#e2cfae", "wood"), ("Matte black", "#2b2b2b", "metal")]},
    "afro-modern": {"name": "African modern", "words": "contemporary African modern, earthy, handwoven textiles, "
                                                       "sculptural clay pieces",
                    "palette": [("Clay white", "#ece3d6", "walls"), ("Dark iroko", "#6a4a32", "floor"),
                                ("Terracotta", "#b8653f", "accent"), ("Woven sisal", "#c7ad84", "fabric"),
                                ("Kiaat wood", "#8a5a36", "wood"), ("Aged bronze", "#7b6243", "metal")]},
    "industrial": {"name": "Soft industrial", "words": "soft industrial loft, polished concrete, leather, "
                                                      "warm timber, black steel",
                   "palette": [("Chalk grey", "#dcd8d1", "walls"), ("Polished concrete", "#a9a59e", "floor"),
                               ("Cognac leather", "#8c5534", "fabric"), ("Reclaimed oak", "#94714e", "wood"),
                               ("Black steel", "#262626", "metal"), ("Olive", "#6f7356", "accent")]},
    "classic": {"name": "Classic family home", "words": "classic, comfortable family home, timeless, layered fabrics",
                "palette": [("Cream", "#efe7d8", "walls"), ("Honey oak", "#b98d57", "floor"),
                            ("Stone linen", "#cbbfa9", "fabric"), ("Navy", "#2f3e57", "accent"),
                            ("Cherry wood", "#7b4a33", "wood"), ("Antique brass", "#a8874f", "metal")]},
    "japandi": {"name": "Japandi", "words": "Japandi, Japanese calm meets Scandinavian warmth, low furniture, "
                                            "paper light, clean lines",
                "palette": [("Rice paper", "#efe9df", "walls"), ("Smoked oak", "#8b6a4c", "floor"),
                            ("Undyed linen", "#d6cbb8", "fabric"), ("Moss", "#7d8466", "accent"),
                            ("Pale hinoki", "#d9c29c", "wood"), ("Charcoal", "#33312e", "metal")]},
    "mediterranean": {"name": "Mediterranean", "words": "Mediterranean villa, whitewashed plaster, terracotta tiles, "
                                                        "olive wood, arches and sun",
                      "palette": [("Whitewash", "#f4efe6", "walls"), ("Terracotta tile", "#b96d4a", "floor"),
                                  ("Washed linen", "#e0d5c3", "fabric"), ("Aegean blue", "#3f6e8c", "accent"),
                                  ("Olive wood", "#9a7b52", "wood"), ("Wrought iron", "#2e2b28", "metal")]},
    "mid-century": {"name": "Mid-century modern", "words": "mid-century modern, teak, tapered legs, mustard and "
                                                           "teal accents, globe lights",
                    "palette": [("Warm white", "#f0ebe1", "walls"), ("Teak", "#9a6337", "wood"),
                                ("Walnut parquet", "#7a5536", "floor"), ("Mustard", "#c9a03d", "accent"),
                                ("Teal wool", "#3e6d6a", "fabric"), ("Brass", "#b38f4f", "metal")]},
    "boho": {"name": "Bohemian", "words": "relaxed bohemian, layered rugs, rattan, macrame, many plants, warm light",
             "palette": [("Sand white", "#efe6d8", "walls"), ("Honey parquet", "#b88a55", "floor"),
                         ("Rust kilim", "#a65a3a", "fabric"), ("Fern green", "#6f8a5a", "accent"),
                         ("Rattan", "#c19a62", "wood"), ("Hammered brass", "#a88446", "metal")]},
    "farmhouse": {"name": "Modern farmhouse", "words": "modern farmhouse, shiplap, wide plank floors, "
                                                      "linen slipcovers, black hardware",
                  "palette": [("Shiplap white", "#f2efe8", "walls"), ("Wide oak plank", "#a88560", "floor"),
                              ("Flax linen", "#d4c8b4", "fabric"), ("Sage", "#8e9c84", "accent"),
                              ("Weathered pine", "#a58a69", "wood"), ("Black iron", "#262524", "metal")]},
    "dark-luxe": {"name": "Moody luxe", "words": "moody contemporary luxury, deep walls, velvet, marble, low warm "
                                                 "light, gold details",
                  "palette": [("Deep charcoal", "#3b3a39", "walls"), ("Dark walnut", "#4e3626", "floor"),
                              ("Emerald velvet", "#2f5a4a", "fabric"), ("Calacatta marble", "#e6e1d8", "stone"),
                              ("Ebony", "#2a211c", "wood"), ("Polished gold", "#c3a056", "metal")]},
    "spa": {"name": "Spa calm (bathrooms)", "words": "calm spa bathroom, large-format stone tiles, timber vanity, "
                                                      "soft hidden light, plants",
            "palette": [("Stone white", "#ece8e1", "walls"), ("Limestone tile", "#cfc6b6", "stone"),
                        ("Warm oak", "#b48d63", "wood"), ("Eucalyptus", "#8fa596", "accent"),
                        ("Waffle cotton", "#ebe6dc", "fabric"), ("Brushed nickel", "#9c9a94", "metal")]},
    "playful": {"name": "Playful (kids' rooms)", "words": "bright playful kids' room, rounded shapes, soft colour "
                                                          "blocks, storage at child height",
                "palette": [("Cloud white", "#f5f3ee", "walls"), ("Light birch", "#d9c19b", "floor"),
                            ("Sky blue", "#8fb4d4", "accent"), ("Sunny yellow", "#e8c35a", "fabric"),
                            ("Maple", "#d2a874", "wood"), ("Coral", "#e08a72", "metal")]},
}
DEFAULT_STYLE = "warm-minimal"
# What each style looks like, in plain words, and the rooms it suits: the Styles page shows these (Faiek, 2026-11-24:
# "need to know what all those styles are").
STYLE_NOTES = {
    "cape-coastal": ("Bright and airy like a beach house on the Atlantic seaboard. Pale walls, light wood, linen and "
                     "a touch of sea blue.", "Sunny lounges and bedrooms"),
    "warm-minimal": ("Calm and uncluttered, but never cold. A few well-made pieces in stone, oak and linen.",
                     "The whole house (the default)"),
    "scandi": ("Light and simple. Pale wood, soft wool, white walls and a little sage green.",
               "Small rooms and family spaces"),
    "afro-modern": ("Earthy and warm. Dark timber, handwoven textiles, terracotta and clay pieces.",
                    "Lounges and dining rooms"),
    "industrial": ("A loft feel made comfortable. Concrete floors, leather, warm timber and black steel.",
                   "Open-plan living and studies"),
    "classic": ("Timeless and cosy. Cream walls, honey oak and layered fabrics with navy accents.",
                "Family lounges and main bedrooms"),
    "japandi": ("Japanese calm meets Scandinavian warmth. Low furniture, paper light and clean lines.",
                "Bedrooms and quiet lounges"),
    "mediterranean": ("A sunny villa. Whitewashed plaster, terracotta tiles, olive wood and blue.",
                      "Kitchens, patios and dining rooms"),
    "mid-century": ("The 1960s done well. Teak, tapered legs, mustard and teal, globe lights.",
                    "Lounges and studies"),
    "boho": ("Relaxed and collected. Layered rugs, rattan, lots of plants and warm light.",
             "Lounges and guest rooms"),
    "farmhouse": ("Country comfort, kept clean. Shiplap walls, wide planks, linen and black hardware.",
                  "Kitchens and family rooms"),
    "dark-luxe": ("Deep and dramatic. Dark walls, velvet, marble and low golden light.",
                  "Dining rooms and TV rooms"),
    "spa": ("A hotel spa at home. Big stone tiles, a timber vanity, soft hidden light and plants.", "Bathrooms"),
    "playful": ("Bright and safe for children. Rounded shapes, soft colour blocks, storage at their height.",
                "Kids' rooms"),
}


def styles_view():
    """Every style for the Styles page: key, name, what it looks like, what it suits, and its palette."""
    return [{"key": k, "name": v["name"], "looks": STYLE_NOTES.get(k, ("", ""))[0],
             "best": STYLE_NOTES.get(k, ("", ""))[1], "palette": palette_of(k)} for k, v in STYLES.items()]


def palette_of(style):
    return [{"name": n, "hex": h, "use": u} for n, h, u in STYLES[style]["palette"]]


def clean_palette(items, limit=6):
    """A palette the page or a model sent: [{name, hex, use}], hexes and uses checked."""
    out = []
    for p in items or []:
        if not isinstance(p, dict):
            continue
        hexv = str(p.get("hex") or "").strip()
        if not HEX.match(hexv):
            continue
        use = str(p.get("use") or "accent").strip().lower()
        out.append({"name": re.sub(r"\s+", " ", str(p.get("name") or "Colour")).strip()[:30],
                    "hex": hexv.lower(), "use": use if use in USES else "accent"})
        if len(out) >= limit:
            break
    return out


def pick(palette, use, fallback):
    return next((p["hex"] for p in palette if p["use"] == use), fallback)


# ---------------------------------------------------------------- furniture
# kind: (width along its wall, depth into the room, height, how it is placed, clear space in front, label)
# Sizes are real furniture sizes in metres. Clearances: in front of a toilet or basin 0.53 m (IRC, 21 in), a kitchen
# work aisle 1.07 m (NKBA, 42 in), a walkway 0.9 m (36 in), beside a bed 0.6 m.
KINDS = {
    "sofa": (2.2, 0.95, 0.85, "wall", 0.9, "Sofa"),
    "armchair": (0.85, 0.85, 0.85, "corner", 0.5, "Armchair"),
    "coffee_table": (1.1, 0.6, 0.42, "front:sofa", 0.0, "Coffee table"),
    "rug": (2.4, 1.7, 0.01, "under", 0.0, "Rug"),
    "tv_unit": (1.8, 0.45, 0.55, "facing:sofa", 0.9, "TV unit"),
    "sideboard": (1.6, 0.45, 0.8, "wall", 0.9, "Sideboard"),
    "bookshelf": (1.0, 0.35, 1.9, "wall", 0.9, "Bookshelf"),
    "dining_table": (1.8, 0.95, 0.75, "centre", 0.9, "Dining table"),
    "dining_chair": (0.46, 0.5, 0.9, "around:dining_table", 0.0, "Dining chair"),
    "bed_double": (1.6, 2.05, 0.55, "wall", 0.6, "Double bed"),
    "bed_single": (0.95, 2.0, 0.55, "wall", 0.6, "Single bed"),
    "bedside": (0.45, 0.4, 0.55, "beside:bed", 0.0, "Bedside table"),
    "wardrobe": (1.6, 0.6, 2.1, "wall", 0.9, "Wardrobe"),
    "desk": (1.3, 0.65, 0.75, "wall", 0.9, "Desk"),
    "desk_chair": (0.55, 0.55, 0.9, "front:desk", 0.0, "Desk chair"),
    "counter": (2.4, 0.62, 0.9, "wall", 1.07, "Kitchen counter"),
    "sink_unit": (1.2, 0.62, 0.9, "wall", 1.07, "Sink"),
    "hob_unit": (0.9, 0.62, 0.9, "wall", 1.07, "Hob"),
    "fridge": (0.75, 0.7, 1.85, "wall", 1.07, "Fridge"),
    "island": (1.8, 0.9, 0.9, "centre", 1.07, "Kitchen island"),
    "toilet": (0.4, 0.7, 0.8, "wall", 0.53, "Toilet"),
    "basin": (0.6, 0.48, 0.85, "wall", 0.53, "Basin"),
    "shower": (0.9, 0.9, 2.0, "corner", 0.6, "Shower"),
    "bath": (1.7, 0.75, 0.55, "wall", 0.6, "Bath"),
    "washer": (0.6, 0.6, 0.85, "wall", 0.9, "Washing machine"),
    "plant": (0.45, 0.45, 1.2, "corner", 0.0, "Plant"),
    "floor_lamp": (0.4, 0.4, 1.6, "corner", 0.0, "Floor lamp"),
    "pendant": (0.45, 0.45, 0.35, "over", 0.0, "Pendant light"),
    "art": (1.0, 0.04, 0.7, "hang", 0.0, "Art"),
}
SOFT = {"rug", "art", "pendant"}
RUN_KINDS = ("fridge", "sink_unit", "hob_unit", "counter")                  # never block a walking route
OPTIONAL = ("plant", "floor_lamp", "armchair", "bookshelf", "sideboard", "island", "art")   # dropped first if in the way
MAX_EACH = {"dining_chair": 8, "bedside": 2, "plant": 2, "art": 2, "pendant": 2, "counter": 2}
MAX_ITEMS = 22
# What a room gets when no photo has been read (or it showed nothing usable), by its name. Free.
KITS = [
    (r"kitchen|scullery", ["counter", "sink_unit", "hob_unit", "fridge", "island", "pendant"]),
    (r"dining", ["dining_table", "dining_chair", "dining_chair", "dining_chair", "dining_chair", "dining_chair",
                 "dining_chair", "pendant", "sideboard", "art"]),
    (r"living|lounge|family|tv|sitting|den", ["sofa", "coffee_table", "rug", "tv_unit", "armchair", "floor_lamp",
                                              "plant", "art", "bookshelf"]),
    (r"main|master|suite|bed", ["bed_double", "bedside", "bedside", "wardrobe", "rug", "art", "plant"]),
    (r"bath|shower|ensuite|en-suite|wc|toilet|powder", ["toilet", "basin", "shower", "bath"]),
    (r"study|office|work", ["desk", "desk_chair", "bookshelf", "floor_lamp", "plant"]),
    (r"laundry|utility", ["washer", "washer", "counter"]),
    (r"entr|foyer|hall|lobby", ["sideboard", "art", "plant"]),
    (r"patio|stoep|veranda|deck|braai", ["dining_table", "dining_chair", "dining_chair", "dining_chair",
                                         "dining_chair", "plant", "plant"]),
]
SKIP_ROOMS = re.compile(r"garage|store|storage|passage|corridor|pantry|plant room|carport", re.I)


def kit_for(room):
    name, w, d = room["name"], room["x"][1] - room["x"][0], room["y"][1] - room["y"][0]
    if SKIP_ROOMS.search(name):
        return []
    kinds = []
    for pattern, kit in KITS:
        if re.search(pattern, name, re.I):
            kinds += [k for k in kit if k not in kinds or k in MAX_EACH]
    area = w * d
    if re.search(r"bed", name, re.I) and area < 10.5 and not re.search(r"main|master|suite", name, re.I):
        kinds = ["bed_single" if k == "bed_double" else k for k in kinds]
        kinds = [k for k in kinds if k != "bedside"] + ["bedside"]
    if "island" in kinds and min(w, d) < 3.6:
        kinds.remove("island")
    if "bath" in kinds and area < 6:
        kinds.remove("bath")
    if "bookshelf" in kinds and area < 14:
        kinds.remove("bookshelf")
    if "dining_chair" in kinds and min(w, d) < 3.0:
        extra = [i for i, k in enumerate(kinds) if k == "dining_chair"][4:]
        kinds = [k for i, k in enumerate(kinds) if i not in extra]
    return kinds


# ---------------------------------------------------------------- doors of each room
def plan_doors(plan):
    """[(x, y, width)] of every door in a plan JSON."""
    walls = {w.get("id"): w for w in (plan or {}).get("walls") or []}
    out = []
    for o in (plan or {}).get("openings") or []:
        w = walls.get(o.get("wall"))
        if not w or o.get("kind") not in ("door", "sliding", "opening", "garage"):
            continue
        (ax, ay), (bx, by) = w["a"], w["b"]
        L = math.hypot(bx - ax, by - ay) or 1
        m = (float(o["from"]) + float(o["to"])) / 2
        out.append((ax + (bx - ax) / L * m, ay + (by - ay) / L * m, abs(float(o["to"]) - float(o["from"]))))
    return out


def room_doors(room, rooms, doors=None, entrance=None):
    """Points on this room's edge where you walk in: the plan's doors, else where it meets the other rooms."""
    x0, x1, y0, y1 = room["x"][0], room["x"][1], room["y"][0], room["y"][1]

    def on_edge(x, y, tol=0.35):
        return (x0 - tol <= x <= x1 + tol and y0 - tol <= y <= y1 + tol
                and min(abs(x - x0), abs(x - x1), abs(y - y0), abs(y - y1)) <= tol)

    found = []
    if doors:
        found = [(min(max(x, x0), x1), min(max(y, y0), y1), w or 0.9) for x, y, w in doors if on_edge(x, y)]
    else:
        for other in rooms:
            if other is room:
                continue
            ox0, ox1, oy0, oy1 = other["x"][0], other["x"][1], other["y"][0], other["y"][1]
            for a, b, c0, c1, d0, d1 in ((x1, ox0, y0, y1, oy0, oy1), (ox1, x0, y0, y1, oy0, oy1)):
                if abs(a - b) <= 0.35:
                    lo, hi = max(c0, d0), min(c1, d1)
                    if hi - lo >= 0.8:
                        found.append(((x1 if a == x1 else x0), (lo + hi) / 2, 0.9))
            for a, b, c0, c1, d0, d1 in ((y1, oy0, x0, x1, ox0, ox1), (oy1, y0, x0, x1, ox0, ox1)):
                if abs(a - b) <= 0.35:
                    lo, hi = max(c0, d0), min(c1, d1)
                    if hi - lo >= 0.8:
                        found.append(((lo + hi) / 2, (y1 if a == y1 else y0), 0.9))
        if entrance and on_edge(entrance["x"], entrance["y"], 0.6):
            found.append((min(max(entrance["x"], x0), x1), min(max(entrance["y"], y0), y1), 0.9))
    if not found:                                    # no door known: assume one in the middle of the longest side
        found = [((x0 + x1) / 2, y0, 0.9)] if x1 - x0 >= y1 - y0 else [(x0, (y0 + y1) / 2, 0.9)]
    out = []
    for p in found:
        if all(math.hypot(p[0] - q[0], p[1] - q[1]) > 0.5 for q in out):
            out.append(p)
    return out


# ---------------------------------------------------------------- placing furniture
def footprint(x, y, w, d, rot):
    """The box an item covers on the plan: (x0, y0, x1, y1). rot = the way its front faces (0 north, 90 east...)."""
    if rot in (90, 270):
        w, d = d, w
    return (x - w / 2, y - d / 2, x + w / 2, y + d / 2)


def front_zone(x, y, w, d, rot, depth):
    """The clear space in front of an item."""
    if depth <= 0:
        return None
    dx, dy = {0: (0, 1), 90: (1, 0), 180: (0, -1), 270: (-1, 0)}[rot]
    cx, cy = x + dx * (d / 2 + depth / 2), y + dy * (d / 2 + depth / 2)
    return footprint(cx, cy, w, depth, rot)


def overlap(a, b, gap=0.001):
    return a[0] < b[2] - gap and b[0] < a[2] - gap and a[1] < b[3] - gap and b[1] < a[3] - gap


def inside(box, room, tol=0.005):
    return (box[0] >= room["x"][0] - tol and box[2] <= room["x"][1] + tol
            and box[1] >= room["y"][0] - tol and box[3] <= room["y"][1] + tol)


class Layout:
    """One room's furniture, placed by rules: backs to walls, clear of doors, clear space kept in front of each piece."""

    def __init__(self, room, doors):
        self.room, self.doors, self.items = room, doors, []
        x0, x1, y0, y1 = room["x"][0], room["x"][1], room["y"][0], room["y"][1]
        self.door_zones = []
        for dx, dy, dw in doors:        # the door's width plus a little, 0.9 m into the room (its swing)
            half = dw / 2 + 0.1
            if abs(dy - y0) < 0.4:
                self.door_zones.append((dx - half, y0, dx + half, y0 + 0.9))
            elif abs(dy - y1) < 0.4:
                self.door_zones.append((dx - half, y1 - 0.9, dx + half, y1))
            elif abs(dx - x0) < 0.4:
                self.door_zones.append((x0, dy - half, x0 + 0.9, dy + half))
            else:
                self.door_zones.append((x1 - 0.9, dy - half, x1, dy + half))

    def solid(self):
        return [i for i in self.items if i["kind"] not in SOFT]

    def free(self, box, zone=None, ignore=()):
        if not inside(box, self.room):
            return False
        if any(overlap(box, z) for z in self.door_zones):
            return False
        for it in self.solid():
            if it in ignore:
                continue
            if overlap(box, it["box"]):
                return False
            if it.get("zone") and overlap(box, it["zone"], 0.02):
                return False
        if zone is not None:
            if not inside(zone, self.room, 0.05) or any(overlap(zone, it["box"]) for it in self.solid() if it not in ignore):
                return False
        return True

    def door_distance(self, x, y):
        return min(math.hypot(x - dx, y - dy) for dx, dy, _ in self.doors)

    def add(self, kind, x, y, rot, w=None, d=None, colour=None, accent=None, label=None):
        kw, kd, kh, _rule, clear, name = KINDS[kind]
        w, d = w or kw, d or kd
        item = {"kind": kind, "label": label or name, "x": round(x, 3), "y": round(y, 3), "w": round(w, 3),
                "d": round(d, 3), "h": kh, "rot": rot, "box": footprint(x, y, w, d, rot),
                "zone": front_zone(x, y, w, d, rot, clear) if kind not in SOFT else None}
        if colour:
            item["c"] = colour
        if accent:
            item["a"] = accent
        self.items.append(item)
        return item

    def wall_spots(self, w, d, step=0.1):
        """Every place along the four walls an item w wide and d deep fits with its back to the wall."""
        x0, x1, y0, y1 = self.room["x"][0], self.room["x"][1], self.room["y"][0], self.room["y"][1]
        out = []
        for rot, fixed, lo, hi, horizontal in ((0, y0 + d / 2, x0 + w / 2, x1 - w / 2, True),
                                               (180, y1 - d / 2, x0 + w / 2, x1 - w / 2, True),
                                               (90, x0 + d / 2, y0 + w / 2, y1 - w / 2, False),
                                               (270, x1 - d / 2, y0 + w / 2, y1 - w / 2, False)):
            if hi < lo:
                continue
            n = int((hi - lo) / step)
            for k in range(n + 1):
                v = lo + k * step
                out.append((v, fixed, rot) if horizontal else (fixed, v, rot))
            if (hi - lo) / step != n:
                out.append(((hi, fixed, rot) if horizontal else (fixed, hi, rot)))
        return out

    def stretches(self, depth):
        """Free lengths along each wall (doors and pieces already there cut them): [(rot, start point, length)]."""
        x0, x1, y0, y1 = self.room["x"][0], self.room["x"][1], self.room["y"][0], self.room["y"][1]
        out = []
        for rot, horizontal, lo, hi in ((0, True, x0, x1), (180, True, x0, x1), (90, False, y0, y1),
                                        (270, False, y0, y1)):
            band = {0: (x0, y0, x1, y0 + depth), 180: (x0, y1 - depth, x1, y1), 90: (x0, y0, x0 + depth, y1),
                    270: (x1 - depth, y0, x1, y1)}[rot]
            cuts = []
            for z in self.door_zones + [i["box"] for i in self.solid()]:
                if overlap(z, band):
                    cuts.append((z[0], z[2]) if horizontal else (z[1], z[3]))
            pos = lo
            for a, b in sorted(cuts) + [(hi, hi)]:
                if a - pos >= 0.6:
                    out.append((rot, pos, a - pos))
                pos = max(pos, b)
        return sorted(out, key=lambda s: -s[2])

    def lay_units(self, rot, start, units, colours):
        x0, x1, y0, y1 = self.room["x"][0], self.room["x"][1], self.room["y"][0], self.room["y"][1]
        pos = start
        for kind, w in units:
            d = KINDS[kind][1]
            c = pos + w / 2
            x, y = {0: (c, y0 + d / 2), 180: (c, y1 - d / 2), 90: (x0 + d / 2, c), 270: (x1 - d / 2, c)}[rot]
            self.add(kind, x, y, rot, w, d, colours.get(kind))
            pos += w

    def place_run(self, kinds, colours):
        """The kitchen: fridge, a little worktop, sink, worktop, hob, in one run (or an L / galley over two walls),
        so the work triangle can be checked (NKBA: each side 1.2-2.7 m)."""
        fridge, sink, hob = "fridge" in kinds, "sink_unit" in kinds, "hob_unit" in kinds
        one = ([("fridge", 0.75), ("counter", 0.45)] if fridge else []) + ([("sink_unit", 1.2)] if sink else []) \
            + [("counter", 0.6)] + ([("hob_unit", 0.9)] if hob else [])
        need = sum(w for _, w in one)
        spans = self.stretches(0.62)
        if spans and spans[0][2] >= need:
            rot, start, length = spans[0]
            extra = min(length - need, 1.2)
            units = one + ([("counter", round(extra, 2))] if extra >= 0.3 else [])
            self.lay_units(rot, start + (length - need - (extra if extra >= 0.3 else 0)) / 2, units, colours)
            return True
        a = ([("fridge", 0.75), ("counter", 0.45)] if fridge else []) + ([("sink_unit", 1.2)] if sink else [])
        b = ([("hob_unit", 0.9)] if hob else []) + [("counter", 0.6)]
        if len(spans) >= 2 and spans[0][2] >= sum(w for _, w in a) and any(
                s[0] != spans[0][0] and s[2] >= sum(w for _, w in b) for s in spans[1:]):
            first = spans[0]
            self.lay_units(first[0], first[1], a, colours)
            second = next(s for s in self.stretches(0.62) if s[0] != first[0] and s[2] >= sum(w for _, w in b))
            self.lay_units(second[0], second[1] + (second[2] - sum(w for _, w in b)) / 2, b, colours)
            return True
        for kind in kinds:                   # no run fits: each where it can
            self.place_wall(kind, colour=colours.get(kind))
        return False

    def place_wall(self, kind, prefer="far", near=None, colour=None, accent=None, size=None, reserve=0.0):
        """Back to a wall. `reserve`: room kept free at both sides (a bed's bedside tables)."""
        kw, kd = size or KINDS[kind][:2]
        clear = KINDS[kind][4]
        best, best_score = None, None
        x0, x1, y0, y1 = self.room["x"][0], self.room["x"][1], self.room["y"][0], self.room["y"][1]
        for x, y, rot in self.wall_spots(kw + 2 * reserve, kd):
            box = footprint(x, y, kw + 2 * reserve, kd, rot)
            zone = front_zone(x, y, kw, kd, rot, clear)
            if kind == "toilet":            # IRC: 15 in (0.38 m) from its centre to anything at its sides
                side = footprint(x, y, 0.76, kd, rot)
                if not self.free(side) or not inside(side, self.room):
                    continue
            if not self.free(box, zone):
                continue
            if prefer == "near" and near is not None:
                score = -math.hypot(x - near[0], y - near[1])
            else:
                score = self.door_distance(x, y)
                if prefer == "centred":   # a sofa, bed or TV sits in the middle of its wall
                    along = (x - (x0 + x1) / 2) if rot in (0, 180) else (y - (y0 + y1) / 2)
                    score -= abs(along) * 0.6
            if best_score is None or score > best_score:
                best, best_score = (x, y, rot), score
        if not best:
            return None
        return self.add(kind, best[0], best[1], best[2], kw, kd, colour, accent)

    def place_centre(self, kind, colour=None, accent=None, size=None):
        kw, kd = size or KINDS[kind][:2]
        clear = KINDS[kind][4]
        x0, x1, y0, y1 = self.room["x"][0], self.room["x"][1], self.room["y"][0], self.room["y"][1]
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        rot = 0 if (x1 - x0) >= (y1 - y0) else 90
        best = None
        for scale in (1.0, 0.85, 0.7):
            w, d = kw * scale, kd * scale
            for k in range(0, 60):
                ang, rad = k * 2.39996, 0.08 * math.sqrt(k) * max(x1 - x0, y1 - y0)
                x, y = cx + rad * math.cos(ang), cy + rad * math.sin(ang)
                box = footprint(x, y, w, d, rot)
                ring = (box[0] - clear, box[1] - clear, box[2] + clear, box[3] + clear)
                if self.free(box) and inside(ring, self.room) and not any(overlap(ring, i["box"]) for i in self.solid()):
                    best = (x, y, w, d)
                    break
            if best:
                break
        if not best:
            return None
        item = self.add(kind, best[0], best[1], rot, best[2], best[3], colour, accent)
        item["zone"] = None
        item["ring"] = clear
        return item

    def place_corner(self, kind, colour=None, accent=None):
        kw, kd = KINDS[kind][:2]
        x0, x1, y0, y1 = self.room["x"][0], self.room["x"][1], self.room["y"][0], self.room["y"][1]
        m = 0.05
        corners = [(x0 + kw / 2 + m, y0 + kd / 2 + m, 0), (x1 - kw / 2 - m, y0 + kd / 2 + m, 0),
                   (x0 + kw / 2 + m, y1 - kd / 2 - m, 180), (x1 - kw / 2 - m, y1 - kd / 2 - m, 180)]
        corners.sort(key=lambda c: -self.door_distance(c[0], c[1]))
        for x, y, rot in corners:
            box = footprint(x, y, kw, kd, rot)
            if self.free(box, front_zone(x, y, kw, kd, rot, KINDS[kind][4])):
                return self.add(kind, x, y, rot, kw, kd, colour, accent)
        return self.place_wall(kind, colour=colour, accent=accent)

    def place_front(self, kind, anchor, gap, colour=None, accent=None):
        kw, kd = KINDS[kind][:2]
        if kind == "coffee_table":
            kw = min(kw, anchor["w"] * 0.55)
        dx, dy = {0: (0, 1), 90: (1, 0), 180: (0, -1), 270: (-1, 0)}[anchor["rot"]]
        dist = anchor["d"] / 2 + gap + kd / 2
        x, y = anchor["x"] + dx * dist, anchor["y"] + dy * dist
        rot = (anchor["rot"] + 180) % 360 if kind == "desk_chair" else anchor["rot"]
        box = footprint(x, y, kw, kd, rot)
        if not self.free(box, ignore=[anchor]) or not inside(box, self.room):
            return None
        item = self.add(kind, x, y, rot, kw, kd, colour, accent)
        item["zone"] = None
        return item

    def place_facing(self, kind, anchor, colour=None, accent=None):
        """A TV unit on the wall the sofa faces."""
        want = (anchor["rot"] + 180) % 360
        spots = [s for s in self.wall_spots(*KINDS[kind][:2]) if s[2] == want]
        spots.sort(key=lambda s: math.hypot(s[0] - anchor["x"], s[1] - anchor["y"]) * 0
                   + (abs(s[0] - anchor["x"]) if want in (0, 180) else abs(s[1] - anchor["y"])))
        for x, y, rot in spots:
            box = footprint(x, y, *KINDS[kind][:2], rot)
            if self.free(box):
                item = self.add(kind, x, y, rot, colour=colour, accent=accent)
                item["zone"] = None
                return item
        return self.place_wall(kind, colour=colour, accent=accent)

    def place_beside(self, kind, bed, colour=None, accent=None):
        kw, kd = KINDS[kind][:2]
        rot = bed["rot"]
        ux, uy = {0: (1, 0), 180: (-1, 0), 90: (0, -1), 270: (0, 1)}[rot]     # along the bed's head wall
        bx, by = {0: (0, -1), 180: (0, 1), 90: (-1, 0), 270: (1, 0)}[rot]     # towards that wall
        for side in (1, -1):
            off = bed["w"] / 2 + 0.05 + kw / 2
            back = bed["d"] / 2 - kd / 2
            x, y = bed["x"] + ux * off * side + bx * back, bed["y"] + uy * off * side + by * back
            box = footprint(x, y, kw, kd, rot)
            if self.free(box) and not any(i["kind"] == kind and abs(i["x"] - x) < 0.01 and abs(i["y"] - y) < 0.01
                                          for i in self.items):
                return self.add(kind, x, y, rot, kw, kd, colour, accent)
        return None

    def place_around(self, kind, table, n, colour=None, accent=None):
        """Chairs round a table: along its long sides, 0.6 m apart, then the ends."""
        kw, kd = KINDS[kind][:2]
        horizontal = table["rot"] in (0, 180)
        long_ = table["w"] if horizontal else table["d"]
        per_side = max(1, int(long_ / 0.6))
        seats = []
        for side in (1, -1):
            for k in range(per_side):
                t = (k + 0.5) / per_side - 0.5
                off = (table["d"] if horizontal else table["w"]) / 2 + kd / 2 - 0.08
                if horizontal:
                    seats.append((table["x"] + t * long_, table["y"] + side * off, 180 if side > 0 else 0))
                else:
                    seats.append((table["x"] + side * off, table["y"] + t * long_, 270 if side > 0 else 90))
        end = (table["w"] if horizontal else table["d"]) / 2 + kd / 2 - 0.08
        if horizontal:
            seats += [(table["x"] - end, table["y"], 90), (table["x"] + end, table["y"], 270)]
        else:
            seats += [(table["x"], table["y"] - end, 0), (table["x"], table["y"] + end, 180)]
        placed = 0
        for x, y, rot in seats:
            if placed >= n:
                break
            box = footprint(x, y, kw, kd, rot)
            if self.free(box, ignore=[table]):
                item = self.add(kind, x, y, rot, kw, kd, colour, accent)
                item["zone"] = None
                placed += 1
        return placed


def furnish(room, kinds, doors, palette, colours=None):
    """Place `kinds` in the room. -> (items for the engine, layout)."""
    colours = colours or {}
    lay = Layout(room, doors)
    fabric, wood = pick(palette, "fabric", "#cfc4b2"), pick(palette, "wood", "#8a6a4a")
    accent, metal = pick(palette, "accent", "#8fa3a0"), pick(palette, "metal", "#2a2a2a")
    stone = pick(palette, "stone", "#d8d2c6")
    default = {"sofa": fabric, "armchair": accent, "coffee_table": wood, "rug": fabric, "tv_unit": wood,
               "sideboard": wood, "bookshelf": wood, "dining_table": wood, "dining_chair": wood, "bed_double": fabric,
               "bed_single": fabric, "bedside": wood, "wardrobe": wood, "desk": wood, "desk_chair": metal,
               "counter": wood, "sink_unit": wood, "hob_unit": wood, "fridge": "#d9d9d6", "island": wood,
               "toilet": "#f4f4f2", "basin": stone, "shower": stone, "bath": "#f4f4f2", "washer": "#f1f1ef",
               "plant": "#4f6b3e", "floor_lamp": metal, "pendant": metal, "art": accent}

    def col(kind):
        return colours.get(kind) or default.get(kind)

    counts = {}
    rank = ["wall", "corner", "centre", "facing:sofa", "front:sofa", "front:desk", "beside:bed",
            "around:dining_table", "under", "over", "hang"]
    order = sorted(kinds, key=lambda k: rank.index(KINDS[k][3]) if k in KINDS else 99)
    big = [k for k in order if k in KINDS and KINDS[k][3] == "wall" and KINDS[k][0] * KINDS[k][1] >= 1.0]
    middle = [k for k in order if k in KINDS and KINDS[k][3] == "centre"]
    beside = [k for k in order if k in KINDS and KINDS[k][3] == "beside:bed"]
    order = big + beside + middle + [k for k in order if k not in big and k not in middle and k not in beside]
    run = [k for k in ("fridge", "sink_unit", "hob_unit") if k in kinds]
    if len(run) >= 2:                     # a kitchen: one run of units, split over two walls when one is too short
        lay.place_run(run, {k: col(k) for k in RUN_KINDS})
        order = [k for k in order if k not in RUN_KINDS]
    first = lambda kind: next((i for i in lay.items if i["kind"] == kind), None)
    bed = lambda: next((i for i in lay.items if i["kind"].startswith("bed_")), None)
    for kind in order:
        if kind not in KINDS:
            continue
        counts[kind] = counts.get(kind, 0) + 1
        if counts[kind] > MAX_EACH.get(kind, 1) or len(lay.items) >= MAX_ITEMS:
            continue
        rule = KINDS[kind][3]
        if rule == "wall":
            prefer = "centred" if kind in ("sofa", "bed_double", "bed_single", "sideboard") else "far"
            near = None
            if kind in ("sink_unit", "hob_unit", "fridge", "counter"):
                c = first("counter") or first("sink_unit")
                if c:
                    prefer, near = "near", (c["x"], c["y"])
            if kind == "basin" and first("toilet"):
                prefer, near = "near", (first("toilet")["x"], first("toilet")["y"])
            reserve = 0.5 if kind.startswith("bed_") and "bedside" in kinds else 0.0
            if not lay.place_wall(kind, prefer, near, col(kind), reserve=reserve) and reserve:
                lay.place_wall(kind, prefer, near, col(kind))
        elif rule == "corner":
            lay.place_corner(kind, col(kind))
        elif rule == "centre":
            lay.place_centre(kind, col(kind))
        elif rule == "facing:sofa":
            sofa = first("sofa")
            lay.place_facing(kind, sofa, col(kind)) if sofa else lay.place_wall(kind, colour=col(kind))
        elif rule.startswith("front:"):
            anchor = first(rule[6:])
            if anchor:
                lay.place_front(kind, anchor, 0.45 if kind == "coffee_table" else 0.05, col(kind))
        elif rule == "beside:bed":
            if bed():
                lay.place_beside(kind, bed(), col(kind))
        elif rule.startswith("around:"):
            table = first("dining_table")
            if table and counts[kind] == 1:
                lay.place_around(kind, table, sum(1 for k in kinds if k == kind), col(kind))
        elif rule == "under":
            anchor = first("coffee_table") or bed() or first("dining_table") or first("sofa")
            x0, x1, y0, y1 = room["x"][0], room["x"][1], room["y"][0], room["y"][1]
            cx, cy = (anchor["x"], anchor["y"]) if anchor else ((x0 + x1) / 2, (y0 + y1) / 2)
            w, d = min(2.4, (x1 - x0) - 0.6), min(1.7, (y1 - y0) - 0.6)
            if w > 1 and d > 0.8:
                cx = min(max(cx, x0 + w / 2 + 0.3), x1 - w / 2 - 0.3)
                cy = min(max(cy, y0 + d / 2 + 0.3), y1 - d / 2 - 0.3)
                lay.add(kind, cx, cy, 0, w, d, col(kind), accent)
        elif rule == "over":
            anchor = first("dining_table") or first("island") or first("desk") or bed() or first("coffee_table")
            x0, x1, y0, y1 = room["x"][0], room["x"][1], room["y"][0], room["y"][1]
            if counts[kind] == 1:
                cx, cy = (anchor["x"], anchor["y"]) if anchor else ((x0 + x1) / 2, (y0 + y1) / 2)
                lay.add(kind, cx, cy, 0, colour=col(kind), accent=accent)
        elif rule == "hang":
            anchor = first("sofa") or bed() or first("sideboard") or first("dining_table")
            if anchor and counts[kind] == 1 and anchor["kind"] != "dining_table":
                dx, dy = {0: (0, -1), 90: (-1, 0), 180: (0, 1), 270: (1, 0)}[anchor["rot"]]
                x, y = anchor["x"] + dx * (anchor["d"] / 2 - 0.02), anchor["y"] + dy * (anchor["d"] / 2 - 0.02)
                item = lay.add(kind, x, y, anchor["rot"], min(1.2, anchor["w"] * 0.6), 0.04, col(kind), wood)
                item["z"] = 1.25 if anchor["kind"] in ("sofa", "sideboard") else 1.15
            else:
                spot = next(iter(lay.wall_spots(1.0, 0.04)), None)
                spots = sorted(lay.wall_spots(1.0, 0.04), key=lambda s: -lay.door_distance(s[0], s[1]))
                for x, y, rot in spots:
                    box = footprint(x, y, 1.0, 0.3, rot)
                    if not any(overlap(box, i["box"]) and i["h"] > 1.2 for i in lay.solid()) and spot:
                        item = lay.add(kind, x, y, rot, 1.0, 0.04, col(kind), wood)
                        item["z"] = 1.45
                        break
    return lay


# ---------------------------------------------------------------- checks after furnishing
CELL = 0.1
PATH_HALF = 0.38                 # a clear path at least 0.76 m wide (walkways 36 in are the aim)


def _grid(lay):
    x0, x1, y0, y1 = lay.room["x"][0], lay.room["x"][1], lay.room["y"][0], lay.room["y"][1]
    nx, ny = max(1, int(round((x1 - x0) / CELL))), max(1, int(round((y1 - y0) / CELL)))
    solid = [i["box"] for i in lay.solid()]
    free = [[True] * ny for _ in range(nx)]
    for ix in range(nx):
        for iy in range(ny):
            px, py = x0 + (ix + 0.5) * CELL, y0 + (iy + 0.5) * CELL
            near_wall = min(px - x0, x1 - px, py - y0, y1 - py) < PATH_HALF - 0.12
            body = (px - PATH_HALF + 0.12, py - PATH_HALF + 0.12, px + PATH_HALF - 0.12, py + PATH_HALF - 0.12)
            if any(overlap(body, b) for b in solid):
                free[ix][iy] = False
            elif near_wall:
                free[ix][iy] = "edge"
    return free, nx, ny, x0, y0


def _cell(x, y, nx, ny, x0, y0):
    return min(nx - 1, max(0, int((x - x0) / CELL))), min(ny - 1, max(0, int((y - y0) / CELL)))


def _reach(free, nx, ny, start):
    seen, todo = {start}, [start]
    while todo:
        cx, cy = todo.pop()
        for ax, ay in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
            if 0 <= ax < nx and 0 <= ay < ny and (ax, ay) not in seen and free[ax][ay]:
                seen.add((ax, ay))
                todo.append((ax, ay))
    return seen


def use_point(item):
    """Where you stand to use a piece: just in front of it."""
    dx, dy = {0: (0, 1), 90: (1, 0), 180: (0, -1), 270: (-1, 0)}[item["rot"]]
    off = item["d"] / 2 + 0.35
    return item["x"] + dx * off, item["y"] + dy * off


def routes_ok(lay):
    """Every door reaches every other door, and the front of each piece you use, by a clear path."""
    if len(lay.doors) == 0:
        return True, ""
    free, nx, ny, x0, y0 = _grid(lay)

    def door_cell(d):
        dx, dy, _ = d
        best, best_d = None, None
        for ix in range(nx):
            for iy in range(ny):
                if free[ix][iy]:
                    px, py = x0 + (ix + 0.5) * CELL, y0 + (iy + 0.5) * CELL
                    dist = math.hypot(px - dx, py - dy)
                    if dist < 0.9 and (best_d is None or dist < best_d):
                        best, best_d = (ix, iy), dist
        return best

    starts = [door_cell(d) for d in lay.doors]
    if any(s is None for s in starts):
        return False, "a door is blocked"
    seen = _reach(free, nx, ny, starts[0])
    if any(s not in seen for s in starts[1:]):
        return False, "you can't walk from one door to the other"
    for it in lay.solid():
        if it["kind"] in ("plant", "floor_lamp", "dining_chair", "desk_chair", "coffee_table", "bedside"):
            continue
        b = it["box"]
        reach = 0.75 if it["kind"] in ("sofa", "armchair", "bed_double", "bed_single", "dining_table") else 0.5
        if not any(math.hypot(max(b[0] - px, 0, px - b[2]), max(b[1] - py, 0, py - b[3])) <= reach
                   for px, py in ((x0 + (ix + 0.5) * CELL, y0 + (iy + 0.5) * CELL) for ix, iy in seen)):
            return False, f"you can't get to the {it['label'].lower()}"
    return True, ""


def checks(lay):
    """The free layout checks for one room -> [{ok, text}] in plain words."""
    out = []
    name = lay.room["name"]
    ok, why = routes_ok(lay)
    out.append({"ok": ok, "text": f"{name}: clear walking routes between the doors (at least 76 cm wide)"
                if ok else f"{name}: {why}"})
    kinds = {i["kind"]: i for i in lay.items}
    if all(k in kinds for k in ("sink_unit", "hob_unit", "fridge")):
        pts = [(kinds[k]["x"], kinds[k]["y"]) for k in ("sink_unit", "hob_unit", "fridge")]
        sides = [math.hypot(pts[a][0] - pts[b][0], pts[a][1] - pts[b][1]) for a, b in ((0, 1), (1, 2), (2, 0))]
        rots = {kinds[k]["rot"] for k in ("sink_unit", "hob_unit", "fridge")}
        if len(rots) == 1:
            out.append({"ok": True, "text": f"{name}: a one-wall kitchen, fridge, sink and hob in one run "
                        "(the work triangle doesn't apply, NKBA)"})
        else:
            good = all(1.2 <= s <= 2.75 for s in sides) and sum(sides) <= 7.9
            out.append({"ok": good, "text": f"{name}: kitchen work triangle {sum(sides):.1f} m "
                        f"(sides {', '.join(f'{s:.1f}' for s in sides)} m; NKBA: each 1.2-2.7 m, under 7.9 m in all)"})
    if "island" in kinds:
        out.append({"ok": True, "text": f"{name}: 1.07 m work aisle kept round the island (NKBA)"})
    for k, words in (("toilet", "toilet: 53 cm clear in front, 38 cm from its centre to the side (IRC)"),
                     ("basin", "basin: 53 cm clear in front (IRC)")):
        if k in kinds:
            out.append({"ok": True, "text": f"{name}: {words}"})
    if "shower" in kinds:
        s = kinds["shower"]
        out.append({"ok": min(s["w"], s["d"]) >= 0.76, "text": f"{name}: shower at least 76 cm inside (IRC)"})
    return out


def design_room(room, kinds, doors, palette, colours=None):
    """Furnish, check, and take out optional pieces one at a time until the routes are clear."""
    lay = furnish(room, kinds, doors, palette, colours)
    dropped = []
    while not routes_ok(lay)[0]:
        spare = next((i for i in reversed(lay.items) if i["kind"] in OPTIONAL), None)
        if not spare:
            break
        lay.items.remove(spare)
        dropped.append(spare["label"])
    results = checks(lay)
    if dropped:
        results.append({"ok": True, "text": f"{room['name']}: left out to keep the routes clear: "
                        + ", ".join(sorted(set(dropped)))})
    missing = [KINDS[k][5] for k in dict.fromkeys(kinds) if k in KINDS and KINDS[k][3] not in ("under", "over", "hang")
               and not any(i["kind"] == k for i in lay.items) and KINDS[k][5] not in dropped]
    if missing:
        results.append({"ok": False, "text": f"{room['name']}: no room for " + ", ".join(missing)})
    items = [{k: v for k, v in i.items() if k not in ("box", "zone", "ring")} for i in lay.items]
    return items, results


# ---------------------------------------------------------------- the photo of each room (Nano Banana)
GARAGE_RE = re.compile(r"garage|carport", re.I)
NARROW_KINDS = ("art", "plant", "pendant", "rug")
PASSAGE_RE = re.compile(r"passage|corridor|hallway|\bhall\b", re.I)


def photo_prompt(room, style_words, palette, wall_height, extra=""):
    w, d = room["x"][1] - room["x"][0], room["y"][1] - room["y"][0]
    named = "; ".join(f"{p['name']} ({p['hex']}) for {p['use']}" for p in palette)
    note = f" About this room: {room['note']}." if room.get("note") else ""
    wish = f" The owner asks for: {extra.strip()[:300]}." if extra and extra.strip() else ""
    name = room["name"].lower()
    if GARAGE_RE.search(name):                      # Faiek, 2026-11-24: the garage came back as a lounge
        return (f"A professional photograph of a clean, well-organised garage in a {style_words} home. The garage is "
                f"{w:.1f} by {d:.1f} metres with {wall_height:.1f} metre ceilings.{note}{wish} A sealed grey concrete "
                f"floor, one modern car parked inside, the roll-up garage door, tidy wall storage (shelves, cabinets, "
                f"hooks), a bicycle, bright practical ceiling lights. No sofa, rug, bed or living-room furniture. "
                f"Walls and cabinets in this house palette where it fits: {named}. Wide eye-level shot from the door "
                f"to the house, photorealistic, no people, no text, no watermark, no border.")
    if PASSAGE_RE.search(name):
        return (f"A professional interior designer's photograph of a {name} (a narrow hallway) in a {style_words} "
                f"home. It is {w:.1f} by {d:.1f} metres with {wall_height:.1f} metre ceilings.{note}{wish} Doors off "
                f"it to the rooms, art on the walls, a runner rug, a slim console only if it fits, soft wall lights. "
                f"Use only this house palette of materials: {named}. Eye-level shot looking down its length, natural "
                f"light, photorealistic, no people, no text, no watermark, no border.")
    return (f"A professional interior designer's photograph of the {room['name'].lower()} in a {style_words} home. "
            f"The room is {w:.1f} by {d:.1f} metres with {wall_height:.1f} metre ceilings.{note}{wish} "
            f"Real furniture sizes that fit this room, with space to walk round them. Light in layers: soft ambient "
            f"light, task light where you work or eat, one accent lamp. Styled like people live there: art, books, "
            f"cushions, a rug, plants. Nothing random. Use only this house palette of materials: {named}. "
            f"Wide eye-level shot from the doorway, natural daylight, photorealistic, no people, no text, "
            f"no watermark, no border.")


def _post(url, payload, key, timeout, opener=None):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json",
                                          "User-Agent": USER_AGENT})
    try:
        with (opener or urllib.request.urlopen)(req, timeout=timeout) as resp:
            return json.loads(resp.read(40 * 1024 * 1024))
    except urllib.error.HTTPError as exc:
        try:
            words = json.loads(exc.read()).get("error", {}).get("message", "")
        except (ValueError, OSError, AttributeError):
            words = ""
        raise DesignError(f"Gemini said no ({exc.code}{': ' + words[:160] if words else ''}).", 502)
    except (urllib.error.URLError, OSError, ValueError) as exc:
        raise DesignError("I couldn't reach Gemini.", 502) from exc


def image_models(key, opener=None):
    """(flash, pro): the newest Nano Banana models Google lists for this key."""
    try:
        req = urllib.request.Request(GEMINI_API + "/v1beta/models?pageSize=1000",
                                     headers={"x-goog-api-key": key, "User-Agent": USER_AGENT})
        with (opener or urllib.request.urlopen)(req, timeout=15) as resp:
            models = json.loads(resp.read(4 * 1024 * 1024)).get("models") or []
    except (urllib.error.URLError, OSError, ValueError):
        return FLASH_FALLBACK, PRO_FALLBACK

    def version(name):
        return tuple(int(n) for n in re.findall(r"\d+", name)[:3])

    names = [m.get("name", "").split("/")[-1] for m in models
             if "generateContent" in (m.get("supportedGenerationMethods") or [])]
    names = [n for n in names if "image" in n and "imagen" not in n]
    flash = [n for n in names if "flash" in n]
    pro = [n for n in names if "pro" in n]
    best = lambda ns, fb: max(ns, key=lambda n: ("preview" not in n, version(n))) if ns else fb
    return best(flash, FLASH_FALLBACK), best(pro, PRO_FALLBACK)


def kind_of(data):
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png"
    if data[:3] == b"\xff\xd8\xff":
        return "jpg"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp"
    return ""


def make_photo(prompt, key, model, record=None, opener=None):
    """One 4:3 room photo -> (bytes, ext). record(model, usage) counts the cost."""
    if not key:
        raise DesignError("Designing rooms needs your Gemini key (Settings).")
    payload = {"contents": [{"parts": [{"text": prompt}]}],
               "generationConfig": {"responseModalities": ["IMAGE"], "imageConfig": {"aspectRatio": "4:3"}}}
    reply = _post(f"{GEMINI_API}/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent", payload, key,
                  PHOTO_TIMEOUT_S, opener)
    if record:
        record(reply.get("modelVersion") or model, reply.get("usageMetadata"))
    for cand in reply.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            if inline.get("data"):
                data = base64.b64decode(inline["data"])
                ext = kind_of(data)
                if ext and len(data) <= MAX_PHOTO_BYTES:
                    return data, ext
    raise DesignError("Gemini didn't send a picture back for that room. Try again, or change the style words.", 502)



# ---- your own room photos redesigned (Faiek, 2026-11-24: "start from images"): Nano Banana edits the photo, keeping
# the room itself (walls, windows, doors, ceiling, camera angle) and changing what a designer would change.
def restyle_prompt(room_name, style_words, palette, extra=""):
    named = "; ".join(f"{p['name']} ({p['hex']}) for {p['use']}" for p in palette)
    wish = f" The owner asks for: {extra.strip()[:300]}." if extra and extra.strip() else ""
    return (f"Redesign this {str(room_name).lower() or 'room'} as a professional interior designer would, in a "
            f"{style_words} style.{wish} Keep the room itself exactly as it is: the same walls, windows, doors, "
            f"ceiling height, built-in features and the same camera position and angle. Change the furniture, "
            f"wall colour, flooring finish, rugs, curtains, lighting and styling. Real furniture sizes that fit the "
            f"room, with space to walk round them. Light in layers. Styled like people live there, nothing random. "
            f"Use only this palette of materials: {named}. Photorealistic, natural daylight, no people, no text, "
            f"no watermark, no border.")


def restyle_photo(picture, mime, prompt, key, model, record=None, opener=None):
    """Your room photo + the prompt -> (bytes, ext) of the redesigned photo, the same shape as the original."""
    if not key:
        raise DesignError("Redesigning photos needs your Gemini key (Settings).")
    payload = {"contents": [{"parts": [{"inlineData": {"mimeType": mime,
                                                       "data": base64.b64encode(picture).decode("ascii")}},
                                       {"text": prompt}]}],
               "generationConfig": {"responseModalities": ["IMAGE"]}}
    reply = _post(f"{GEMINI_API}/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent", payload, key,
                  PHOTO_TIMEOUT_S, opener)
    if record:
        record(reply.get("modelVersion") or model, reply.get("usageMetadata"))
    for cand in reply.get("candidates") or []:
        for part in (cand.get("content") or {}).get("parts") or []:
            inline = part.get("inlineData") or part.get("inline_data") or {}
            if inline.get("data"):
                data = base64.b64decode(inline["data"])
                ext = kind_of(data)
                if ext and len(data) <= MAX_PHOTO_BYTES:
                    return data, ext
    raise DesignError("Gemini didn't send the redesigned photo back. Try again, or pick another style.", 502)

READ_SCHEMA = {
    "type": "object",
    "properties": {
        "palette": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "hex": {"type": "string"},
            "use": {"type": "string", "enum": list(USES)}}, "required": ["name", "hex", "use"]}},
        "floor": {"type": "object", "properties": {"material": {"type": "string", "enum": list(FLOORS)},
                                                   "hex": {"type": "string"}}, "required": ["material", "hex"]},
        "walls": {"type": "string"},
        "items": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": sorted(KINDS)}, "hex": {"type": "string"}},
            "required": ["kind", "hex"]}},
    },
    "required": ["palette", "floor", "walls", "items"],
}
READ_PROMPT = ("You are an interior designer's assistant. Look at this room photo and say what is in it. "
               "palette: the 5 main colours as named materials (like 'light oak', 'travertine', 'linen', "
               "'smoked walnut', 'matte black'), each with its hex colour and what it is used for. floor: the floor's "
               "material and colour. walls: the wall colour as a hex. items: each piece of furniture you can see, "
               "one entry per piece (six chairs = six entries), only kinds from the list, with its main colour. "
               "Hex colours as #rrggbb. Only what you can see.")


def read_photo(data, ext, key, model=None, record=None, opener=None):
    """What a room photo holds -> {palette, floor, walls, items} (cleaned). A cheap Gemini call."""
    mime = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    model = model or READ_MODEL
    payload = {"contents": [{"parts": [{"inline_data": {"mime_type": mime,
                                                        "data": base64.b64encode(data).decode("ascii")}},
                                       {"text": READ_PROMPT}]}],
               "generationConfig": {"responseMimeType": "application/json", "responseSchema": READ_SCHEMA,
                                    "temperature": 0.2}}
    reply = _post(f"{GEMINI_API}/v1beta/models/{urllib.parse.quote(model, safe='')}:generateContent", payload, key,
                  READ_TIMEOUT_S, opener)
    if record:
        record(reply.get("modelVersion") or model, reply.get("usageMetadata"))
    text = "".join(p.get("text", "") for c in reply.get("candidates") or []
                   for p in (c.get("content") or {}).get("parts") or [])
    return clean_read(text)


def clean_read(text):
    try:
        raw = json.loads(re.sub(r"^```(?:json)?|```$", "", str(text).strip()).strip())
    except ValueError:
        return {"palette": [], "floor": None, "walls": None, "items": []}
    floor = raw.get("floor") if isinstance(raw.get("floor"), dict) else {}
    walls = str(raw.get("walls") or "").strip().lower()
    items = []
    for it in raw.get("items") or []:
        if isinstance(it, dict) and it.get("kind") in KINDS:
            hexv = str(it.get("hex") or "").strip().lower()
            items.append({"kind": it["kind"], "hex": hexv if HEX.match(hexv) else None})
    return {"palette": clean_palette(raw.get("palette"), 6),
            "floor": {"material": floor.get("material") if floor.get("material") in FLOORS else "wood",
                      "hex": floor["hex"].lower()} if HEX.match(str(floor.get("hex") or "")) else None,
            "walls": walls if HEX.match(walls) else None, "items": items[:MAX_ITEMS]}


# ---- the furniture cut out of the room's photo (Faiek, 2026-11-24: "use images instead of the 3D boxes"). Gemini
# marks each piece in the designed photo with its box and an outline (a mask); the walkthrough stands that cut-out
# picture in the room where the piece is placed. Boxes only (no mask) still work: the page feathers the edges.
CUT_MODEL = "gemini-2.5-flash"           # segmentation masks (config `house_cutout_model` overrides)
CUT_KINDS = tuple(k for k in KINDS if k not in ("rug", "pendant", "shower") + RUN_KINDS)
MAX_CUTS = 24
MAX_MASK_BYTES = 400 * 1024
CUT_PROMPT = ("Give the segmentation masks for each piece of furniture, each plant, each floor lamp and each framed "
              "picture in this room photo. Output a JSON list of segmentation masks where each entry contains the 2D "
              "bounding box in the key \"box_2d\", the segmentation mask in the key \"mask\", and the text label in "
              "the key \"label\". Use only these labels: " + ", ".join(CUT_KINDS) + ". One entry per piece (six "
              "chairs = six entries). Leave out anything cut off by the edge of the photo.")


def clean_cuts(text):
    """Gemini's answer -> [{kind, box: [ymin, xmin, ymax, xmax] in 0-1000, mask: PNG data URL or None}]."""
    text = str(text or "").strip()
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text).strip()
    try:
        raw = json.loads(text)
    except ValueError:
        start, end = text.find("["), text.rfind("]")
        try:
            raw = json.loads(text[start:end + 1]) if start >= 0 < end else []
        except ValueError:
            raw = []
    if isinstance(raw, dict):
        raw = raw.get("items") or raw.get("masks") or []
    out = []
    for it in raw if isinstance(raw, list) else []:
        if not isinstance(it, dict):
            continue
        kind = str(it.get("label") or it.get("kind") or "").strip().lower().replace(" ", "_")
        box = it.get("box_2d") or it.get("box")
        if kind not in CUT_KINDS or not isinstance(box, list) or len(box) != 4:
            continue
        try:
            y0, x0, y1, x1 = (max(0, min(1000, int(round(float(v))))) for v in box)
        except (TypeError, ValueError):
            continue
        if y1 - y0 < 15 or x1 - x0 < 15:
            continue
        mask = it.get("mask")
        if isinstance(mask, str) and mask.startswith("data:image/png;base64,") and len(mask) < MAX_MASK_BYTES * 4 // 3:
            try:
                ok = base64.b64decode(mask.split(",", 1)[1], validate=True)[:8] == b"\x89PNG\r\n\x1a\n"
            except ValueError:
                ok = False
            mask = mask if ok else None
        else:
            mask = None
        out.append({"kind": kind, "box": [y0, x0, y1, x1], "mask": mask})
    return out[:MAX_CUTS]


def cut_photo(data, ext, key, model=None, record=None, opener=None):
    """The pieces in a room photo, each with its box and mask, for the walkthrough's cut-outs. One cheap call.
    The mask model (2.5 Flash, thinking off) first; if Google no longer has it, the read model gives boxes only."""
    if not key:
        raise DesignError("Cutting out the furniture needs your Gemini key (Settings).")
    mime = {"png": "image/png", "jpg": "image/jpeg", "webp": "image/webp"}.get(ext, "image/png")
    parts = [{"inline_data": {"mime_type": mime, "data": base64.b64encode(data).decode("ascii")}},
             {"text": CUT_PROMPT}]
    tries = [(model or CUT_MODEL, {"temperature": 0.3, "thinkingConfig": {"thinkingBudget": 0}})]
    if not model:
        tries.append((READ_MODEL, {"temperature": 0.3}))
    error = None
    for name, config in tries:
        try:
            reply = _post(f"{GEMINI_API}/v1beta/models/{urllib.parse.quote(name, safe='')}:generateContent",
                          {"contents": [{"parts": parts}], "generationConfig": config}, key, CUT_TIMEOUT_S, opener)
        except DesignError as exc:
            error = exc
            continue
        if record:
            record(reply.get("modelVersion") or name, reply.get("usageMetadata"))
        text = "".join(p.get("text", "") for c in reply.get("candidates") or []
                       for p in (c.get("content") or {}).get("parts") or [])
        cuts = clean_cuts(text)
        if cuts:
            return cuts
    if error:
        raise error
    return []


def kinds_from_read(room, read):
    """The furniture to place: what the photo shows (only what fits this kind of room), else the room's kit."""
    kit = kit_for(room)
    seen = [i["kind"] for i in (read or {}).get("items") or []]
    w, d = room["x"][1] - room["x"][0], room["y"][1] - room["y"][0]
    if GARAGE_RE.search(room["name"]):           # a garage keeps what the plan draws (the car); the photo adds nothing
        seen = []
    elif PASSAGE_RE.search(room["name"]) or min(w, d) < 1.6:      # a passage: wall pieces only, never a sofa
        seen = [k for k in seen if k in NARROW_KINDS]
        kit = [k for k in kit if k in NARROW_KINDS]
        if not seen:
            return kit, {}
    if not seen:
        return kit, {}
    shown = []
    for k in seen:
        if shown.count(k) < MAX_EACH.get(k, 1):
            shown.append(k)
    for k in ("rug", "pendant", "art"):            # soft pieces the kit would add, if the photo had none
        if k in kit and k not in shown:
            shown.append(k)
    colours = {}
    for i in (read or {}).get("items") or []:
        if i.get("hex") and i["kind"] not in colours:
            colours[i["kind"]] = i["hex"]
    return shown, colours


def floor_of(room, read, palette):
    """{material, hex}: the photo's floor, else the palette's (tiles in wet rooms). A garage is always concrete."""
    if GARAGE_RE.search(room["name"]):
        return {"material": "concrete", "hex": "#a9a59e"}
    if read and read.get("floor"):
        return read["floor"]
    seen = room.get("floor")                         # as the plan draws it: planks, a tile grid...
    if seen == "tile" or seen == "stone":
        return {"material": seen, "hex": pick(palette, "stone", "#d8d2c6")}
    if seen == "carpet":
        return {"material": "carpet", "hex": pick(palette, "fabric", "#cfc4b2")}
    if seen == "concrete":
        return {"material": "concrete", "hex": "#a9a59e"}
    if seen == "wood":
        return {"material": "wood", "hex": pick(palette, "floor", "#c8a57a")}
    if re.search(r"bath|shower|toilet|wc|laundry|scullery|ensuite", room["name"], re.I):
        return {"material": "tile", "hex": pick(palette, "stone", "#d8d2c6")}
    return {"material": "wood", "hex": pick(palette, "floor", "#c8a57a")}


# ---------------------------------------------------------------- a floor plan picture -> plan JSON
# Faiek, 2026-11-23: his plans come as pictures (a PDF printed to PDF is one big JPEG), and a model reading a whole
# page at once guesses where lines are. So: the picture is taken out of the PDF at full size; Gemini, which is made
# to mark where things are in a picture, boxes every space, door, window and piece of furniture and reads the overall
# sizes; plain code turns the boxes into metres, snaps them into one grid and builds the walls from the rooms (no wall
# between rooms that are open to each other). Without a Gemini key, Claude reads the plan straight into walls
# (PLAN_RULES). Either way the plan is a draft: the page's fix tools put right what was misread.
OPENING_KINDS = ("door", "sliding", "garage", "opening", "window")
SWINGS = ("door",)                                  # drawn with a swing on the plan; the rest slide, roll up or are open
FLOOR_KINDS = ("wood", "tile", "carpet", "concrete", "stone", "unknown")
PLAN_MAX = 80.0
OUTSIDE_RE = re.compile(r"patio|yard|garden|stoep|deck|terrace|veranda|verandah|porch|courtyard|balcony|pool|"
                        r"braai|covered entrance|entrance porch|drying", re.I)

PLAN_RULES = """You read a floor plan picture (a drawing, a scan, a photo or a PDF of one) into JSON, for a 3D house.
Work it out step by step in your thinking before you answer:
1. List EVERY space the plan names: living, dining, kitchen, bedrooms, bathrooms, en-suites, passages, garage,
   scullery, laundry, study, store, and the outside ones (patio, covered entrance, yard), with the area written
   beside each (m2), if any.
2. Read the dimension chains along the edges (millimetres on most plans: 12650 = 12.65 m). Turn them into grid lines:
   x positions left to right, y positions bottom to top, each a running sum of the chain. Walls and rooms sit on
   these lines. With no dimensions, take a door as 0.9 m wide, scale from that and say so in "unsure".
3. Place each named space as a rectangle between grid lines, where its label and its walls are. A space is never
   bigger than its walls: if a written area is given, its width x depth must come within about 15% of it; if it
   doesn't, you have the wrong lines, so look again. Rooms never overlap. An open plan (a kitchen open to the
   living/dining room, no wall drawn between them) is two rooms side by side with NO wall between them.
4. Then the walls (only where the plan draws a thick wall), and EVERY door and window you can see. kind: "door" (a
   gap with a quarter-circle swing), "sliding" (a gap with two thin overlapping panels), "garage" (a wide gap in the
   garage's wall, it rolls or lifts up), "opening" (a gap with no door), "window" (thin double or triple lines across
   a gap). Count them per room before you answer: most rooms have one door and at least one window.
5. The furniture the plan draws (beds, sofas, tables, the bath, the toilet, the car...), and each room's floor as
   drawn: planks are "wood", a square grid is "tile".
Answer with ONLY this JSON, no other words:
{"wall_height": 2.6, "walls": [{"id": "w1", "a": [x, y], "b": [x, y], "t": 0.22}],
 "openings": [{"wall": "w1", "from": 1.2, "to": 2.1, "kind": "door", "name": "front door"}],
 "rooms": [{"name": "Living room", "x": [x0, x1], "y": [y0, y1], "area": 39.5, "outside": false, "floor": "wood",
            "note": ""}],
 "items": [{"kind": "sofa", "room": "Living room", "x": 2.1, "y": 3.0, "w": 2.2, "d": 0.9, "rot": 0}],
 "unsure": ""}
- Metres. x runs to the right of the drawing, y runs UP the drawing (so the bottom edge is y = 0). Put the house's
  bottom-left corner at 0, 0.
- Walls are straight segments along their centre lines: outside walls t 0.22, inside walls t 0.11. Join corners
  exactly (the same point for both walls).
- An opening sits on one wall: "from" and "to" are metres along that wall from its "a" end. Name the main entrance
  "front door".
- Rooms are rectangles (for an L-shaped room give its biggest rectangle), named as the plan names them, with "area"
  the area written on the plan (else 0), "outside" true for a patio, yard, garden, stoep or covered entrance.
- items: kind is one of """ + ", ".join(sorted(KINDS) + ["car"]) + """; x, y its centre; w its width across its front,
  d its depth; rot the way its front faces (0 up the drawing, 90 right, 180 down, 270 left). Only what is drawn.
- Never invent rooms, doors, windows or furniture. "unsure": one short sentence on anything you guessed, else "".
- Only the ground floor if there are several."""


def parse_plan(text):
    """Claude's answer -> a checked plan JSON (moved so its corner is 0, 0). Raises DesignError."""
    m = re.search(r"\{.*\}", str(text or ""), re.S)
    if not m:
        raise DesignError("I couldn't read a plan out of that picture.")
    try:
        raw = json.loads(m.group(0))
    except ValueError:
        raise DesignError("I couldn't read a plan out of that picture.")
    return clean_plan(raw, note=True)


def _num(v):
    f = float(v)
    if not math.isfinite(f) or abs(f) > PLAN_MAX:
        raise ValueError
    return f


def clean_plan(raw, note=False, move=True):
    """Any plan JSON (Claude's, Gemini's boxes turned into metres, or the page's edits) -> a checked plan: walls,
    openings on them, rooms, outside spaces, furniture drawn on the plan. With note, what looks wrong is added to
    "unsure". Raises DesignError when there isn't a house in it."""
    if not isinstance(raw, dict):
        raise DesignError("That isn't a plan.")
    walls = []
    for k, w in enumerate(raw.get("walls") or []):
        try:
            a, b = [_num(w["a"][0]), _num(w["a"][1])], [_num(w["b"][0]), _num(w["b"][1])]
            t = min(0.5, max(0.05, _num(w.get("t") or 0.15)))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        if math.hypot(b[0] - a[0], b[1] - a[1]) >= 0.3:
            walls.append({"id": str(w.get("id") or f"w{k + 1}")[:20], "a": a, "b": b, "t": t})
    seen = set()
    for k, w in enumerate(walls):                          # ids must be unique: openings hang off them
        if w["id"] in seen:
            w["id"] = f"w{k + 1}x"
        seen.add(w["id"])
    if len(walls) < 3:
        raise DesignError("That picture didn't give me enough walls to build a house. Try a clearer plan.")
    mx = min(min(w["a"][0], w["b"][0]) for w in walls) if move else 0.0
    my = min(min(w["a"][1], w["b"][1]) for w in walls) if move else 0.0
    for w in walls:
        w["a"] = [round(w["a"][0] - mx, 3), round(w["a"][1] - my, 3)]
        w["b"] = [round(w["b"][0] - mx, 3), round(w["b"][1] - my, 3)]
    by_id = {w["id"]: w for w in walls}
    openings = []
    for o in raw.get("openings") or []:
        w = by_id.get(str(o.get("wall")))
        try:
            f, t = sorted((_num(o["from"]), _num(o["to"])))
        except (KeyError, TypeError, ValueError):
            continue
        if not w or o.get("kind") not in OPENING_KINDS:
            continue
        L = math.hypot(w["b"][0] - w["a"][0], w["b"][1] - w["a"][1])
        f, t = max(0.0, f), min(L, t)
        if t - f >= 0.4:
            one = {"wall": w["id"], "from": round(f, 3), "to": round(t, 3), "kind": o["kind"],
                   "name": str(o.get("name") or "")[:40]}
            if o.get("flip"):
                one["flip"] = True
            openings.append(one)
    rooms = []
    for r in raw.get("rooms") or []:
        try:
            x0, x1 = sorted((_num(r["x"][0]) - mx, _num(r["x"][1]) - mx))
            y0, y1 = sorted((_num(r["y"][0]) - my, _num(r["y"][1]) - my))
        except (KeyError, IndexError, TypeError, ValueError):
            continue
        name = re.sub(r"\s+", " ", str(r.get("name") or "")).strip()[:40]
        if name and x1 - x0 >= 0.8 and y1 - y0 >= 0.8:
            room = {"name": name, "x": [round(x0, 3), round(x1, 3)], "y": [round(y0, 3), round(y1, 3)],
                    "note": str(r.get("note") or "")[:200]}
            try:
                area = _num(r.get("area") or 0)
            except (TypeError, ValueError):
                area = 0
            if area > 0:
                room["area"] = round(area, 2)
            if r.get("outside") is True or (r.get("outside") is None and OUTSIDE_RE.search(name)):
                room["outside"] = True
            if r.get("floor") in FLOOR_KINDS and r.get("floor") != "unknown":
                room["floor"] = r["floor"]
            if r.get("part_of"):
                room["part_of"] = name
            rooms.append(room)
    names = {r["name"] for r in rooms}
    items = []
    for it in raw.get("items") or []:
        try:
            kind = str(it["kind"])
            x, y = _num(it["x"]) - mx, _num(it["y"]) - my
            w, d = _num(it.get("w") or 0), _num(it.get("d") or 0)
            rot = int(round(float(it.get("rot") or 0) / 90.0)) % 4 * 90
        except (KeyError, TypeError, ValueError):
            continue
        if kind in KINDS or kind == "car":
            dw, dd = (1.8, 4.5) if kind == "car" else KINDS[kind][:2]
            one = {"kind": kind, "x": round(x, 3), "y": round(y, 3), "rot": rot,
                   "w": round(min(max(w or dw, dw * 0.5), dw * 1.8), 3),
                   "d": round(min(max(d or dd, dd * 0.5), dd * 1.8), 3)}
            if it.get("room") in names:
                one["room"] = it["room"]
            items.append(one)
    try:
        wh = min(4.5, max(2.2, _num(raw.get("wall_height") or 2.6)))
    except (TypeError, ValueError):
        wh = 2.6
    unsure = str(raw.get("unsure") or "").strip()
    if note:
        off = plan_mismatches([r for r in rooms if not r.get("outside") and not r.get("part_of")])
        if not any(o["kind"] != "window" for o in openings):
            off.insert(0, "no doors were read")
        if not any(o["kind"] == "window" for o in openings):
            off.insert(0, "no windows were read")
        if off:
            unsure = (unsure + " " if unsure else "") + "Check these against the plan: " + "; ".join(off) + "."
    out = {"wall_height": wh, "walls": walls, "openings": openings, "rooms": rooms, "items": items[:120],
           "unsure": unsure[:600], "from_picture": bool(raw.get("from_picture", True))}
    if raw.get("read_by"):
        out["read_by"] = str(raw["read_by"])[:40]
    return out


# ---- the picture inside a PDF ("Microsoft Print to PDF" makes one big JPEG of the page): stdlib only
def _png(width, height, colours, rows):
    """A PNG from rows that already start with their filter byte (PNG predictors), colours 1 or 3, 8 bits."""
    import zlib

    def chunk(kind, data):
        return (len(data).to_bytes(4, "big") + kind + data
                + (zlib.crc32(kind + data) & 0xffffffff).to_bytes(4, "big"))
    head = width.to_bytes(4, "big") + height.to_bytes(4, "big") + bytes([8, 2 if colours == 3 else 0, 0, 0, 0])
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", head) + chunk(b"IDAT", zlib.compress(rows, 6)) + chunk(b"IEND", b"")


def pdf_picture(data):
    """The biggest picture in a PDF as (bytes, media type), or None (a drawing made of lines, or nothing usable).
    JPEGs come out as they are; plain 8-bit grey/RGB Flate pictures become a PNG."""
    import zlib
    best = None
    for m in re.finditer(rb"<<((?:[^<>]|<<(?:[^<>]|<<[^<>]*>>)*>>)*)>>\s*stream\r?\n", data):
        head = m.group(1)
        if not re.search(rb"/Subtype\s*/Image", head):
            continue
        try:
            width = int(re.search(rb"/Width\s+(\d+)", head).group(1))
            height = int(re.search(rb"/Height\s+(\d+)", head).group(1))
        except AttributeError:
            continue
        length = re.search(rb"/Length\s+(\d+)(\s+\d+\s+R)?", head)
        start = m.end()
        if length and not length.group(2):
            end = start + int(length.group(1))
        else:
            end = data.find(b"endstream", start)
            if end < 0:
                continue
            end = data.rfind(b"\n", start, end) if data[end - 1:end] == b"\n" else end
        if best and width * height <= best[0]:
            continue
        stream = data[start:end]
        filters = re.findall(rb"/(DCTDecode|FlateDecode|JPXDecode|CCITTFaxDecode|LZWDecode|RunLengthDecode)", head)
        try:
            if filters == [b"DCTDecode"] and stream[:2] == b"\xff\xd8":
                best = (width * height, stream.rstrip(b"\r\n"), "image/jpeg")
            elif filters == [b"FlateDecode"] and re.search(rb"/BitsPerComponent\s+8", head):
                colours = 3 if re.search(rb"/ColorSpace\s*/DeviceRGB", head) else (
                    1 if re.search(rb"/ColorSpace\s*/DeviceGray", head) else 0)
                if not colours:
                    continue
                raw = zlib.decompress(stream)
                pred = re.search(rb"/Predictor\s+(\d+)", head)
                row = width * colours
                if pred and int(pred.group(1)) >= 10:
                    if len(raw) < (row + 1) * height:
                        continue
                    rows = raw[:(row + 1) * height]
                else:
                    if len(raw) < row * height:
                        continue
                    rows = b"".join(b"\x00" + raw[k * row:(k + 1) * row] for k in range(height))
                best = (width * height, _png(width, height, colours, rows), "image/png")
        except (zlib.error, ValueError):
            continue
    return (best[1], best[2]) if best else None


def picture_size(data):
    """(width, height) of a JPEG or PNG from its header, else None."""
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return int.from_bytes(data[16:20], "big"), int.from_bytes(data[20:24], "big")
    if data[:2] == b"\xff\xd8":
        k = 2
        while k + 9 < len(data):
            if data[k] != 0xFF:
                k += 1
                continue
            marker = data[k + 1]
            if marker in (0xD8, 0x01) or 0xD0 <= marker <= 0xD7:
                k += 2
                continue
            size = int.from_bytes(data[k + 2:k + 4], "big")
            if 0xC0 <= marker <= 0xCF and marker not in (0xC4, 0xC8, 0xCC):
                return int.from_bytes(data[k + 7:k + 9], "big"), int.from_bytes(data[k + 5:k + 7], "big")
            k += 2 + size
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP" and data[12:16] == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    return None


# ---- Gemini marks where everything is; code does the measuring
LOCATE_MODEL = "gemini-pro-latest"                  # config `house_plan_model`; Flash is tried if this one isn't there
LOCATE_FALLBACK = "gemini-flash-latest"
LOCATE_TIMEOUT_S = 150
BOX = {"type": "array", "items": {"type": "integer"}}
LOCATE_SCHEMA = {
    "type": "object",
    "properties": {
        "outline": BOX,
        "width_mm": {"type": "number"}, "depth_mm": {"type": "number"},
        "spaces": {"type": "array", "items": {"type": "object", "properties": {
            "name": {"type": "string"}, "area_m2": {"type": "number"}, "box": BOX,
            "outside": {"type": "boolean"}, "floor": {"type": "string", "enum": list(FLOOR_KINDS)},
            "open_to": {"type": "array", "items": {"type": "string"}}},
            "required": ["name", "box", "outside", "floor"]}},
        "openings": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": list(OPENING_KINDS)}, "box": BOX,
            "front": {"type": "boolean"}}, "required": ["kind", "box"]}},
        "furniture": {"type": "array", "items": {"type": "object", "properties": {
            "kind": {"type": "string", "enum": sorted(KINDS) + ["car"]}, "box": BOX},
            "required": ["kind", "box"]}},
        "unsure": {"type": "string"},
    },
    "required": ["outline", "spaces", "openings", "furniture"],
}
LOCATE_PROMPT = """This is an architect's floor plan of a house. Mark where everything is, as boxes [ymin, xmin, ymax, xmax]
on a 0-1000 scale of the whole picture.
- outline: the house's outer walls (the house, garage and covered spaces against it), NOT the fence, the plot or the
  site boundary. width_mm and depth_mm: that outline's overall outside size read from the dimension chains (the
  longest dimension along the top or bottom, and along the left or right side), in millimetres; 0 if none is written.
- spaces: EVERY named space, inside and outside, each with its name as written, the area written beside it (else 0),
  its box from wall to wall (the inner faces of its walls; never past them), outside true for a patio, yard, garden,
  stoep or covered entrance, its floor as drawn (planks = wood, a square grid = tile, else unknown), and open_to: the
  names of spaces it opens into with NO wall drawn between them (an open-plan kitchen and living room). A space that
  isn't a rectangle (an L-shape, or an entrance area that belongs to the living room) is given as two or more
  entries with the SAME name, one per rectangle; give the area only on the biggest.
- openings: every door and window, each boxed tightly round the gap in the wall only (not the door's swing arc).
  kind: door (a swing), sliding, garage (the garage's wide door), opening (a gap with no door), window (thin lines
  across the gap). front true for the main entrance.
- furniture: every piece the plan draws (beds, sofas, chairs, tables, the bath, the toilet, basins, the shower, the
  kitchen units, the car), each boxed tightly.
Only what is drawn. "unsure": one short sentence on anything you couldn't read."""


def locate_plan(picture, mime, key, model=None, record=None, opener=None):
    """Gemini boxes the plan's spaces, openings and furniture -> its answer (dict). Raises DesignError."""
    payload = {"contents": [{"parts": [{"inline_data": {"mime_type": mime,
                                                        "data": base64.b64encode(picture).decode("ascii")}},
                                       {"text": LOCATE_PROMPT}]}],
               "generationConfig": {"responseMimeType": "application/json", "responseSchema": LOCATE_SCHEMA,
                                    "temperature": 0.1, "mediaResolution": "MEDIA_RESOLUTION_HIGH"}}
    last = None
    for name in dict.fromkeys([model or LOCATE_MODEL, LOCATE_FALLBACK]):
        try:
            reply = _post(f"{GEMINI_API}/v1beta/models/{urllib.parse.quote(name, safe='')}:generateContent",
                          payload, key, LOCATE_TIMEOUT_S, opener)
        except DesignError as exc:
            last = exc
            if "(404" in exc.message or "(400" in exc.message:
                continue
            raise
        if record:
            record(reply.get("modelVersion") or name, reply.get("usageMetadata"))
        text = "".join(p.get("text", "") for c in reply.get("candidates") or []
                       for p in (c.get("content") or {}).get("parts") or [] if not p.get("thought"))
        try:
            found = json.loads(re.sub(r"^```(?:json)?|```$", "", text.strip()).strip())
        except ValueError:
            raise DesignError("Gemini's reading of the plan didn't come back whole. Try again.", 502)
        if not isinstance(found, dict):
            raise DesignError("Gemini's reading of the plan didn't come back whole. Try again.", 502)
        found["read_by"] = reply.get("modelVersion") or name
        return found
    raise last or DesignError("I couldn't reach Gemini.", 502)


def _box(v, img_w, img_h):
    """[ymin, xmin, ymax, xmax] on 0-1000 -> (x0, y0, x1, y1) in pixels, top-down; None if it isn't a box."""
    try:
        y0, x0, y1, x1 = (float(n) for n in v)
    except (TypeError, ValueError):
        return None
    if not all(math.isfinite(n) for n in (x0, y0, x1, y1)):
        return None
    x0, x1 = sorted((x0, x1))
    y0, y1 = sorted((y0, y1))
    if x1 - x0 < 1 and y1 - y0 < 1:
        return None
    return (x0 / 1000 * img_w, y0 / 1000 * img_h, x1 / 1000 * img_w, y1 / 1000 * img_h)


def _cluster(values, tol):
    """Each value -> the mean of the values within tol of it (in a chain), so near-lines become one line."""
    order = sorted(values)
    groups, cur = [], [order[0]] if order else []
    for v in order[1:]:
        if v - cur[-1] <= tol:
            cur.append(v)
        else:
            groups.append(cur)
            cur = [v]
    if cur:
        groups.append(cur)
    out = {}
    for g in groups:
        mean = sum(g) / len(g)
        for v in g:
            out[v] = mean
    return out


SNAP_M = 0.25
OUTER_T, INNER_T = 0.22, 0.11


def plan_from_boxes(found, img_w, img_h):
    """Gemini's boxes -> a plan JSON in metres: rooms snapped into one grid, walls built round them (none between
    rooms open to each other), doors and windows set on the wall they sit in, furniture in its room."""
    outline = _box(found.get("outline"), img_w, img_h)
    spaces = []
    for s in found.get("spaces") or []:
        b = _box(s.get("box"), img_w, img_h) if isinstance(s, dict) else None
        name = re.sub(r"\s+", " ", str((s or {}).get("name") or "")).strip()[:40] if isinstance(s, dict) else ""
        if b and name:
            spaces.append((name, b, s))
    if not spaces:
        raise DesignError("Gemini didn't find any rooms on that plan. Try a clearer picture of just the plan.")
    inside = [b for _, b, s in spaces if not s.get("outside")]
    if not outline:
        outline = (min(b[0] for b in inside), min(b[1] for b in inside), max(b[2] for b in inside),
                   max(b[3] for b in inside))
    ow, oh = outline[2] - outline[0], outline[3] - outline[1]
    notes = []
    try:
        wmm, dmm = float(found.get("width_mm") or 0), float(found.get("depth_mm") or 0)
    except (TypeError, ValueError):
        wmm = dmm = 0
    sx = wmm / 1000 / ow if 2000 < wmm < 80000 and ow > 10 else 0
    sy = dmm / 1000 / oh if 2000 < dmm < 80000 and oh > 10 else 0
    if sx and sy and not 0.8 < sx / sy < 1.25:            # the two sizes disagree: trust the one nearer square pixels
        sx = sy = sx if abs(1 - (wmm / dmm) / (ow / oh)) < abs(1 - (dmm / wmm) / (oh / ow)) else sy
        notes.append("the plan's two overall sizes didn't agree, so I used one of them")
    if not sx and not sy:                                  # no sizes written: a door is 0.9 m
        widths = []
        for o in found.get("openings") or []:
            b = _box((o or {}).get("box"), img_w, img_h)
            if b and (o or {}).get("kind") == "door":
                widths.append(max(b[2] - b[0], b[3] - b[1]))
        if not widths:
            raise DesignError("That plan has no sizes written on it and no doors to measure by.")
        widths.sort()
        sx = sy = 0.9 / widths[len(widths) // 2]
        notes.append("no overall sizes were written, so I measured from the doors (0.9 m each)")
    sx, sy = sx or sy, sy or sx

    def mx(px):
        return (px - outline[0]) * sx

    def my(py):
        return (outline[3] - py) * sy

    W, D = ow * sx, oh * sy
    rects = []
    for name, b, s in spaces:
        x0, x1 = sorted((mx(b[0]), mx(b[2])))
        y0, y1 = sorted((my(b[3]), my(b[1])))
        rects.append({"name": name, "x": [x0, x1], "y": [y0, y1], "s": s})
    xs = [v for r in rects for v in r["x"]] + [0.0, W]
    ys = [v for r in rects for v in r["y"]] + [0.0, D]
    cx, cy = _cluster(xs, SNAP_M), _cluster(ys, SNAP_M)
    for edge, cl in ((0.0, cx), (W, cx)):                 # the outline wins over a room's nearby edge
        for v, m in list(cl.items()):
            if m == cl[edge] and v != edge:
                cl[v] = edge
        cl[edge] = edge
    for edge, cl in ((0.0, cy), (D, cy)):
        for v, m in list(cl.items()):
            if m == cl[edge] and v != edge:
                cl[v] = edge
        cl[edge] = edge
    rooms, names = [], set()
    for r in rects:
        x0, x1 = round(cx[r["x"][0]], 3), round(cx[r["x"][1]], 3)
        y0, y1 = round(cy[r["y"][0]], 3), round(cy[r["y"][1]], 3)
        if x1 - x0 < 0.8 or y1 - y0 < 0.8:
            continue
        name, s = r["name"], r["s"]
        room = {"name": name, "x": [x0, x1], "y": [y0, y1], "note": ""}
        if name in names:                          # a second rectangle of an L-shaped space
            room["part_of"] = name
        names.add(name)
        try:
            area = float(s.get("area_m2") or 0)
        except (TypeError, ValueError):
            area = 0
        if 0 < area < 2000:
            room["area"] = round(area, 2)
        if s.get("outside") or OUTSIDE_RE.search(name):
            room["outside"] = True
        if s.get("floor") in FLOOR_KINDS and s.get("floor") != "unknown":
            room["floor"] = s["floor"]
        room["_open"] = {str(n).strip().lower() for n in s.get("open_to") or []}
        rooms.append(room)
    walls = walls_from_rooms(rooms, W, D)
    openings = []
    for o in found.get("openings") or []:
        b = _box((o or {}).get("box"), img_w, img_h)
        kind = (o or {}).get("kind")
        if not b or kind not in OPENING_KINDS:
            continue
        x0, x1 = sorted((mx(b[0]), mx(b[2])))
        y0, y1 = sorted((my(b[3]), my(b[1])))
        one = opening_on_wall(walls, x0, y0, x1, y1, kind)
        if one:
            if o.get("front"):
                one["name"] = "front door"
            openings.append(one)
    items = []
    for f in found.get("furniture") or []:
        b = _box((f or {}).get("box"), img_w, img_h)
        kind = (f or {}).get("kind")
        if not b or not (kind in KINDS or kind == "car"):
            continue
        x0, x1 = sorted((mx(b[0]), mx(b[2])))
        y0, y1 = sorted((my(b[3]), my(b[1])))
        x, y = (x0 + x1) / 2, (y0 + y1) / 2
        room = next((r for r in rooms if r["x"][0] - 0.05 <= x <= r["x"][1] + 0.05
                     and r["y"][0] - 0.05 <= y <= r["y"][1] + 0.05), None)
        items.append(item_from_box(kind, x0, y0, x1, y1, room))
    for r in rooms:                                    # the biggest rectangle carries the name; the others are parts
        if r.get("part_of"):
            main = next(m for m in rooms if m["name"] == r["name"] and not m.get("part_of"))
            if (r["x"][1] - r["x"][0]) * (r["y"][1] - r["y"][0]) > (main["x"][1] - main["x"][0]) * (main["y"][1] - main["y"][0]):
                r.pop("part_of")
                main["part_of"] = main["name"]
                for k in ("area",):
                    if k in main:
                        r[k] = main.pop(k)
    open_pairs = sorted({tuple(sorted((a["name"], b["name"]))) for a in rooms for b in rooms
                         if a is not b and not a.get("outside") and not b.get("outside") and a["name"] != b["name"]
                         and (b["name"].lower() in a["_open"] or any(n and n in b["name"].lower() for n in a["_open"]))})
    for r in rooms:
        r.pop("_open", None)
    # everything moved so the lowest corner (an outside yard, say) is 0, 0
    lx = min([r["x"][0] for r in rooms] + [min(w["a"][0], w["b"][0]) for w in walls])
    ly = min([r["y"][0] for r in rooms] + [min(w["a"][1], w["b"][1]) for w in walls])
    for r in rooms:
        r["x"] = [round(v - lx, 3) for v in r["x"]]
        r["y"] = [round(v - ly, 3) for v in r["y"]]
    for w in walls:
        w["a"] = [round(w["a"][0] - lx, 3), round(w["a"][1] - ly, 3)]
        w["b"] = [round(w["b"][0] - lx, 3), round(w["b"][1] - ly, 3)]
    for it in items:
        it["x"], it["y"] = round(it["x"] - lx, 3), round(it["y"] - ly, 3)
    unsure = str(found.get("unsure") or "").strip()
    if notes:
        unsure = (unsure + " " if unsure else "") + "; ".join(notes).capitalize() + "."
    return {"wall_height": 2.6, "walls": walls, "openings": openings, "rooms": rooms, "items": items,
            "unsure": unsure, "from_picture": True, "read_by": found.get("read_by") or "gemini",
            "open": [list(p) for p in open_pairs]}


# ---- both readers on one plan (Faiek, 2026-11-24): Claude measures the rooms from the dimension lines (it found the
# passage Gemini missed), Gemini says where doors, windows, furniture and outside spaces are drawn (and which rooms are
# open plan). Gemini's plan is fitted onto Claude's by the rooms both found; then free code puts it all together.
def room_key(name):
    return re.sub(r"[^a-z]+", " ", re.sub(r"\d+", "", str(name or "").lower())).replace(" room", " ").strip()


def _match_rooms(claude_rooms, gemini_rooms):
    """Pairs (claude room, gemini room) for the rooms both readers found, by name."""
    pairs, used = [], set()
    for g in gemini_rooms:
        kg = room_key(g["name"])
        best = next((c for c in claude_rooms if id(c) not in used and room_key(c["name"]) == kg), None)
        if not best and kg:
            best = next((c for c in claude_rooms if id(c) not in used and room_key(c["name"])
                         and (kg in room_key(c["name"]) or room_key(c["name"]) in kg)), None)
        if best:
            used.add(id(best))
            pairs.append((best, g))
    return pairs


def _fit(points):
    """Least squares c = a * g + b over [(g, c)], one refit without points more than 0.6 m off. None if it can't."""
    for _ in range(2):
        n = len(points)
        if n < 2:
            return None
        mg = sum(g for g, _ in points) / n
        mc = sum(c for _, c in points) / n
        var = sum((g - mg) ** 2 for g, _ in points)
        if var < 1.0:
            return None
        a = sum((g - mg) * (c - mc) for g, c in points) / var
        b = mc - a * mg
        if not 0.7 < a < 1.4:
            return None
        keep = [(g, c) for g, c in points if abs(a * g + b - c) <= 0.6]
        if len(keep) == n:
            break
        points = keep
    return a, b


def _bbox_fit(cr, gr):
    def span(rs, k):
        return min(r[k][0] for r in rs), max(r[k][1] for r in rs)
    out = []
    for k in ("x", "y"):
        (g0, g1), (c0, c1) = span(gr, k), span(cr, k)
        if g1 - g0 < 1:
            return None
        a = (c1 - c0) / (g1 - g0)
        out.append((a, c0 - a * g0))
    return out


def _cut_open(walls, A, B):
    """Take the walls off the edge rooms A and B share (they are open to each other)."""
    edges = []
    for k, other in (("x", "y"), ("y", "x")):
        for p, q in ((A[k][1], B[k][0]), (B[k][1], A[k][0])):
            if abs(p - q) < 0.35:
                o0, o1 = max(A[other][0], B[other][0]), min(A[other][1], B[other][1])
                if o1 - o0 > 0.5:
                    edges.append((k, (p + q) / 2, o0, o1))
    for k, c, o0, o1 in edges:
        out = []
        for w in walls:
            (ax, ay), (bx, by) = w["a"], w["b"]
            vertical = abs(ax - bx) < 1e-6
            if (k == "x" and vertical and abs(ax - c) < 0.3) or (k == "y" and abs(ay - by) < 1e-6 and abs(ay - c) < 0.3):
                i = 1 if k == "x" else 0                   # the coordinate along the wall
                lo, hi = sorted((w["a"][i], w["b"][i]))
                for n, (s0, s1) in enumerate(((lo, min(hi, o0)), (max(lo, o1), hi))):
                    if s1 - s0 >= 0.3:
                        a, b = list(w["a"]), list(w["b"])
                        a[i], b[i] = s0, s1
                        out.append({"id": f"{w['id']}{'ab'[n]}"[:20], "a": a, "b": b, "t": w["t"]})
            else:
                out.append(w)
        walls = out
    return walls


def _opening_box(o, walls):
    w = next((w for w in walls if w["id"] == o.get("wall")), None)
    if not w:
        return None
    (ax, ay), (bx, by) = w["a"], w["b"]
    L = math.hypot(bx - ax, by - ay) or 1
    ux, uy = (bx - ax) / L, (by - ay) / L
    p = (ax + ux * o["from"], ay + uy * o["from"])
    q = (ax + ux * o["to"], ay + uy * o["to"])
    return p, q


def merge_reads(claude, gemini):
    """Claude's checked plan + Gemini's (plan_from_boxes) -> one plan: Claude's rooms, sizes and walls; Gemini's open
    plan, doors and windows (Claude's kept where Gemini has none near), furniture, floors and outside spaces."""
    cr = [r for r in claude["rooms"] if not r.get("outside") and not r.get("part_of")]
    gr = [r for r in gemini["rooms"] if not r.get("outside") and not r.get("part_of")]
    if not cr or not gr:
        return claude, {"matched": 0, "claude_only": [r["name"] for r in cr]}
    pairs = _match_rooms(cr, gr)
    fx = _fit([(g["x"][i], c["x"][i]) for c, g in pairs for i in (0, 1)])
    fy = _fit([(g["y"][i], c["y"][i]) for c, g in pairs for i in (0, 1)])
    notes = []
    if not fx or not fy:
        fx, fy = _bbox_fit(cr, gr) or ((1.0, 0.0), (1.0, 0.0))
        notes.append("Gemini's doors and furniture were lined up by the house's outline only")

    def tx(v):
        return fx[0] * v + fx[1]

    def ty(v):
        return fy[0] * v + fy[1]

    rooms = [dict(r) for r in claude["rooms"]]
    by_name = {}
    for c, g in pairs:
        one = next(r for r in rooms if r["name"] == c["name"] and not r.get("part_of"))
        by_name[g["name"]] = one
        if not one.get("floor") and g.get("floor"):
            one["floor"] = g["floor"]
    claude_outside = {room_key(r["name"]) for r in rooms if r.get("outside")}
    for g in gemini["rooms"]:
        if g.get("outside") and room_key(g["name"]) not in claude_outside:
            rooms.append({**g, "x": sorted((round(tx(g["x"][0]), 3), round(tx(g["x"][1]), 3))),
                          "y": sorted((round(ty(g["y"][0]), 3), round(ty(g["y"][1]), 3)))})
    walls = [dict(w) for w in claude["walls"]]
    for a, b in gemini.get("open") or []:
        A, B = by_name.get(a), by_name.get(b)
        if A and B:
            walls = _cut_open(walls, A, B)
    # doors and windows: Gemini's (it tells a garage or sliding door apart), then Claude's where Gemini has none near
    placed, centres = [], []
    for o in gemini["openings"]:
        seg = _opening_box(o, gemini["walls"])
        if not seg:
            continue
        (px, py), (qx, qy) = seg
        x0, x1 = sorted((tx(px), tx(qx)))
        y0, y1 = sorted((ty(py), ty(qy)))
        one = opening_on_wall(walls, x0 - 0.05, y0 - 0.05, x1 + 0.05, y1 + 0.05, o["kind"])
        if one:
            one["name"] = o.get("name") or ""
            if o.get("flip"):
                one["flip"] = True
            placed.append(one)
            centres.append(((x0 + x1) / 2, (y0 + y1) / 2))
    for o in claude["openings"]:
        seg = _opening_box(o, claude["walls"])
        if not seg:
            continue
        (px, py), (qx, qy) = seg
        cx, cy = (px + qx) / 2, (py + qy) / 2
        if any(math.hypot(cx - x, cy - y) < 0.9 for x, y in centres):
            continue
        one = opening_on_wall(walls, min(px, qx) - 0.05, min(py, qy) - 0.05, max(px, qx) + 0.05, max(py, qy) + 0.05,
                              o["kind"])
        if one:
            one["name"] = o.get("name") or ""
            placed.append(one)
    if not any(o.get("name") == "front door" for o in placed):
        front = next((o for o in claude["openings"] if "front" in (o.get("name") or "").lower()), None)
        seg = front and _opening_box(front, claude["walls"])
        if seg:
            cx, cy = (seg[0][0] + seg[1][0]) / 2, (seg[0][1] + seg[1][1]) / 2
            def gap(o):
                seg2 = _opening_box(o, walls)
                return math.dist((cx, cy), ((seg2[0][0] + seg2[1][0]) / 2, (seg2[0][1] + seg2[1][1]) / 2)) if seg2 else 99
            near = min((o for o in placed if o["kind"] != "window"), key=gap, default=None)
            if near:
                near["name"] = "front door"
    # furniture: where Gemini saw it drawn, in Claude's room it now stands in
    inside = [r for r in rooms if not r.get("outside")]
    items = []
    for it in gemini.get("items") or []:
        x, y = tx(it["x"]), ty(it["y"])
        bw, bd = (it["w"], it["d"]) if it["rot"] in (0, 180) else (it["d"], it["w"])
        bw, bd = bw * fx[0], bd * fy[0]
        room = next((r for r in inside if r["x"][0] - 0.05 <= x <= r["x"][1] + 0.05
                     and r["y"][0] - 0.05 <= y <= r["y"][1] + 0.05), None)
        if not room:
            room = next((r for r in rooms if r["x"][0] <= x <= r["x"][1] and r["y"][0] <= y <= r["y"][1]), None)
        if not room:
            continue
        one = item_from_box(it["kind"], x - bw / 2, y - bd / 2, x + bw / 2, y + bd / 2, room)
        one["room"] = room.get("part_of") or room["name"]
        items.append(one)
    # the lowest corner (an outside yard, say) at 0, 0
    lx = min([r["x"][0] for r in rooms] + [min(w["a"][0], w["b"][0]) for w in walls])
    ly = min([r["y"][0] for r in rooms] + [min(w["a"][1], w["b"][1]) for w in walls])
    for r in rooms:
        r["x"] = [round(v - lx, 3) for v in r["x"]]
        r["y"] = [round(v - ly, 3) for v in r["y"]]
    for w in walls:
        w["a"] = [round(w["a"][0] - lx, 3), round(w["a"][1] - ly, 3)]
        w["b"] = [round(w["b"][0] - lx, 3), round(w["b"][1] - ly, 3)]
    for it in items:
        it["x"], it["y"] = round(it["x"] - lx, 3), round(it["y"] - ly, 3)
    missed = [c["name"] for c in cr if c not in [p[0] for p in pairs]]
    unsure = str(claude.get("unsure") or "")
    if notes:
        unsure = (unsure + " " if unsure else "") + "; ".join(notes) + "."
    out = {"wall_height": claude.get("wall_height", 2.6), "walls": walls, "openings": placed, "rooms": rooms,
           "items": items, "unsure": unsure, "from_picture": True,
           "read_by": f"{claude.get('read_by') or 'claude'} + {gemini.get('read_by') or 'gemini'}"}
    return out, {"matched": len(pairs), "claude_only": missed}


def walls_from_rooms(rooms, W, D):
    """Walls along every room edge: outside walls where a room meets the outside (or an outside space), inside walls
    between two rooms, none between rooms open to each other. Collinear pieces of one kind are joined."""
    inside = [r for r in rooms if not r.get("outside")]
    eps = 0.05

    def at(x, y):
        return next((r for r in inside if r["x"][0] < x < r["x"][1] and r["y"][0] < y < r["y"][1]), None)

    def open_pair(a, b):
        return (b["name"].lower() in a.get("_open", ()) or a["name"].lower() in b.get("_open", ())
                or any(n and n in b["name"].lower() for n in a.get("_open", ()))
                or any(n and n in a["name"].lower() for n in b.get("_open", ())))

    lines = {}                                      # (axis, position) -> [breakpoints]
    for r in inside:
        for y in r["y"]:
            lines.setdefault(("h", y), set()).update(r["x"])
        for x in r["x"]:
            lines.setdefault(("v", x), set()).update(r["y"])
    walls = []
    for (axis, c), cuts in sorted(lines.items()):
        pts = sorted(cuts | {p for (ax2, c2), cs in lines.items() if ax2 != axis for p in [c2]
                             if min(cuts) < p < max(cuts)})
        run = None
        for a, b in zip(pts, pts[1:]):
            if b - a < 1e-3:
                continue
            m = (a + b) / 2
            one, two = (at(m, c - eps), at(m, c + eps)) if axis == "h" else (at(c - eps, m), at(c + eps, m))
            if one is two or (one and two and (one["name"] == two["name"] or open_pair(one, two))):
                t = None
            else:
                t = INNER_T if (one and two) else OUTER_T
            if run and t == run[2] and abs(run[1] - a) < 1e-3:
                run[1] = b
            else:
                if run and run[2]:
                    walls.append((axis, c, run))
                run = [a, b, t]
        if run and run[2]:
            walls.append((axis, c, run))
    out = []
    for k, (axis, c, (a, b, t)) in enumerate(walls):
        p, q = ([a, c], [b, c]) if axis == "h" else ([c, a], [c, b])
        out.append({"id": f"w{k + 1}", "a": [round(p[0], 3), round(p[1], 3)], "b": [round(q[0], 3), round(q[1], 3)],
                    "t": t})
    return out


def opening_on_wall(walls, x0, y0, x1, y1, kind):
    """A box round a gap in a wall -> {wall, from, to, kind} on the wall it sits in, or None."""
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    best = None
    for w in walls:
        (ax, ay), (bx, by) = w["a"], w["b"]
        horizontal = abs(ay - by) < 1e-6
        if horizontal:
            lo, hi, along0, along1, gap = min(ax, bx), max(ax, bx), x0, x1, abs(cy - ay)
            inside = y0 - 0.25 <= ay <= y1 + 0.25
        else:
            lo, hi, along0, along1, gap = min(ay, by), max(ay, by), y0, y1, abs(cx - ax)
            inside = x0 - 0.25 <= ax <= x1 + 0.25
        a0, a1 = max(lo, along0), min(hi, along1)
        if not inside or a1 - a0 < 0.3:
            continue
        across = (y1 - y0) if horizontal else (x1 - x0)
        score = gap + max(0.0, across - (along1 - along0)) * 0.5      # a gap runs along its wall
        if not best or score < best[0]:
            best = (score, w, a0, a1)
    if not best:
        return None
    _, w, a0, a1 = best
    (ax, ay), (bx, by) = w["a"], w["b"]
    horizontal = abs(ay - by) < 1e-6
    start = ax if horizontal else ay
    sign = 1 if ((bx - ax) if horizontal else (by - ay)) > 0 else -1
    f, t = sorted(((a0 - start) * sign, (a1 - start) * sign))
    least = {"garage": 2.0, "window": 0.4}.get(kind, 0.6)
    if t - f < least:
        mid = (f + t) / 2
        f, t = mid - least / 2, mid + least / 2
    L = math.hypot(bx - ax, by - ay)
    f, t = max(0.0, f), min(L, t)
    if t - f < 0.4:
        return None
    return {"wall": w["id"], "from": round(f, 3), "to": round(t, 3), "kind": kind, "name": ""}


def item_from_box(kind, x0, y0, x1, y1, room):
    """A piece of furniture boxed on the plan -> {kind, x, y, w, d, rot, room}: turned to match its box, its back to
    the nearer wall of its room."""
    bw, bd = x1 - x0, y1 - y0
    dw, dd = (1.8, 4.5) if kind == "car" else KINDS[kind][:2]
    across = (dw >= dd) == (bw >= bd)              # its width runs left-right on the plan
    x, y = (x0 + x1) / 2, (y0 + y1) / 2
    if room:
        rx0, rx1, ry0, ry1 = room["x"][0], room["x"][1], room["y"][0], room["y"][1]
    else:
        rx0, rx1, ry0, ry1 = x0 - 1, x1 + 1, y0 - 1, y1 + 1
    if across:
        rot = 0 if (y - ry0) <= (ry1 - y) else 180      # back to the nearer of the bottom or top wall
        w, d = bw, bd
    else:
        rot = 90 if (x - rx0) <= (rx1 - x) else 270
        w, d = bd, bw
    out = {"kind": kind, "x": round(x, 3), "y": round(y, 3), "rot": rot, "w": round(w, 3), "d": round(d, 3)}
    if room:
        out["room"] = room["name"]
    return out


def plan_items(plan, room):
    """The furniture the plan draws in this room, for the engine (no colours yet)."""
    out = []
    for it in (plan or {}).get("items") or []:
        if it.get("room") == room["name"] or (not it.get("room") and room["x"][0] <= it["x"] <= room["x"][1]
                                              and room["y"][0] <= it["y"] <= room["y"][1]):
            out.append(it)
    return out


def items_layout(room, items, doors, palette, colours=None):
    """Furniture drawn on the plan, coloured from the palette, and the same checks a designed room gets."""
    lay = Layout(room, doors)
    colours = colours or {}
    for it in items:
        kind = it["kind"]
        if kind == "car":
            lay.items.append({"kind": "car", "label": "Car", "x": it["x"], "y": it["y"], "w": it["w"], "d": it["d"],
                              "h": 1.45, "rot": it["rot"], "c": pick(palette, "accent", "#7d8a96"),
                              "box": footprint(it["x"], it["y"], it["w"], it["d"], it["rot"]), "zone": None})
            continue
        lay.add(kind, it["x"], it["y"], it["rot"], it["w"], it["d"], colours.get(kind) or default_colour(kind, palette),
                pick(palette, "accent", "#8fa3a0"))
    results = checks(lay)
    results.insert(0, {"ok": True, "text": f"{room['name']}: furniture placed as the plan draws it"})
    return [{k: v for k, v in i.items() if k not in ("box", "zone", "ring")} for i in lay.items], results


def default_colour(kind, palette):
    fabric, wood = pick(palette, "fabric", "#cfc4b2"), pick(palette, "wood", "#8a6a4a")
    accent, metal = pick(palette, "accent", "#8fa3a0"), pick(palette, "metal", "#2a2a2a")
    stone = pick(palette, "stone", "#d8d2c6")
    return {"sofa": fabric, "armchair": accent, "coffee_table": wood, "rug": fabric, "tv_unit": wood,
            "sideboard": wood, "bookshelf": wood, "dining_table": wood, "dining_chair": wood, "bed_double": fabric,
            "bed_single": fabric, "bedside": wood, "wardrobe": wood, "desk": wood, "desk_chair": metal,
            "counter": wood, "sink_unit": wood, "hob_unit": wood, "fridge": "#d9d9d6", "island": wood,
            "toilet": "#f4f4f2", "basin": stone, "shower": stone, "bath": "#f4f4f2", "washer": "#f1f1ef",
            "plant": "#4f6b3e", "floor_lamp": metal, "pendant": metal, "art": accent}.get(kind, wood)


AREA_SLACK = 0.25


def plan_mismatches(rooms):
    """Rooms whose box is far from the area written on the plan, and rooms that overlap: the read's own proof."""
    off = []
    for r in rooms:
        box = (r["x"][1] - r["x"][0]) * (r["y"][1] - r["y"][0])
        if r.get("area") and abs(box - r["area"]) > AREA_SLACK * r["area"]:
            off.append(f"{r['name']} is {box:.1f} m\u00b2, the plan says {r['area']:g} m\u00b2")
    for k, a in enumerate(rooms):
        for b in rooms[k + 1:]:
            w = min(a["x"][1], b["x"][1]) - max(a["x"][0], b["x"][0])
            h = min(a["y"][1], b["y"][1]) - max(a["y"][0], b["y"][0])
            if w > 0.3 and h > 0.3:
                off.append(f"{a['name']} and {b['name']} overlap")
    return off[:6]


# ---------------------------------------------------------------- checks
def selftest():
    fails = []

    def check(ok, what):
        if not ok:
            fails.append(what)

    living = {"name": "Living room", "x": [0, 5.5], "y": [0, 4.5], "note": ""}
    kitchen = {"name": "Kitchen", "x": [5.5, 9.5], "y": [0, 4.5], "note": ""}
    bath = {"name": "Bathroom", "x": [0, 2.4], "y": [4.5, 7.0], "note": ""}
    bed = {"name": "Main bedroom", "x": [2.4, 6.4], "y": [4.5, 8.5], "note": ""}
    rooms = [living, kitchen, bath, bed]
    pal = palette_of(DEFAULT_STYLE)
    check(len(pal) == 6 and all(HEX.match(p["hex"]) for p in pal), "style palette")
    check(clean_palette([{"name": "x", "hex": "red", "use": "walls"}, {"name": "Oak", "hex": "#AABBCC", "use": "?"}])
          == [{"name": "Oak", "hex": "#aabbcc", "use": "accent"}], "clean_palette")
    check("sofa" in kit_for(living) and "toilet" in kit_for(bath) and kit_for({"name": "Garage", "x": [0, 6],
                                                                            "y": [0, 6]}) == [], "kits")
    check("bed_single" in kit_for({"name": "Bedroom 3", "x": [0, 3], "y": [0, 3]}), "small bedroom single bed")
    doors = room_doors(living, rooms, None, {"x": 2.7, "y": 0})
    check(len(doors) >= 2, f"doors from neighbours ({doors})")
    doors = [(2.7, 0, 0.9), (5.5, 1.0, 0.9)]
    for room in rooms:
        d = room_doors(room, rooms, None, {"x": 2.7, "y": 0})
        items, results = design_room(room, kinds_from_read(room, None)[0], d, pal)
        check(items, f"{room['name']} has furniture")
        boxes = [footprint(i["x"], i["y"], i["w"], i["d"], i["rot"]) for i in items if i["kind"] not in SOFT]
        check(all(inside(b, room, 0.01) for b in boxes), f"{room['name']}: everything inside")
        check(not any(overlap(a, b) for k, a in enumerate(boxes) for b in boxes[k + 1:]), f"{room['name']}: no overlap")
        check(results and results[0]["ok"], f"{room['name']}: routes ({results})")
    items, _ = design_room(living, kit_for(living), doors, pal)
    sofa = next((i for i in items if i["kind"] == "sofa"), None)
    tv = next((i for i in items if i["kind"] == "tv_unit"), None)
    check(sofa and tv and (sofa["rot"] + 180) % 360 == tv["rot"], "TV faces the sofa")
    items, results = design_room(kitchen, ["counter", "sink_unit", "hob_unit", "fridge"],
                                 room_doors(kitchen, rooms), pal)
    check(any("work triangle" in r["text"] for r in results), "kitchen triangle checked")
    # a blocked room: a wardrobe across the only route must not be accepted
    narrow = {"name": "Passage room", "x": [0, 4], "y": [0, 1.6]}
    lay = Layout(narrow, [(0, 0.8, 0.9), (4, 0.8, 0.9)])
    lay.add("wardrobe", 2, 0.8, 0, 1.6, 1.6)
    check(not routes_ok(lay)[0], "a blocked route is caught")
    read = clean_read(json.dumps({"palette": [{"name": "Travertine", "hex": "#D8C9B1", "use": "stone"}],
                                  "floor": {"material": "stone", "hex": "#cccccc"}, "walls": "#eeeeee",
                                  "items": [{"kind": "sofa", "hex": "#123456"}, {"kind": "spaceship", "hex": "#000000"},
                                            {"kind": "plant", "hex": "bad"}]}))
    check(read["palette"][0]["hex"] == "#d8c9b1" and [i["kind"] for i in read["items"]] == ["sofa", "plant"]
          and read["floor"]["material"] == "stone", "clean_read")
    kinds, colours = kinds_from_read(living, read)
    check(kinds[:2] == ["sofa", "plant"] and colours.get("sofa") == "#123456" and "rug" in kinds, "kinds_from_read")
    check(clean_read("not json")["items"] == [], "clean_read refuses junk")
    prompt = photo_prompt(living, STYLES[DEFAULT_STYLE]["words"], pal, 2.6, "a reading nook")
    check("5.5 by 4.5" in prompt and "Travertine" in prompt and "reading nook" in prompt and "Nothing random" in prompt,
          "photo prompt")
    plan = parse_plan('Here: {"walls": [{"id": "a", "a": [1, 1], "b": [11, 1]}, {"id": "b", "a": [11, 1], "b": [11, 9]},'
                      '{"id": "c", "a": [11, 9], "b": [1, 9]}, {"id": "d", "a": [1, 9], "b": [1, 1]}],'
                      '"openings": [{"wall": "a", "from": 4, "to": 4.9, "kind": "door", "name": "front door"},'
                      '{"wall": "zz", "from": 1, "to": 2, "kind": "door"}, {"wall": "b", "from": 2, "to": 2.1, "kind": "window"}],'
                      '"rooms": [{"name": "Lounge", "x": [1, 6], "y": [1, 9]}, {"name": "", "x": [6, 11], "y": [1, 9]}],'
                      '"wall_height": 9}')
    check(plan["walls"][0]["a"] == [0, 0] and len(plan["openings"]) == 1 and len(plan["rooms"]) == 1
          and plan["rooms"][0]["x"] == [0, 5] and plan["wall_height"] == 4.5, "parse_plan")
    check(plan_doors(plan) and abs(plan_doors(plan)[0][0] - 4.45) < 0.01, "plan doors")
    # a picture plan: Gemini's boxes -> walls round the rooms, none between open-plan rooms, doors on their walls
    found = {"outline": [0, 0, 1000, 1000], "width_mm": 10000, "depth_mm": 8000,
             "spaces": [{"name": "Living", "area_m2": 30, "box": [0, 0, 1000, 500], "outside": False, "floor": "wood",
                         "open_to": ["Kitchen"]},
                        {"name": "Kitchen", "area_m2": 20, "box": [0, 500, 500, 1000], "outside": False, "floor": "tile"},
                        {"name": "Garage", "area_m2": 20, "box": [500, 500, 1000, 1000], "outside": False,
                         "floor": "concrete"}],
             "openings": [{"kind": "garage", "box": [995, 600, 1000, 900]}, {"kind": "door", "box": [995, 200, 1000, 300],
                                                                           "front": True},
                          {"kind": "window", "box": [0, 100, 5, 400]}],
             "furniture": [{"kind": "car", "box": [550, 650, 950, 850]}, {"kind": "sofa", "box": [100, 50, 160, 400]}]}
    plan = clean_plan(plan_from_boxes(found, 2000, 1600), note=True, move=False)
    inner = [w for w in plan["walls"] if w["t"] == INNER_T]
    check(plan["rooms"][0]["x"] == [0.0, 5.0] and plan["rooms"][2]["y"] == [0.0, 4.0], f"boxes to metres ({plan['rooms']})")
    across = [w for w in inner if abs(w["a"][0] - 5) < 0.01 and abs(w["b"][0] - 5) < 0.01]
    check(across and all(max(w["a"][1], w["b"][1]) <= 4.01 for w in across) and
          any(abs(w["a"][1] - 4) < 0.01 and abs(w["b"][1] - 4) < 0.01 for w in inner),
          f"open plan has no wall, the garage has one ({inner})")
    kinds = sorted(o["kind"] for o in plan["openings"])
    check(kinds == ["door", "garage", "window"] and any(o["name"] == "front door" for o in plan["openings"]),
          f"doors on their walls ({plan['openings']})")
    car = next((i for i in plan["items"] if i["kind"] == "car"), {})
    check(car.get("room") == "Garage" and car.get("rot") in (0, 180) and 3 < car.get("d", 0) < 4.5,
          f"furniture drawn on the plan ({plan['items']})")
    check(plan["rooms"][1].get("floor") == "tile", "floors as drawn")
    # both readers: Claude's rooms (with the passage Gemini missed) + Gemini's open plan, sliding door and bed
    claude = clean_plan({"walls": [{"a": [0, 0], "b": [10, 0], "t": 0.22}, {"a": [10, 0], "b": [10, 8], "t": 0.22},
                                   {"a": [10, 8], "b": [0, 8], "t": 0.22}, {"a": [0, 8], "b": [0, 0], "t": 0.22},
                                   {"id": "k", "a": [0, 4], "b": [5, 4], "t": 0.11},
                                   {"id": "p1", "a": [5, 0], "b": [5, 8], "t": 0.11},
                                   {"id": "p2", "a": [6.2, 0], "b": [6.2, 8], "t": 0.11}],
                         "openings": [{"wall": "p1", "from": 5, "to": 5.9, "kind": "door"},
                                      {"wall": "p2", "from": 2, "to": 2.9, "kind": "door"}],
                         "rooms": [{"name": "Living", "x": [0, 5], "y": [4, 8]}, {"name": "Kitchen", "x": [0, 5], "y": [0, 4]},
                                   {"name": "Passage", "x": [5, 6.2], "y": [0, 8]},
                                   {"name": "Bedroom 1", "x": [6.2, 10], "y": [0, 8]}]})
    found = {"outline": [0, 0, 1000, 1000], "width_mm": 10000, "depth_mm": 8000,
             "spaces": [{"name": "Living", "box": [0, 0, 500, 500], "open_to": ["Kitchen"]},
                        {"name": "Kitchen", "box": [500, 0, 1000, 500], "floor": "tile"},
                        {"name": "Bedroom", "box": [0, 620, 1000, 1000], "floor": "wood"},
                        {"name": "Patio", "box": [0, 0, 1000, 1000], "outside": True}],
             "openings": [{"kind": "sliding", "box": [0, 100, 5, 300]}],
             "furniture": [{"kind": "bed_double", "box": [300, 700, 700, 900]}]}
    gem = plan_from_boxes(found, 1000, 800)
    merged, how = merge_reads(claude, gem)
    merged = clean_plan(merged, note=True, move=False)
    names = [r["name"] for r in merged["rooms"]]
    check("Passage" in names and how["matched"] == 3, f"Claude's rooms kept, Gemini's matched ({names}, {how})")
    check(not any(abs(w["a"][1] - w["b"][1]) < 1e-6 and 0.1 < w["a"][1] < 7.9 and min(w["a"][0], w["b"][0]) < 4.9
                  for w in merged["walls"]), f"no wall between the open-plan kitchen and living ({merged['walls']})")
    kinds = sorted(o["kind"] for o in merged["openings"])
    check(kinds == ["door", "door", "sliding"], f"Gemini's sliding door and Claude's two doors ({merged['openings']})")
    bed = next((i for i in merged["items"] if i["kind"] == "bed_double"), {})
    check(bed.get("room") == "Bedroom 1" and 7.4 < bed["x"] < 8.6, f"Gemini's bed in Claude's bedroom ({merged['items']})")
    check(next(r for r in merged["rooms"] if r["name"] == "Kitchen").get("floor") == "tile", "Gemini's floors")
    check(any(r.get("outside") for r in merged["rooms"]), "Gemini's outside spaces")
    jpeg = b"\xff\xd8\xff\xc0\x00\x11\x08\x00\x20\x00\x30\x03" + b"\x00" * 20 + b"\xff\xd9"
    pdf = (b"%PDF-1.7\n4 0 obj\n<< /Type /XObject /Subtype /Image /Width 48 /Height 32 /Filter /DCTDecode "
           b"/Length " + str(len(jpeg)).encode() + b" >>\nstream\n" + jpeg + b"\nendstream\nendobj\n")
    got = pdf_picture(pdf)
    check(got and got[0] == jpeg and picture_size(got[0]) == (48, 32), "the JPEG inside a printed PDF")
    import zlib
    grey = (b"<< /Subtype /Image /Width 2 /Height 2 /ColorSpace /DeviceGray /BitsPerComponent 8 /Filter /FlateDecode "
            b">>\nstream\n" + zlib.compress(b"\x00\xff\xff\x00") + b"\nendstream")
    got = pdf_picture(b"%PDF-1.4\n" + grey)
    check(got and got[1] == "image/png" and picture_size(got[0]) == (2, 2), "a Flate picture becomes a PNG")
    check(pdf_picture(b"%PDF-1.4\n1 0 obj << /Type /Page >> endobj") is None, "a PDF of lines has no picture")
    off = plan_mismatches([{"name": "Bedroom 1", "x": [0, 4.55], "y": [0, 5], "area": 12.38},
                           {"name": "Bedroom 2", "x": [0, 3.7], "y": [5, 8], "area": 11.04},
                           {"name": "En-suite", "x": [2, 4], "y": [7, 9], "area": 4.1}])
    check(len(off) == 2 and "Bedroom 1" in off[0] and "overlap" in off[1], f"plan_mismatches ({off})")
    try:
        parse_plan('{"walls": []}')
        fails.append("parse_plan refuses an empty plan")
    except DesignError:
        pass

    class Fake:
        def __init__(self, body):
            self.body = body

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def read(self, n=-1):
            return self.body
    png = b"\x89PNG\r\n\x1a\n" + b"\x00" * 40
    reply = json.dumps({"candidates": [{"content": {"parts": [{"inlineData": {"data": base64.b64encode(png).decode()}}]}}],
                        "usageMetadata": {"promptTokenCount": 10}, "modelVersion": "gemini-2.5-flash-image"}).encode()
    seen = []
    data, ext = make_photo("x", "k", "gemini-2.5-flash-image", lambda m, u: seen.append(m),
                           opener=lambda req, timeout: Fake(reply))
    check(data == png and ext == "png" and seen == ["gemini-2.5-flash-image"], "make_photo with a stand-in")
    # the cut-outs: the mask model gone (404), the read model's boxes still used
    asked = []

    def cutter(req, timeout):
        model = urllib.parse.unquote(req.full_url.split("/models/")[1].split(":")[0])
        asked.append(model)
        if model == CUT_MODEL:
            raise urllib.error.HTTPError(req.full_url, 404, "gone", {}, None)
        text = "```json\n" + json.dumps([{"box_2d": [500, 100, 900, 700], "label": "Dining chair"},
                                          {"box_2d": [0, 0, 1000, 1000], "label": "car"}]) + "\n```"
        return Fake(json.dumps({"candidates": [{"content": {"parts": [{"text": text}]}}]}).encode())
    cuts = cut_photo(png, "png", "k", opener=cutter)
    check(asked == [CUT_MODEL, READ_MODEL] and cuts == [{"kind": "dining_chair", "box": [500, 100, 900, 700],
                                                         "mask": None}], f"cut_photo falls back to boxes ({cuts})")
    mask = "data:image/png;base64," + base64.b64encode(png).decode()
    check(clean_cuts(json.dumps({"items": [{"box_2d": [10, 10, 500, 400], "label": "plant", "mask": mask},
                                           {"box_2d": [10, 10, 500, 400], "label": "sofa", "mask": "data:image/png;base64,AAAA"}]}))
          == [{"kind": "plant", "box": [10, 10, 500, 400], "mask": mask},
              {"kind": "sofa", "box": [10, 10, 500, 400], "mask": None}], "clean_cuts keeps only real PNG masks")
    return fails


if __name__ == "__main__":
    problems = selftest()
    print("housedesign: all checks pass" if not problems else "housedesign FAILED:\n  " + "\n  ".join(problems))
    sys.exit(1 if problems else 0)
