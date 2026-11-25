"""Input checks for terminals and visits: refused with a plain message, never silently fixed (like sheet.validators)."""

from decimal import Decimal

from sheet import access
from sheet.errors import BadRequest
from sheet.validators import _as_dict, _local_datetime, _parse_number, _short, listed

from .models import ListedVessel, Terminal

MAX_BERTHS = 30
MAX_LINES = 50


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


def _lines(value, port, saved):
    """The terminal's shipping lines: each from the Master data list of its port (a line already saved stays allowed)."""
    if value is None:
        return list(saved)
    if not isinstance(value, list) or len(value) > MAX_LINES:
        raise BadRequest(f"Tick at most {MAX_LINES} shipping lines.")
    lines = []
    for item in value:
        text = item if isinstance(item, str) else ""
        line = text.strip() if text.strip() in saved else listed("line", text, port)
        if not line:
            raise BadRequest("Shipping line: choose a value from the Master data Shipping line list for this port.")
        if line in lines:
            raise BadRequest("Each shipping line may appear only once.")
        lines.append(line)
    return lines


def clean_terminal(data, profile, existing=None):
    """A terminal from the Terminals page: every field but the lines required; the port is any existing one (turned
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
        "lines": _lines(data.get("lines"), port, getattr(existing, "lines", []) or []),
        "active": data.get("active", True) is not False,
    }


TIMES = (("eta", "ETA"), ("ata", "ATA"), ("etb", "ETB"), ("etc", "ETC"), ("atb", "ATB"), ("atd", "ATD"))
MAX_MOVES = 1_000_000


def _visit_terminal(data, profile, existing):
    raw = data.get("terminal")
    terminal = None
    if isinstance(raw, (int, str)) and not isinstance(raw, bool) and str(raw).isdigit():
        terminal = Terminal.objects.filter(pk=int(raw)).first()
    if terminal is None:
        raise BadRequest("Choose a terminal.")
    # A new visit, or one moved into this port, needs the port turned on (like every record in a port).
    access.require_port(profile, terminal.port, new=existing is None or existing.terminal.port != terminal.port)
    if not terminal.active and (existing is None or existing.terminal_id != terminal.id):
        raise BadRequest("That terminal is turned off.")
    return terminal


def _berth(value, terminal, saved, label):
    text = _short(value, 10, label)
    if text and text not in terminal.berths and text != saved:
        raise BadRequest(f"{label}: choose one of this terminal's berths.")
    return text


def _loa(value):
    number = _parse_number(value, "LOA")
    if number is None:
        return None
    if not 0 < number <= 500:
        raise BadRequest("LOA must be more than 0 and at most 500 m.")
    return Decimal(str(round(number, 1)))


def clean_listed_vessel(data, existing=None):
    """An entry of the vessel list: name (upper-case, unique ignoring case) and LOA, both required."""
    data = _as_dict(data)
    name = _short(data.get("name"), 100, "Vessel name").upper()
    if not name:
        raise BadRequest("Enter the vessel name.")
    taken = ListedVessel.objects.filter(name__iexact=name)
    if existing is not None:
        taken = taken.exclude(pk=existing.pk)
    if taken.exists():
        raise BadRequest("That vessel is already on the list.")
    loa = _loa(data.get("loa"))
    if loa is None:
        raise BadRequest("Enter the LOA.")
    return {"name": name, "loa": loa}


def _times(data):
    times = {key: _local_datetime(data.get(key), label) for key, label in TIMES}
    if times["eta"] is None:
        raise BadRequest("Enter the ETA.")
    if times["atb"] and not times["ata"]:
        raise BadRequest("ATB needs the ATA.")
    if times["atd"] and not times["atb"]:
        raise BadRequest("ATD needs the ATB.")
    if times["atb"] and times["atb"] < times["ata"]:
        raise BadRequest("ATB cannot be before ATA.")
    if times["atd"] and times["atd"] <= times["atb"]:
        raise BadRequest("ATD must be after ATB.")
    if times["etb"] and times["etb"] < times["eta"]:
        raise BadRequest("ETB cannot be before ETA.")
    if times["etb"] and times["etc"] and times["etc"] < times["etb"]:
        raise BadRequest("ETC cannot be before ETB.")
    return times


def clean_visit(data, profile, existing=None):
    """A visit from the Vessel Data dialog. Required: vessel name, terminal (one of the person's ports, turned on
    for a new visit), shipping line (Master data list of the terminal's port), ETA. Values already saved on the
    visit stay allowed (a line or berth taken off its list)."""
    data = _as_dict(data)
    name = _short(data.get("vessel_name"), 100, "Vessel name").upper()
    if not name:
        raise BadRequest("Enter the vessel name.")
    terminal = _visit_terminal(data, profile, existing)
    saved_line = getattr(existing, "shipping_line", "")
    line = listed("line", data.get("shipping_line"), terminal.port, saved_line)
    if not line:
        raise BadRequest("Choose a shipping line.")
    if terminal.lines and line not in terminal.lines and line != saved_line:
        raise BadRequest("Shipping line: choose one of this terminal's lines.")
    return {
        "vessel_name": name,
        "terminal": terminal,
        "shipping_line": line,
        "loa": _loa(data.get("loa")),
        **_times(data),
        "planned_berth": _berth(data.get("planned_berth"), terminal, getattr(existing, "planned_berth", ""),
                                "Planned berth"),
        "actual_berth": _berth(data.get("actual_berth"), terminal, getattr(existing, "actual_berth", ""),
                               "Actual berth"),
        "cranes": whole(data.get("cranes"), "Cranes", 1, 50, required=False),
        "discharge": whole(data.get("discharge"), "Discharge", 0, MAX_MOVES, required=False),
        "loading": whole(data.get("loading"), "Loading", 0, MAX_MOVES, required=False),
    }
