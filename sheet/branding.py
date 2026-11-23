"""The company logo: `brand.png` in the letterhead folder (settings.LETTERHEAD_DIR), never in git (the repository is
public) and never under static/. Missing, too big or not a PNG: no logo, and the pages show the anchor icon."""

import logging
from pathlib import Path

from django.conf import settings

security_log = logging.getLogger("sheet.security")

LOGO_FILE = "brand.png"
MAX_LOGO_BYTES = 500_000
PNG_SIGNATURE = b"\x89PNG\r\n\x1a\n"


def logo_bytes():
    """The logo's bytes, or None."""
    folder = settings.LETTERHEAD_DIR
    if not folder:
        return None
    try:
        path = Path(folder, LOGO_FILE)
        if not path.is_file() or path.stat().st_size > MAX_LOGO_BYTES:
            return None
        data = path.read_bytes()
    except OSError:
        security_log.warning("brand logo unreadable")
        return None
    return data if data.startswith(PNG_SIGNATURE) else None


def logo_available():
    return logo_bytes() is not None
