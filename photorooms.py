"""Designed Living: a house started from photos of its rooms (standard library only; Faiek, 2026-11-24).

No plan and no 3D: each photo you upload is a room. Nano Banana redesigns the photo in the room's style, keeping the
room itself (housedesign.restyle_photo), a cheap Gemini call reads the new photo back into a palette and furniture
(housedesign.read_photo), and the mood board PDF puts before and after side by side. The house is an ordinary house
folder (houseplan.py) with state["kind"] == "photos"; its rooms are {name, source} (the source photo in model/).
"""
import re
import time
from pathlib import Path

import housedesign
import houseplan
from houseplan import HouseError

KIND = "photos"
MAX_PHOTOS = houseplan.MAX_ROOMS


def is_photos(state):
    return state.get("kind") == KIND


def _name_from(file_name):
    stem = re.sub(r"[_\-.]+", " ", Path(file_name).stem)
    stem = re.sub(r"\b(img|dsc|photo|pxl|image)\s*\d*\b", " ", stem, flags=re.I)
    stem = re.sub(r"\d{6,}", " ", stem)
    stem = re.sub(r"\s+", " ", stem).strip()
    return stem[:1].upper() + stem[1:] if stem else ""


def sync(files_root, house_id):
    """The rooms follow the photos in model/: a new photo becomes a room (named from its file), a gone one goes."""
    path = houseplan.house_dir(files_root, house_id)
    state = houseplan.read_state(path)
    if not is_photos(state):
        raise HouseError("This house wasn't started from photos.")
    photos = [p.name for p in houseplan.model_files(path) if p.suffix.lower() in houseplan.PICTURE_TYPES]
    rooms = [r for r in state.get("rooms") or [] if r.get("source") in photos]
    have = {r["source"] for r in rooms}
    used = {r["name"] for r in rooms}
    for file in photos:
        if file in have or len(rooms) >= MAX_PHOTOS:
            continue
        name, n = _name_from(file) or f"Room {len(rooms) + 1}", 2
        base = name
        while name in used:
            name, n = f"{base} {n}", n + 1
        used.add(name)
        rooms.append({"name": name, "source": file})
    state["rooms"] = rooms
    houseplan.save_state(path, state)
    return state


def rename(files_root, house_id, names):
    """{source file: new room name}; the room's design moves with it."""
    path = houseplan.house_dir(files_root, house_id)
    state = houseplan.read_state(path)
    d = houseplan.design_of(state)
    taken = set()
    for r in state.get("rooms") or []:
        new = re.sub(r"\s+", " ", str(names.get(r["source"], r["name"]) or "")).strip()[:40] or r["name"]
        if new in taken:
            raise HouseError(f"Two rooms can't both be called {new}.")
        taken.add(new)
        if new != r["name"] and r["name"] in d["rooms"]:
            d["rooms"][new] = d["rooms"].pop(r["name"])
        r["name"] = new
    houseplan.save_state(path, state)
    return state


def source(files_root, house_id, room_name):
    """(bytes, media type) of the photo you uploaded for a room."""
    path = houseplan.house_dir(files_root, house_id)
    state = houseplan.read_state(path)
    room = next((r for r in state.get("rooms") or [] if r.get("name") == room_name), None)
    target = path / houseplan.MODEL_DIR / str((room or {}).get("source") or "")
    if not room or not target.is_file() or target.parent != path / houseplan.MODEL_DIR:
        raise HouseError("That room has no photo.", 404)
    return target.read_bytes(), houseplan.PICTURE_TYPES.get(target.suffix.lower(), "image/jpeg")


def store(files_root, house_id, room_name, data, ext, read, model):
    """The redesigned photo and what was read from it (furniture is never placed: there is no plan)."""
    path = houseplan.house_dir(files_root, house_id)
    state = houseplan.read_state(path)
    d = houseplan.design_of(state)
    folder = path / houseplan.DESIGN_DIR
    for old in folder.glob(f"{houseplan.folder_name(room_name) or 'room'}.*") if folder.is_dir() else []:
        old.unlink()
    target = houseplan.photo_path(path, room_name, ext)
    target.parent.mkdir(exist_ok=True)
    houseplan.write_atomic(target, data)
    rd = d["rooms"].setdefault(room_name, {})
    rd.update({"photo": target.name, "model": model, "read": read, "made": time.strftime("%Y-%m-%d %H:%M"),
               "floor": (read or {}).get("floor"),
               "walls": (read or {}).get("walls") or housedesign.pick(houseplan.room_style(d, room_name)[1],
                                                                     "walls", "#f1ede5"),
               "items": [{"kind": i["kind"], "label": i["kind"]} for i in (read or {}).get("items") or []]})
    houseplan.save_state(path, state)


# ---------------------------------------------------------------- the mood board: before and after
def moodboard_pdf(files_root, house_id):
    path = houseplan.house_dir(files_root, house_id)
    state = houseplan.read_state(path)
    d = houseplan.design_of(state)
    rooms = [r for r in state.get("rooms") or [] if (d["rooms"].get(r["name"]) or {}).get("photo")]
    if not rooms:
        raise HouseError("Redesign at least one room first, then make the mood board.")
    PW, PH = houseplan.MOOD_PAGE
    M = 40
    title = state.get("title") or path.name
    pages = []
    cover = houseplan._Sheet()
    if state.get("brand"):
        cover.text(M, PH - M - 4, state["brand"].upper(), 9, "F2", 0.45, 360)
    cover.text(M, PH - M - 40, title, 26, "F2", 0.08, 700)
    y = PH - M - 62
    if state.get("subtitle"):
        y = cover.wrap(M, y, state["subtitle"], 10.5, 700, "F3", 0.35, 3) - 4
    cover.text(M, y - 6, "Mood board", 13, "F2", 0.2)
    cover.text(M, y - 24, f"House style: {housedesign.STYLES[d['style']]['name']}", 10, "F1", 0.3, 700)
    y -= 24
    if d.get("wish"):
        y = cover.wrap(M, y - 14, f"The owner asked for: {d['wish']}", 9, 700, "F3", 0.4, 2) + 9
    cover.text(M, y - 26, "House palette", 9, "F2", 0.45)
    y = houseplan._swatches(cover, M, y - 34, d["palette"], 700)
    cover.text(M, y - 18, f"{len(rooms)} room(s): " + ", ".join(r["name"] for r in rooms), 9, "F1", 0.35, 760)
    pages.append(cover)
    for r in rooms:
        rd = d["rooms"][r["name"]]
        sheet = houseplan._Sheet()
        own = rd.get("style") if rd.get("style") in housedesign.STYLES else d["style"]
        sheet.text(M, PH - M - 20, r["name"], 20, "F2", 0.08, 520)
        sheet.text(M, PH - M - 38, housedesign.STYLES[own]["name"], 9.5, "F1", 0.4, 520)
        after = houseplan._pdf_image((path / houseplan.DESIGN_DIR / rd["photo"]).read_bytes())
        try:
            before = houseplan._pdf_image(source(files_root, house_id, r["name"])[0])
        except HouseError:
            before = None
        big_w, big_h = 520, PH - 2 * M - 70
        if after:
            iw, ih, obj = after
            k = min(big_w / iw, big_h / ih)
            sheet.image(obj, M, M + 10 + (big_h - ih * k), iw * k, ih * k)
        x, cw = M + big_w + 24, PW - M - big_w - 24 - M
        y = PH - M - 62
        if before:
            iw, ih, obj = before
            k = min(cw / iw, 150 / ih)
            sheet.text(x, y, "Before", 9, "F2", 0.45)
            sheet.image(obj, x, y - 8 - ih * k, iw * k, ih * k)
            y -= 8 + ih * k + 18
        read = rd.get("read") or {}
        sheet.text(x, y, "Palette", 9, "F2", 0.45)
        y = houseplan._swatches(sheet, x, y - 8, (read.get("palette") or houseplan.room_style(d, r["name"])[1])[:6],
                                cw, 8.5)
        pieces = houseplan._furniture_list(rd.get("items"))
        if pieces:
            y -= 8
            sheet.text(x, y, "In the room", 9, "F2", 0.45)
            y -= 13
            for p in pieces:
                if y < M + 30:
                    break
                sheet.text(x, y, f"- {p}", 8.5, "F1", 0.2, cw)
                y -= 11
        pages.append(sheet)
    for n, sheet in enumerate(pages, 1):
        sheet.text(M, 20, f"{title}  |  mood board  |  page {n} of {len(pages)}", 7.5, "F1", 0.5, PW - 2 * M)
    return houseplan._mood_file(pages, f"{title} mood board")


def save_moodboard(files_root, house_id):
    path = houseplan.house_dir(files_root, house_id)
    data = moodboard_pdf(files_root, house_id)
    target = houseplan.moodboard_path(path, houseplan.read_state(path))
    houseplan.write_atomic(target, data)
    return {"file": target.name, "path": str(target), "kb": len(data) // 1024}


def view(files_root, house_id):
    """What the house page needs for a photos house."""
    path = houseplan.house_dir(files_root, house_id)
    state = houseplan.read_state(path)
    d = houseplan.design_of(dict(state))
    rooms = []
    for r in state.get("rooms") or []:
        rd = d["rooms"].get(r["name"]) or {}
        rooms.append({"name": r["name"], "source": r["source"],
                      "photo": bool(rd.get("photo") and (path / houseplan.DESIGN_DIR / rd["photo"]).exists()),
                      "style": rd.get("style") or "", "palette": (rd.get("read") or {}).get("palette") or [],
                      "items": houseplan._furniture_list(rd.get("items")), "model": rd.get("model") or "",
                      "made": rd.get("made") or ""})
    return {"rooms": rooms}


def selftest(scratch):
    """Offline: a photos house, two photos, names, a stand-in redesign, the before/after mood board."""
    import base64
    png = base64.b64decode("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8/5+hHgAHggJ/PchI7wAAAABJRU5ErkJggg==")
    hid = houseplan.create(scratch, "Photo house")
    path = houseplan.house_dir(scratch, hid)
    state = houseplan.read_state(path)
    state["kind"] = KIND
    houseplan.save_state(path, state)
    houseplan.add_file(scratch, hid, "IMG_20261124_living-room.png", png)
    houseplan.add_file(scratch, hid, "kitchen.png", png)
    state = sync(scratch, hid)
    names = sorted(r["name"] for r in state["rooms"])
    assert names == ["Kitchen", "Living room"], names
    rename(scratch, hid, {"kitchen.png": "Open kitchen"})
    read = housedesign.clean_read('{"palette": [{"name": "Oak", "hex": "#aa8855", "use": "floor"}], '
                                  '"items": [{"kind": "sofa", "hex": "#777777"}]}')
    store(scratch, hid, "Open kitchen", png, "png", read, "flash")
    v = view(scratch, hid)
    assert any(r["name"] == "Open kitchen" and r["photo"] for r in v["rooms"]), v
    pdf = moodboard_pdf(scratch, hid)
    assert pdf.startswith(b"%PDF-") and b"/Count 2" in pdf, pdf[:200]
    return ["a house from two photos: rooms named from the files, renamed, redesigned (stand-in), mood board"]
