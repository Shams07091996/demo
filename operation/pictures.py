"""Terminal pictures for Live data: `<letterhead folder>/terminals/<CODE>.png` or `.jpg`, put there on the server by
hand (no upload in the app, the user's choice). Never in git (the repository is public) and never under static/.
Only a code of letters, digits, "_" and "-" names a file, so a code can never point outside that folder. Missing,
too big or not a PNG / JPEG by its first bytes: no picture."""

import logging
import re
from pathlib import Path

from django.conf import settings

security_log = logging.getLogger("sheet.security")

FOLDER = "terminals"
MAX_BYTES = 1_000_000
SAFE_CODE = re.compile(r"[A-Za-z0-9_-]{1,10}")
KINDS = ((".png", b"\x89PNG\r\n\x1a\n", "image/png"), (".jpg", b"\xff\xd8\xff", "image/jpeg"),
         (".jpeg", b"\xff\xd8\xff", "image/jpeg"))


def _candidates(terminal):
    folder = settings.LETTERHEAD_DIR
    if not folder or not SAFE_CODE.fullmatch(terminal.code or ""):
        return []
    return [(Path(folder, FOLDER, terminal.code + ext), signature, kind) for ext, signature, kind in KINDS]


def _find(terminal, whole):
    """(path, bytes, content type) of the first good file; `whole` False reads only its first bytes."""
    for path, signature, kind in _candidates(terminal):
        try:
            if not path.is_file() or path.stat().st_size > MAX_BYTES:
                continue
            if whole:
                data = path.read_bytes()
            else:
                with path.open("rb") as file:
                    data = file.read(len(signature))
        except OSError:
            security_log.warning("terminal picture unreadable: %s", terminal.id)
            continue
        if data.startswith(signature):
            return path, data, kind
    return None


def picture(terminal):
    """(bytes, content type) of the terminal's picture, or None."""
    found = _find(terminal, whole=True)
    return (found[1], found[2]) if found else None


def has_picture(terminal):
    """Whether the terminal has a picture (sent with every terminal list: reads only the first bytes)."""
    return _find(terminal, whole=False) is not None
