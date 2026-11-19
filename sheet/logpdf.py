"""The LOG letter ("Invitation letter for boarding") as a PDF, written by hand with the standard library only.

A PDF is structured text: a few numbered objects (catalog, pages, fonts, images, page content) and a table of their
byte offsets. Text uses the PDF's built-in fonts (Helvetica, Helvetica-Bold, Courier-Bold) with WinAnsi encoding, so
nothing is embedded; letters outside it are reduced to their plain form or "?" (to_winansi). The letterhead pictures
are JPEGs placed as they are (/DCTDecode): they are never decoded here, only their size is read from the header.

Safety: every value from the crew change is plain text. It is converted to WinAnsi bytes and written only inside a
PDF string, with \\, ( and ) escaped and control characters removed, so it can never become a PDF name, operator or
link. The layout follows the user's LOG.docx; no placeholder text ({{ }}) is ever written.
"""

import unicodedata

PAGE_W, PAGE_H = 595, 842  # A4 in points
LEFT, RIGHT = 57, 538
TEXT_W = RIGHT - LEFT
LOGO_H = 54
FOOTER_W = PAGE_W - 2 * 36
STAMP_W = 150

FONTS = {"F1": "Helvetica", "F2": "Helvetica-Bold", "F3": "Courier-Bold"}
IMAGE_NAMES = {"logo": "Im1", "stamp": "Im2", "footer": "Im3"}
_COLOR_SPACES = {1: "/DeviceGray", 3: "/DeviceRGB"}

# Helvetica glyph widths (1/1000 em) for printable ASCII 32..126; other characters count as 600. Bold is a little
# wider: measured with BOLD_FACTOR, which errs on the wide side (wrapping a bit early is harmless).
_HELVETICA = [
    278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
    556, 556, 556, 556, 556, 556, 556, 556, 556, 556, 278, 278, 584, 584, 584, 556,
    1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778,
    667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
    333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556,
    556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584,
]
BOLD_FACTOR = 1.1


def to_winansi(text):
    """Plain text -> WinAnsi (cp1252) bytes: kept when the letter exists there, else its plain form (Ş -> S), else
    "?". Tabs become 4 spaces; other control characters are dropped."""
    out = bytearray()
    for char in str(text):
        if char == "\t":
            out += b"    "
            continue
        if unicodedata.category(char) == "Cc":
            continue
        try:
            out += char.encode("cp1252")
            continue
        except UnicodeEncodeError:
            pass
        plain = "".join(c for c in unicodedata.normalize("NFKD", char) if not unicodedata.combining(c))
        try:
            out += plain.encode("cp1252") if plain else b"?"
        except UnicodeEncodeError:
            out += b"?"
    return bytes(out)


def _pdf_string(data):
    """WinAnsi bytes -> a PDF literal string, (...) with \\, ( and ) escaped."""
    return b"(" + data.replace(b"\\", b"\\\\").replace(b"(", b"\\(").replace(b")", b"\\)") + b")"


def jpeg_size(data):
    info = _jpeg_info(data)
    return info[:2] if info else None


def _jpeg_info(data):
    """(width, height, components) of a baseline / progressive JPEG with 1 or 3 components, else None."""
    if not isinstance(data, bytes | bytearray) or data[:2] != b"\xff\xd8":
        return None
    i = 2
    while i + 4 <= len(data):
        if data[i] != 0xFF:
            return None
        marker = data[i + 1]
        if marker == 0xFF:  # fill byte
            i += 1
            continue
        length = int.from_bytes(data[i + 2:i + 4], "big")
        if marker in (0xC0, 0xC1, 0xC2):
            if i + 10 > len(data):
                return None
            height = int.from_bytes(data[i + 5:i + 7], "big")
            width = int.from_bytes(data[i + 7:i + 9], "big")
            components = data[i + 9]
            if width and height and components in _COLOR_SPACES:
                return width, height, components
            return None
        if marker in (0xD9, 0xDA) or length < 2:  # end of image / start of scan before any frame header
            return None
        i += 2 + length
    return None


def _text_width(data, size, font):
    if font == "F3":  # Courier: every glyph is 600
        return len(data) * 0.6 * size
    widths = sum(_HELVETICA[b - 32] if 32 <= b <= 126 else 600 for b in data)
    return widths * size / 1000 * (BOLD_FACTOR if font == "F2" else 1)


def _wrap(data, size, font, width):
    """Split one line of WinAnsi bytes into lines that fit `width` (at spaces when possible)."""
    lines = []
    while _text_width(data, size, font) > width:
        cut = len(data)
        while cut > 1 and _text_width(data[:cut], size, font) > width:
            cut -= 1
        space = data.rfind(b" ", 0, cut + 1)
        if space > 0:
            lines.append(data[:space])
            data = data[space + 1:]
        else:
            lines.append(data[:cut])
            data = data[cut:]
    lines.append(data)
    return lines


class _Layout:
    """Places text and pictures top-down, starting a new page (with logo and footer) when one is full."""

    def __init__(self, images):
        self.images = images  # name -> (width, height, components, data)
        self.pages = []
        footer = images.get("footer")
        self.footer_h = FOOTER_W * footer[1] / footer[0] if footer else 0
        self.bottom = 30 + self.footer_h + 20
        self._new_page()

    def _new_page(self):
        self.ops = []
        self.pages.append(self.ops)
        self.y = PAGE_H - 40
        logo = self.images.get("logo")
        if logo:
            width = LOGO_H * logo[0] / logo[1]
            self._image("logo", LEFT, self.y - LOGO_H, width, LOGO_H)
            self.y -= LOGO_H + 24
        if self.images.get("footer"):
            self._image("footer", 36, 30, FOOTER_W, self.footer_h)

    def _image(self, name, x, y, width, height):
        self.ops.append(f"q {width:.2f} 0 0 {height:.2f} {x:.2f} {y:.2f} cm /{IMAGE_NAMES[name]} Do Q".encode())

    def room(self, height):
        if self.y - height < self.bottom:
            self._new_page()

    def text_at(self, x, y, data, font, size):
        self.ops.append(b"BT /" + font.encode() + f" {size} Tf {x:.2f} {y:.2f} Td ".encode() + _pdf_string(data)
                        + b" Tj ET")

    def line(self, data, font="F1", size=11, x=LEFT, leading=None, width=TEXT_W):
        """Write `data` (WinAnsi bytes) from the cursor, wrapped to `width`."""
        leading = leading or size * 1.3
        for part in _wrap(data, size, font, width):
            self.room(leading)
            self.y -= leading
            self.text_at(x, self.y, part, font, size)

    def block(self, text, font="F3", size=9):
        """Multi-line pasted text, line breaks kept, long lines wrapped."""
        for raw in str(text).replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            self.line(to_winansi(raw.rstrip()), font, size, leading=size * 1.35)

    def gap(self, height):
        self.y -= height

    def rule(self):
        self.room(8)
        self.y -= 6
        self.ops.append(f"0.6 w {LEFT} {self.y:.2f} m {RIGHT} {self.y:.2f} l S".encode())

    def stamp(self):
        stamp = self.images.get("stamp")
        if not stamp:
            return
        height = STAMP_W * stamp[1] / stamp[0]
        self.room(height + 10)
        self.y -= height + 10
        self._image("stamp", RIGHT - STAMP_W, self.y, STAMP_W, height)


def _letter(layout, fields):
    win = {key: to_winansi(fields.get(key) or "") for key in ("to", "date", "vessel")}
    # TO / DATE and CC / OUR REF. as in the Word letter's table (values wrap inside their column).
    for (left_label, left_value), (right_label, right_value) in (
        ((b"TO:", win["to"]), (b"DATE:", win["date"])),
        ((b"CC:", b"XXXXXXXXXXXXXXXXX."), (b"OUR REF.:", win["vessel"])),
    ):
        layout.room(30)
        top = layout.y
        layout.line(left_label, "F1", 11)
        layout.y = top
        layout.line(right_label, "F1", 11, x=330)
        layout.y = top
        layout.line(left_value, "F1", 11, x=120, width=200)
        low = layout.y
        layout.y = top
        layout.line(right_value, "F1", 11, x=420, width=RIGHT - 420)
        layout.y = min(low, layout.y) - 14
    layout.line(b"SUBJECT: INVITATION LETTER FOR BOARDING  M/V " + win["vessel"], "F2", 11, x=LEFT + 30,
                width=TEXT_W - 30)
    layout.rule()
    layout.gap(6)
    layout.line(b"PLEASE NOTE THAT THE FOLLOWING CREW MEMBER (S) WILL JOIN  M/V " + win["vessel"], "F2", 10)
    layout.gap(14)
    layout.block(fields.get("flight") or "")
    layout.gap(18)
    layout.block(fields.get("personal") or "")
    layout.gap(28)
    layout.line(b"A visa has been arranged before departure and will take care of him.", "F2", 11, x=LEFT + 15)
    layout.gap(16)
    layout.line(b"VISA UPON ARRIVAL IN EGYPT", "F2", 11)
    layout.stamp()


def build(fields, images):
    """The LOG letter as PDF bytes. `fields`: to, date, vessel, flight, personal (plain text). `images`: logo,
    stamp, footer as JPEG bytes (missing, None or not a usable JPEG -> left out)."""
    pictures = {}
    for name in IMAGE_NAMES:
        info = _jpeg_info(images.get(name))
        if info:
            pictures[name] = (*info, bytes(images[name]))
    layout = _Layout(pictures)
    _letter(layout, fields)

    objects = []  # (number, body bytes); numbers are positions + 1

    def add(body):
        objects.append(body)
        return len(objects)

    catalog = add(None)
    pages_obj = add(None)
    font_refs = {key: add(f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>".encode())
                 for key, base in FONTS.items()}
    image_refs = {}
    for name, (width, height, components, data) in pictures.items():
        head = (f"<< /Type /XObject /Subtype /Image /Width {width} /Height {height} /ColorSpace "
                f"{_COLOR_SPACES[components]} /BitsPerComponent 8 /Filter /DCTDecode /Length {len(data)} >>")
        image_refs[name] = add(head.encode() + b"\nstream\n" + data + b"\nendstream")
    resources = "<< /Font << " + " ".join(f"/{k} {n} 0 R" for k, n in font_refs.items()) + " >>"
    if image_refs:
        resources += " /XObject << " + " ".join(f"/{IMAGE_NAMES[k]} {n} 0 R" for k, n in image_refs.items()) + " >>"
    resources += " >>"
    page_refs = []
    for ops in layout.pages:
        content = b"\n".join(ops)
        stream = add(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
        page_refs.append(add(f"<< /Type /Page /Parent {pages_obj} 0 R /MediaBox [0 0 {PAGE_W} {PAGE_H}] "
                             f"/Resources {resources} /Contents {stream} 0 R >>".encode()))
    objects[catalog - 1] = f"<< /Type /Catalog /Pages {pages_obj} 0 R >>".encode()
    kids = " ".join(f"{n} 0 R" for n in page_refs)
    objects[pages_obj - 1] = f"<< /Type /Pages /Kids [{kids}] /Count {len(page_refs)} >>".encode()

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets = []
    for number, body in enumerate(objects, 1):
        offsets.append(len(out))
        out += f"{number} 0 obj\n".encode() + body + b"\nendobj\n"
    xref = len(out)
    out += f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode()
    out += b"".join(f"{offset:010d} 00000 n \n".encode() for offset in offsets)
    out += f"trailer\n<< /Size {len(objects) + 1} /Root {catalog} 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    return bytes(out)
