"""Print: a note as a PDF, made here with the standard library only (no PDF library, nothing to install).

The page is A4 with the PDF's own built-in fonts (Helvetica, its bold and oblique, and Courier for code), so nothing
is embedded and every reader shows it the same. Those fonts know Windows' Latin letters (cp1252): accents, curly
quotes and dashes print, anything else (emoji, Arabic, Chinese) prints as "?". The note's Markdown is kept as
print: headings, bullets and numbered lists, **bold**, *italic*, `code`, code blocks, tables (in Courier, so the
columns line up) and quotes. Every page has the title and "page n of m" at the bottom.

A locked PDF (the red star's notes) is encrypted the standard way, AES-256 (PDF 2.0, security handler revision 6),
so any reader asks for its password. The AES itself is Windows' own (CNG, bcrypt.dll through ctypes), never a
cipher written here, and it is checked against published test vectors before a file is made. No AES, no locked
PDF: it says so instead of writing a weaker one.
"""

import datetime
import hashlib
import re
import secrets
import sys
import unicodedata
import zlib

A4 = (595.28, 841.89)
MARGIN = 56                  # points (about 2 cm)
FOOTER_Y = 30
BODY_SIZE = 10.5
LEADING = 1.38               # line height as a multiple of the font size
HEADING_SIZES = {1: 16, 2: 14, 3: 12.5, 4: 11.5, 5: 11, 6: 11}
TITLE_SIZE = 20
CODE_SIZE = 9
MAX_PAGES = 400
MIN_PASSWORD = 8
PRODUCER = "Designed Living"

# Character widths (1/1000 of the font size) for cp1252 bytes 32-255, from the fonts' own Adobe metrics.
_HELV = [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556, 556,
         556, 556, 556, 556, 278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667,
         556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556, 333, 556,
         556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722,
         500, 500, 500, 334, 260, 334, 584, 0, 556, 0, 222, 556, 333, 1000, 556, 556, 333, 1000, 667, 333, 1000, 0,
         611, 0, 0, 222, 222, 333, 333, 350, 556, 1000, 333, 1000, 500, 333, 944, 0, 500, 667, 278, 333, 556, 556, 556,
         556, 260, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333, 333, 556, 537, 278, 333, 333, 365,
         556, 834, 834, 834, 611, 667, 667, 667, 667, 667, 667, 1000, 722, 667, 667, 667, 667, 278, 278, 278, 278, 722,
         722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667, 667, 611, 556, 556, 556, 556, 556, 556, 889,
         500, 556, 556, 556, 556, 278, 278, 278, 278, 556, 556, 556, 556, 556, 556, 556, 584, 611, 556, 556, 556, 556,
         500, 556, 500]
_HELV_BOLD = [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278, 556, 556, 556, 556, 556,
              556, 556, 556, 556, 556, 333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278,
              556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584,
              556, 333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556,
              333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584, 0, 556, 0, 278, 556, 500, 1000, 556, 556, 333,
              1000, 667, 333, 1000, 0, 611, 0, 0, 278, 278, 500, 500, 350, 556, 1000, 333, 1000, 556, 333, 944, 0, 500,
              667, 278, 333, 556, 556, 556, 556, 280, 556, 333, 737, 370, 556, 584, 333, 737, 333, 400, 584, 333, 333,
              333, 611, 556, 278, 333, 333, 365, 556, 834, 834, 834, 611, 722, 722, 722, 722, 722, 722, 1000, 722, 667,
              667, 667, 667, 278, 278, 278, 278, 722, 722, 778, 778, 778, 778, 778, 584, 778, 722, 722, 722, 722, 667,
              667, 611, 556, 556, 556, 556, 556, 556, 889, 556, 556, 556, 556, 556, 278, 278, 278, 278, 611, 611, 611,
              611, 611, 611, 611, 584, 611, 611, 611, 611, 611, 556, 611, 556]
# name in the page -> (base font, widths); oblique has Helvetica's widths, Courier is 600 throughout
FONTS = {"F1": ("Helvetica", _HELV), "F2": ("Helvetica-Bold", _HELV_BOLD), "F3": ("Helvetica-Oblique", _HELV),
         "F4": ("Courier", None)}
REGULAR, BOLD, ITALIC, MONO = "F1", "F2", "F3", "F4"

FRONTMATTER_RE = re.compile(r"\A---\s*\n.*?\n---\s*\n", re.S)
WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]")
INLINE_RE = re.compile(r"`([^`]+)`|\*\*(.+?)\*\*|__(.+?)__|(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])"
                       r"|(?<![\w_])_(?!\s)(.+?)(?<!\s)_(?![\w_])")
LIST_RE = re.compile(r"^(\s*)([-*+]|\d{1,3}[.)])\s+(.*)$")
TASK_RE = re.compile(r"^\[([ xX])\]\s+")
RULE_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")
TABLE_RULE_RE = re.compile(r"^\s*\|?[\s:|-]*-{3,}[\s:|-]*\|?\s*$")


class PrintError(Exception):
    """A print that can't be done. `message` is short enough to be spoken."""

    def __init__(self, message):
        super().__init__(message)
        self.message = message


# ---------------------------------------------------------------- text

def encode(text):
    """Text -> the bytes the built-in fonts print (cp1252); what they don't have becomes "?"."""
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\t", "    ").replace(" ", " ").replace("−", "-").replace("→", "->")
    out = bytearray()
    for ch in text:
        try:
            b = ch.encode("cp1252")
        except UnicodeEncodeError:
            b = b"?"
        if b[0] < 32 or b[0] == 127 or b in (b"\x81", b"\x8d", b"\x8f", b"\x90", b"\x9d"):
            b = b"?"
        out += b
    return bytes(out)


def width(data, font, size):
    """The printed width of cp1252 bytes, in points."""
    widths = FONTS[font][1]
    if widths is None:
        return len(data) * 600 * size / 1000
    return sum(widths[b - 32] for b in data) * size / 1000


def pdf_string(data):
    return b"(" + data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def clean_links(text):
    text = WIKILINK_RE.sub(lambda m: (m.group(2) or m.group(1)).strip(), text)
    text = re.sub(r"!\[([^\]]*)\]\([^)]*\)", lambda m: f"[picture: {m.group(1)}]" if m.group(1) else "[picture]", text)

    def link(m):
        label, url = m.group(1), m.group(2).strip()
        return label if not url or url == label or url.startswith("#") else f"{label} ({url})"
    return re.sub(r"\[([^\]]+)\]\(([^)\s]*)[^)]*\)", link, text)


def spans(text, base=REGULAR):
    """Inline Markdown -> [(font, text)]. Bold, italic and code; the markers themselves are not printed."""
    text = clean_links(text)
    out, at = [], 0
    for m in INLINE_RE.finditer(text):
        if m.start() > at:
            out.append((base, text[at:m.start()]))
        code, bold, bold2, ital, ital2 = m.groups()
        if code is not None:
            out.append((MONO, code))
        elif bold is not None or bold2 is not None:
            out.append((BOLD, bold if bold is not None else bold2))
        else:
            out.append((BOLD if base == BOLD else ITALIC, ital if ital is not None else ital2))
        at = m.end()
    if at < len(text):
        out.append((base, text[at:]))
    return [(f, t.replace("\\*", "*").replace("\\_", "_")) for f, t in out if t]


# ---------------------------------------------------------------- Markdown -> blocks

def blocks(markdown, title=""):
    """The note's Markdown as printable blocks: (kind, data). A first heading that only repeats the title is
    dropped (the title is printed above it anyway)."""
    text = FRONTMATTER_RE.sub("", markdown.replace("\r\n", "\n").replace("\r", "\n"))
    lines = text.split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    if lines and re.match(r"^#\s", lines[0]) and _norm(lines[0][2:]) == _norm(title):
        lines.pop(0)
    out, para, i = [], [], 0

    def flush():
        if para:
            out.append(("p", " ".join(s.strip() for s in para)))
            para.clear()
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```") or stripped.startswith("~~~"):
            flush()
            fence, code = stripped[:3], []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith(fence):
                code.append(lines[i].rstrip())
                i += 1
            out.append(("code", code))
            i += 1
            continue
        if not stripped:
            flush()
            i += 1
            continue
        heading = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", stripped)
        if heading:
            flush()
            out.append(("h", (len(heading.group(1)), heading.group(2))))
        elif RULE_RE.match(stripped):
            flush()
            out.append(("rule", None))
        elif stripped.startswith("|"):
            flush()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                if not TABLE_RULE_RE.match(lines[i]):
                    cells = re.split(r"(?<!\\)\|", lines[i].strip().strip("|"))
                    rows.append([clean_links(re.sub(r"[*_`]", "", c.strip().replace("\\|", "|"))) for c in cells])
                i += 1
            out.append(("table", rows))
            continue
        elif stripped.startswith(">"):
            flush()
            out.append(("quote", stripped.lstrip("> ").strip()))
        else:
            item = LIST_RE.match(line)
            if item:
                flush()
                depth = len(item.group(1).replace("\t", "    ")) // 2
                marker, body = item.group(2), item.group(3)
                task = TASK_RE.match(body)
                if task:
                    marker, body = ("[x]" if task.group(1).lower() == "x" else "[ ]"), body[task.end():]
                elif not marker[0].isdigit():
                    marker = "•" if depth % 2 == 0 else "–"
                out.append(("li", (min(depth, 4), marker, body)))
            elif out and out[-1][0] == "li" and not para and line.startswith(("  ", "\t")):
                depth, marker, body = out[-1][1]
                out[-1] = ("li", (depth, marker, body + " " + stripped))     # a list item that runs on
            else:
                para.append(line)
        i += 1
    flush()
    return out


def _norm(s):
    return re.sub(r"\s+", " ", re.sub(r"[*_`]", "", s)).strip().lower()


# ---------------------------------------------------------------- layout

class Layout:
    """Places text on A4 pages, top to bottom. Each page is a list of drawing operations (bytes)."""

    def __init__(self):
        self.w, self.h = A4
        self.left, self.right = MARGIN, A4[0] - MARGIN
        self.top, self.bottom = A4[1] - MARGIN, MARGIN + 18
        self.pages = []
        self.new_page()

    def new_page(self):
        if len(self.pages) >= MAX_PAGES:
            raise PrintError(f"That note would be over {MAX_PAGES} pages, too long to print.")
        self.pages.append([])
        self.y = self.top

    def need(self, height):
        if self.y - height < self.bottom:
            self.new_page()

    def space(self, points):
        if self.y != self.top:
            self.y -= points

    def draw(self, x, font, size, data, grey=False):
        colour = b"0.42 g " if grey else b""
        self.pages[-1].append(colour + b"BT /" + font.encode() + b" %.2f Tf %.2f %.2f Td " % (size, x, self.y)
                              + pdf_string(data) + b" Tj ET" + (b" 0 g" if grey else b""))

    def line(self, x1, x2, y, grey=0.75, thick=0.6):
        self.pages[-1].append(b"%.2f G %.2f w %.2f %.2f m %.2f %.2f l S 0 G" % (grey, thick, x1, y, x2, y))

    def bar(self, x, y1, y2):
        self.pages[-1].append(b"0.8 G 2 w %.2f %.2f m %.2f %.2f l S 0 G" % (x, y1, x, y2))

    def words(self, parts, size):
        """[(font, text)] -> words, each a list of (font, bytes) pieces with no space inside, and whether a space
        comes before it."""
        out, current, space_before = [], [], False
        for font, text in parts:
            for piece in re.split(r"(\s+)", text):
                if not piece:
                    continue
                if piece.isspace():
                    if current:
                        out.append((space_before, current))
                        current = []
                    space_before = True
                    continue
                current.append((font, encode(piece)))
        if current:
            out.append((space_before, current))
        return out

    def paragraph(self, parts, size, indent=0, grey=False, quote=False, marker=None):
        """Wrapped text from the left margin + indent. marker: (x, bytes) printed level with the first line."""
        x0 = self.left + indent
        width_max = self.right - x0
        lead = size * LEADING
        lines, line, line_w = [], [], 0.0
        for space_before, word in self.words(parts, size):
            w = sum(width(d, f, size) for f, d in word)
            gap = width(b" ", REGULAR, size) if (line and space_before) else 0.0
            if line and line_w + gap + w > width_max:
                lines.append(line)
                line, line_w, gap = [], 0.0, 0.0
            if w > width_max:                                   # one word wider than the page: cut it
                for f, d in word:
                    while d:
                        n = len(d)
                        while n > 1 and line_w + width(d[:n], f, size) > width_max:
                            n -= 1
                        line.append((line_w, f, d[:n]))
                        line_w += width(d[:n], f, size)
                        d = d[n:]
                        if d:
                            lines.append(line)
                            line, line_w = [], 0.0
                continue
            x = line_w + gap
            for f, d in word:
                line.append((x, f, d))
                x += width(d, f, size)
            line_w = x
        if line:
            lines.append(line)
        for n, placed in enumerate(lines or [[]]):
            self.need(lead)
            self.y -= size
            if quote:
                self.bar(x0 - 9, self.y - size * 0.3, self.y + size)
            if n == 0 and marker:
                self.draw(marker[0], REGULAR, size, marker[1])
            for x, f, d in placed:
                self.draw(x0 + x, f, size, d, grey)
            self.y -= lead - size

    def mono_lines(self, rows, size=CODE_SIZE, indent=0):
        """Lines of Courier, wrapped at the page width (code blocks and tables)."""
        x0 = self.left + indent
        per_line = max(10, int((self.right - x0) / (0.6 * size)))
        lead = size * 1.3
        for row in rows:
            data = encode(row) or b""
            chunks = [data[k:k + per_line] for k in range(0, len(data), per_line)] or [b""]
            for chunk in chunks:
                self.need(lead)
                self.y -= size
                if chunk:
                    self.draw(x0, MONO, size, chunk)
                self.y -= lead - size


def table_text(rows):
    """Table rows as lines of text with columns lined up (Courier keeps them straight)."""
    if not rows:
        return []
    cols = max(len(r) for r in rows)
    rows = [r + [""] * (cols - len(r)) for r in rows]
    widths = [min(40, max(len(r[c]) for r in rows)) for c in range(cols)]
    out = []
    for n, r in enumerate(rows):
        out.append("  ".join(r[c][:widths[c]].ljust(widths[c]) for c in range(cols)).rstrip())
        if n == 0 and len(rows) > 1:
            out.append("  ".join("-" * w for w in widths))
    return out


def render(title, markdown, subtitle=""):
    """The note on A4 pages -> list of page content streams (bytes)."""
    page = Layout()
    page.paragraph([(BOLD, title or "Untitled")], TITLE_SIZE)
    if subtitle:
        page.y -= 2
        page.paragraph([(REGULAR, subtitle)], 9, grey=True)
    page.y -= 6
    page.line(page.left, page.right, page.y)
    page.y -= 10
    for kind, data in blocks(markdown, title):
        if kind == "h":
            level, text = data
            size = HEADING_SIZES[level]
            page.space(size * 0.7)
            page.need(size * LEADING * 3)                       # never a heading alone at the foot of a page
            page.paragraph(spans(text, BOLD), size)
            page.y -= 2
        elif kind == "p":
            page.paragraph(spans(data), BODY_SIZE)
            page.y -= BODY_SIZE * 0.55
        elif kind == "li":
            depth, marker, body = data
            indent = 16 + depth * 16
            mark = encode(marker)
            mark_x = page.left + indent - width(mark, REGULAR, BODY_SIZE) - 5
            page.paragraph(spans(body), BODY_SIZE, indent=indent, marker=(mark_x, mark))
            page.y -= 1.5
        elif kind == "quote":
            page.paragraph(spans(data, ITALIC), BODY_SIZE, indent=14, quote=True)
            page.y -= BODY_SIZE * 0.55
        elif kind == "code":
            page.space(2)
            page.mono_lines(data, indent=10)
            page.y -= BODY_SIZE * 0.6
        elif kind == "table":
            page.space(2)
            page.mono_lines(table_text(data))
            page.y -= BODY_SIZE * 0.6
        elif kind == "rule":
            page.need(14)
            page.y -= 6
            page.line(page.left, page.right, page.y)
            page.y -= 8
    total = len(page.pages)
    name = encode(title or "")
    if len(name) > 70:
        name = name[:67] + b"..."
    for n, ops in enumerate(page.pages, 1):
        foot = name + b"   \x97   " + b"page %d of %d" % (n, total)
        ops.append(b"0.5 g BT /F1 8 Tf %.2f %.2f Td " % (page.left, FOOTER_Y) + pdf_string(foot) + b" Tj ET 0 g")
    return [b"\n".join(op for op in ops if op) for ops in page.pages]



# ---------------------------------------------------------------- the PDF file

def note_pdf(title, markdown, subtitle="", password=None, aes=None):
    """A note -> the bytes of a PDF. With a password: AES-256 locked (aes: the AES to use, default Windows')."""
    pages = render(title, markdown, subtitle)
    lock = Lock(password, aes or windows_aes()) if password is not None else None
    objects = {}                       # number -> body bytes (streams already compressed and, if locked, encrypted)
    fonts = {name: 3 + i for i, name in enumerate(FONTS)}
    objects[1] = b"<< /Type /Catalog /Pages 2 0 R >>"
    first_page = 3 + len(FONTS)
    kids = []
    for name, num in fonts.items():
        objects[num] = (b"<< /Type /Font /Subtype /Type1 /BaseFont /" + FONTS[name][0].encode()
                        + b" /Encoding /WinAnsiEncoding >>")
    font_dict = b"<< " + b" ".join(b"/%s %d 0 R" % (n.encode(), num) for n, num in fonts.items()) + b" >>"
    for i, content in enumerate(pages):
        page_num, content_num = first_page + 2 * i, first_page + 2 * i + 1
        kids.append(b"%d 0 R" % page_num)
        objects[page_num] = (b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 %.2f %.2f] /Resources << /Font %s >> "
                             b"/Contents %d 0 R >>" % (A4[0], A4[1], font_dict, content_num))
        data = zlib.compress(content, 9)
        if lock:
            data = lock.encrypt(data)
        objects[content_num] = b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(data) + data + b"\nendstream"
    objects[2] = b"<< /Type /Pages /Kids [" + b" ".join(kids) + b"] /Count %d >>" % len(pages)
    n = max(objects) + 1
    trailer_extra = b""
    if lock:
        objects[n] = lock.dictionary()
        trailer_extra = b" /Encrypt %d 0 R" % n
    else:                              # a locked PDF carries no plain-text title or dates outside the lock
        stamp = datetime.datetime.now().strftime("D:%Y%m%d%H%M%S").encode()
        objects[n] = (b"<< /Title " + _text_string(title) + b" /Producer " + _text_string(PRODUCER)
                      + b" /CreationDate (" + stamp + b") >>")
        trailer_extra = b" /Info %d 0 R" % n
    file_id = secrets.token_bytes(16).hex().encode()
    out = bytearray(b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n" if not lock else b"%PDF-2.0\n%\xe2\xe3\xcf\xd3\n")
    offsets = {}
    for num in sorted(objects):
        offsets[num] = len(out)
        out += b"%d 0 obj\n" % num + objects[num] + b"\nendobj\n"
    size = max(objects) + 1
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % size
    for num in range(1, size):
        out += b"%010d 00000 n \n" % offsets[num]
    out += (b"trailer\n<< /Size %d /Root 1 0 R" % size + trailer_extra + b" /ID [<" + file_id + b"> <" + file_id
            + b">] >>\nstartxref\n%d\n%%%%EOF\n" % xref)
    return bytes(out)


def _text_string(text):
    """A string for the document's info: UTF-16 so any title reads right in the reader's properties."""
    return b"<FEFF" + str(text).encode("utf-16-be").hex().upper().encode() + b">"


# ---------------------------------------------------------------- the lock (AES-256, PDF 2.0, revision 6)

class Lock:
    """The standard security handler, revision 6 (ISO 32000-2, 7.6.4): a random 256-bit file key, sealed under the
    password (U, UE) and under a random owner password nobody knows (O, OE), so the file's permissions can't be
    changed. Strings and streams are AES-256-CBC with a random IV in front."""

    PERMISSIONS = -4                   # everything allowed to whoever has the password (print, copy)

    def __init__(self, password, aes):
        check_aes(aes)
        pw = prepare_password(password)
        self.aes = aes
        self.key = secrets.token_bytes(32)
        uvs, uks = secrets.token_bytes(8), secrets.token_bytes(8)
        self.u = hash_r6(pw, uvs, b"", aes) + uvs + uks
        self.ue = aes(hash_r6(pw, uks, b"", aes), self.key, bytes(16))
        owner = secrets.token_bytes(32)
        ovs, oks = secrets.token_bytes(8), secrets.token_bytes(8)
        self.o = hash_r6(owner, ovs, self.u, aes) + ovs + oks
        self.oe = aes(hash_r6(owner, oks, self.u, aes), self.key, bytes(16))
        perms = (self.PERMISSIONS & 0xFFFFFFFF).to_bytes(4, "little") + b"\xff\xff\xff\xffTadb" + secrets.token_bytes(4)
        self.perms = aes(self.key, perms, None)

    def encrypt(self, data):
        pad = 16 - len(data) % 16
        iv = secrets.token_bytes(16)
        return iv + self.aes(self.key, data + bytes([pad]) * pad, iv)

    def dictionary(self):
        def hexs(b):
            return b"<" + b.hex().encode() + b">"
        return (b"<< /Filter /Standard /V 5 /R 6 /Length 256 /P %d /EncryptMetadata true "
                b"/CF << /StdCF << /Type /CryptFilter /CFM /AESV3 /AuthEvent /DocOpen /Length 32 >> >> "
                b"/StmF /StdCF /StrF /StdCF /O " % self.PERMISSIONS + hexs(self.o) + b" /U " + hexs(self.u)
                + b" /OE " + hexs(self.oe) + b" /UE " + hexs(self.ue) + b" /Perms " + hexs(self.perms) + b" >>")


def prepare_password(password):
    """The password as PDF 2.0 wants it: Unicode normalised, UTF-8, at most 127 bytes."""
    text = unicodedata.normalize("NFKC", str(password or ""))
    if len(text) < MIN_PASSWORD:
        raise PrintError(f"The PDF's password needs at least {MIN_PASSWORD} characters.")
    return text.encode("utf-8")[:127]


def hash_r6(password, salt, udata, aes):
    """ISO 32000-2 algorithm 2.B: the slow, salted hash that turns a password into a key."""
    k = hashlib.sha256(password + salt + udata).digest()
    i = 0
    while True:
        i += 1
        e = aes(k[:16], (password + k + udata) * 64, k[16:32])
        k = (hashlib.sha256, hashlib.sha384, hashlib.sha512)[sum(e[:16]) % 3](e).digest()
        if i >= 64 and e[-1] <= i - 32:
            return k[:32]


# Published AES test vectors (FIPS-197 C.3; SP 800-38A F.2.1 and F.2.5): (key, iv or None for ECB, plain, cipher)
AES_VECTORS = [
    ("000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f", None,
     "00112233445566778899aabbccddeeff", "8ea2b7ca516745bfeafc49904b496089"),
    ("2b7e151628aed2a6abf7158809cf4f3c", "000102030405060708090a0b0c0d0e0f",
     "6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51",
     "7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"),
    ("603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4", "000102030405060708090a0b0c0d0e0f",
     "6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51",
     "f58c4c04d6e5f1ba779eabfb5f7bfbd69cfc4e967edb808d679f777bc6702c7d"),
]


def check_aes(aes):
    """The AES must give the published answers before it locks anything; a wrong one would lock a file for good."""
    for key, iv, plain, cipher in AES_VECTORS:
        got = aes(bytes.fromhex(key), bytes.fromhex(plain), bytes.fromhex(iv) if iv else None)
        if got != bytes.fromhex(cipher):
            raise PrintError("This PC's encryption gave a wrong answer on its self-test, so I won't lock a PDF "
                             "with it.")


def available():
    return sys.platform == "win32"


def windows_aes():
    """Windows' AES (CNG, bcrypt.dll): aes(key, data, iv) -> CBC without padding, or ECB when iv is None. data is a
    whole number of 16-byte blocks."""
    if not available():
        raise PrintError("Locked PDFs need Windows' own encryption, so they can only be made on the Windows PC.")
    import ctypes
    from ctypes import wintypes
    bcrypt = ctypes.WinDLL("bcrypt")
    handle = ctypes.c_void_p
    bcrypt.BCryptOpenAlgorithmProvider.argtypes = [ctypes.POINTER(handle), wintypes.LPCWSTR, wintypes.LPCWSTR,
                                                   wintypes.ULONG]
    bcrypt.BCryptSetProperty.argtypes = [handle, wintypes.LPCWSTR, ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG]
    bcrypt.BCryptGenerateSymmetricKey.argtypes = [handle, ctypes.POINTER(handle), ctypes.c_void_p, wintypes.ULONG,
                                                  ctypes.c_void_p, wintypes.ULONG, wintypes.ULONG]
    bcrypt.BCryptEncrypt.argtypes = [handle, ctypes.c_void_p, wintypes.ULONG, ctypes.c_void_p, ctypes.c_void_p,
                                     wintypes.ULONG, ctypes.c_void_p, wintypes.ULONG, ctypes.POINTER(wintypes.ULONG),
                                     wintypes.ULONG]
    bcrypt.BCryptDestroyKey.argtypes = [handle]
    bcrypt.BCryptCloseAlgorithmProvider.argtypes = [handle, wintypes.ULONG]
    for fn in ("BCryptOpenAlgorithmProvider", "BCryptSetProperty", "BCryptGenerateSymmetricKey", "BCryptEncrypt",
               "BCryptDestroyKey", "BCryptCloseAlgorithmProvider"):
        getattr(bcrypt, fn).restype = ctypes.c_long

    def ok(status, what):
        if status != 0:
            raise PrintError(f"Windows' encryption failed ({what}, 0x{status & 0xFFFFFFFF:08X}).")

    def aes(key, data, iv):
        alg = handle()
        ok(bcrypt.BCryptOpenAlgorithmProvider(ctypes.byref(alg), "AES", None, 0), "open")
        try:
            mode = ctypes.create_unicode_buffer("ChainingModeECB" if iv is None else "ChainingModeCBC")
            ok(bcrypt.BCryptSetProperty(alg, "ChainingMode", mode, ctypes.sizeof(mode), 0), "mode")
            key_buf = ctypes.create_string_buffer(bytes(key), len(key))
            hkey = handle()
            ok(bcrypt.BCryptGenerateSymmetricKey(alg, ctypes.byref(hkey), None, 0, key_buf, len(key), 0), "key")
            try:
                src = ctypes.create_string_buffer(bytes(data), len(data))
                dst = ctypes.create_string_buffer(len(data))
                iv_buf = ctypes.create_string_buffer(bytes(iv), len(iv)) if iv is not None else None
                done = wintypes.ULONG()
                ok(bcrypt.BCryptEncrypt(hkey, src, len(data), None, iv_buf, len(iv) if iv is not None else 0,
                                        dst, len(data), ctypes.byref(done), 0), "encrypt")
                return dst.raw[:done.value]
            finally:
                bcrypt.BCryptDestroyKey(hkey)
        finally:
            bcrypt.BCryptCloseAlgorithmProvider(alg, 0)
    return aes


if __name__ == "__main__":                 # python printing.py NOTE.md [OUT.pdf]: try the layout on a note
    from pathlib import Path
    src = Path(sys.argv[1])
    out = Path(sys.argv[2]) if len(sys.argv) > 2 else src.with_suffix(".pdf")
    out.write_bytes(note_pdf(src.stem, src.read_text(encoding="utf-8")))
    print(f"wrote {out}")
