"""Input checks for terminals and visits: refused with a plain message, never silently fixed (like sheet.validators)."""

from sheet import access
from sheet.errors import BadRequest
from sheet.validators import _as_dict, _short

from .models import Terminal

MAX_BERTHS = 30


def whole(value, label, low, high, required=True):
    """A whole number from low to high; None when empty and not required."""
    if value is None or (isinstance(value, str) and not value.strip()):
        if required:
            raise BadRequest(f"{label} must be a whole number from {low} to {high}.")
        return None
    try:
        number = float(value) if not isinstance(value, bool) else None
    except (TypeError, ValueError):
        number = None
    if number is None or number != int(number) or not low <= number <= high:
        raise BadRequest(f"{label} must be a whole number from {low} to {high}.")
    return int(number)


def _berths(value):
    if not isinstance(value, list) or not 1 <= len(value) <= MAX_BERTHS:
        raise BadRequest(f"Add 1 to {MAX_BERTHS} berths.")
    berths = []
    for item in value:
        text = str(item).strip() if isinstance(item, (str, int)) and not isinstance(item, bool) else ""
        if not 1 <= len(text) <= 10:
            raise BadRequest("A berth name is 1 to 10 characters.")
        if text in berths:
            raise BadRequest("Each berth may appear only once.")
        berths.append(text)
    return berths


def clean_terminal(data, profile, existing=None):
    """A terminal from the Terminals page (Admins): every field required, the port may be any existing one (turned
    on when the terminal is new or moves there)."""
    data = _as_dict(data)
    name = _short(data.get("name"), 40, "Name")
    if len(name) < 2:
        raise BadRequest("Name must be 2 to 40 characters.")
    taken = Terminal.objects.filter(name__iexact=name)
    if existing is not None:
        taken = taken.exclude(pk=existing.pk)
    if taken.exists():
        raise BadRequest("That terminal already exists.")
    code = _short(data.get("code"), 10, "Code").upper()
    if not code:
        raise BadRequest("Enter the terminal code.")
    port = data.get("port")
    moving = existing is None or port != existing.port
    access.require_port(profile, port, new=moving)
    return {
        "name": name,
        "code": code,
        "port": port,
        "quay_length": whole(data.get("quay_length"), "Quay length", 1, 10000),
        "cranes": whole(data.get("cranes"), "Cranes", 0, 50),
        "berths": _berths(data.get("berths")),
        "active": data.get("active", True) is not False,
    }
