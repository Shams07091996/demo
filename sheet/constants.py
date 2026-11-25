"""Fixed business vocabulary shared by models, validation and the front end."""

from datetime import timedelta

PORTS = [
    ("alexandria", "Alexandria"),
    ("portsaid", "Port Said"),
    ("damietta", "Damietta"),
    ("suez", "Suez"),
]
PORT_KEYS = [key for key, _ in PORTS]
PORT_LABELS = dict(PORTS)


SERVICE_TYPES = [
    "Crew Change",
    "Delivery Parcels",
    "Delivery Courier",
    "Medical Treatment",
    "Landing",
    "Certificates",
    "Fresh Water",
    "Suez Canal Transit",
    "Surveyors Attendance",
    "Supply",
    "SIM Cards",
    "Tourism Tours",
    "Cash to Master",
    "Others / Remarks",
]

# Operations status of a service (2026-11-23): key -> label. New services start in progress.
SERVICE_STATUSES = {"in_progress": "In progress", "completed": "Completed", "cancelled": "Cancelled"}
CANCEL_REASON_MAX = 500

# How a service is paid (2026-11-24): a label only; Calculations can filter on it.
BILLING = {"account": "On account", "cash": "Cash"}
# What a customer's agreed rate means per service type (Others / Remarks has no rate).
RATE_UNITS = {
    "Crew Change": "service",
    "Medical Treatment": "service",
    "Certificates": "service",
    "Fresh Water": "unit",
    "Suez Canal Transit": "service",
    "Surveyors Attendance": "service",
    "Supply": "service",
    "SIM Cards": "unit",
    "Tourism Tours": "service",
    "Delivery Parcels": "line",
    "Delivery Courier": "line",
    "Landing": "line",
    "Cash to Master": "percent",
}

# Services made of several priced entries (AWB / weight / cost / revenue).
MULTI_TYPES = ("Delivery Parcels", "Delivery Courier", "Landing")


def _f(key, label, kind="text", **extra):
    return {"key": key, "label": label, "kind": kind, **extra}


# A service's own detail fields (not money), by type: what the form shows, validators._clean_details cleans and the
# card / Summary list. kind: text (max 160 unless given) / number (>= 0) / date / datetime (Cairo, YYYY-MM-DDTHH:MM) /
# choice (one of `choices`). "label": the field shown after the type in its money line ("Fresh Water · 5 t"), with
# "suffix". The agreed "unit" rate multiplies the field `quantity`. Sent to the browser as service-fields-data.
SERVICE_FIELDS = {
    "Medical Treatment": {"fields": [_f("patientName", "Patient name")], "label": "patientName", "suffix": ""},
    "Certificates": {"fields": [_f("certName", "Certificate name")], "label": "certName", "suffix": ""},
    "Fresh Water": {"fields": [_f("quantity", "Quantity (tons)", "number")], "label": "quantity", "suffix": " t"},
    "Suez Canal Transit": {
        "fields": [
            _f("direction", "Direction", "choice", choices=["Northbound", "Southbound"]),
            _f("originPort", "Origin port"), _f("destinationPort", "Destination port"),
            _f("expectedTransit", "Expected transit", "date"), _f("etaSuez", "ETA Suez", "datetime"),
            _f("bookingRef", "Booking reference"), _f("canalAgent", "Canal agent"), _f("convoyNo", "Convoy no."),
            _f("pilotBoarding", "Pilot boarding", "datetime"), _f("canalEntry", "Canal entry", "datetime"),
            _f("canalExit", "Canal exit", "datetime"), _f("scaInvoice", "SCA invoice no."),
        ],
        "label": "direction", "suffix": "", "cost_label": "SCA charges", "cost_currency": "USD",
    },
    "Surveyors Attendance": {
        "fields": [_f("count", "Number of people", "number"), _f("names", "Names", max=500),
                   _f("attendanceAt", "Date and time", "datetime")],
        "label": "count", "suffix": " people",
    },
    "Supply": {"fields": [_f("description", "Description", max=500), _f("quantity", "Quantity", "number")],
               "label": "description", "suffix": ""},
    "SIM Cards": {"fields": [_f("quantity", "Number of cards", "number")], "label": "quantity", "suffix": " cards"},
    "Tourism Tours": {
        "fields": [_f("tour", "Tour"), _f("passengers", "Passengers", "number"), _f("tourDate", "Date", "date")],
        "label": "tour", "suffix": "",
    },
    "Cash to Master": {"fields": [_f("reference", "Reference"), _f("beneficiary", "Beneficiary")], "label": None,
                       "suffix": ""},
}

# Parcel extras (2026-11-25, piece 2 of the HTML gaps). "when" [key, value]: the field is only for that choice.
_TRANSFER = ("Vessel-to-Vessel", "Vessel-to-Courier")
_COURIERS = ("DHL", "FedEx", "Aramex", "Other")
_PAYMENT = _f("payment", "Courier payment", "choice", choices=("Paid", "Not Paid"))
_PARCEL = {"fields": [
    _f("transferType", "Transfer type", "choice", choices=_TRANSFER),
    _f("receivingVessel", "Receiving vessel", when=("transferType", "Vessel-to-Vessel")),
    _f("courier", "Courier", "choice", choices=_COURIERS, when=("transferType", "Vessel-to-Courier")),
    _PAYMENT,
], "label": None, "suffix": ""}
SERVICE_FIELDS["Delivery Parcels"] = _PARCEL
SERVICE_FIELDS["Landing"] = _PARCEL
SERVICE_FIELDS["Delivery Courier"] = {"fields": [
    _f("courier", "Courier", "choice", choices=_COURIERS),
    _f("deliveryStatus", "Delivery status", "choice", choices=("Pending", "Dispatched", "Delivered")),
    _PAYMENT,
], "label": None, "suffix": ""}

# Optional vendor / invoice notes kept on a vessel for its summary.
SUMMARY_FIELDS = (
    "Vendor Name",
    "Vendor Invoice",
    "Selling Rate $",
    "ARKAS FEES Invoice $",
    "ARKAS FEES Invoice LE",
)

# Master-data lists. Vessels store the chosen text in the field of the same name.
OPTION_KINDS = [
    ("opr", "OPR"), ("poc", "POC"), ("agent", "Agent"), ("hotel", "Hotel"), ("airport", "Airport"), ("port", "Port"),
    ("delay", "Delay reason"), ("closure", "Closure reason"), ("terminal", "Terminal"),
]
OPTION_KIND_KEYS = [key for key, _ in OPTION_KINDS]

# Port-call milestones of a vessel, in the order they normally happen.
TIME_FIELDS = [
    ("arrival_at", "Arrived"),
    ("berthing_at", "Berthed"),
    ("ops_start_at", "Ops started"),
    ("ops_end_at", "Ops finished"),
    ("sailing_at", "Sailed"),
]
TIME_KEYS = [key for key, _ in TIME_FIELDS]
TIME_LABELS = dict(TIME_FIELDS)

# A vessel is delayed when it berthed more than this long after it arrived; it then needs a delay reason.
DELAY_LIMIT = timedelta(hours=2)


def is_delayed(arrival_at, berthing_at):
    """Both times known and berthing more than DELAY_LIMIT after arrival (exactly 2:00 is not delayed)."""
    return bool(arrival_at and berthing_at) and berthing_at - arrival_at > DELAY_LIMIT

# Hotels and Transport: a booking is one room / one car trip shared by 1..MAX_GUESTS guests of one vessel.
PLACES = [("airport", "Airport"), ("hotel", "Hotel"), ("port", "Port")]
PLACE_KEYS = [key for key, _ in PLACES]
GUEST_GROUPS = ("on", "off", "")  # on-signer, off-signer, typed by hand
MAX_GUESTS = 6
MAX_NIGHTS = 60

# Dashboard filter value meaning "jobs nobody was assigned to" (an empty agent).
NO_AGENT = "__none__"


# ---- Access rework piece 2: per-person permissions and pages (Profile.permissions / pages) ----------------------

# key -> label, in the order the Accounts dialog shows them. Admins (superusers) have all of them always.
PERMISSIONS = (
    ("vessels.edit", "Add / edit vessels"),
    ("vessels.delete", "Delete vessels"),
    ("services.edit", "Add / edit services"),
    ("services.cancel", "Cancel a service"),
    ("services.complete", "Mark a service Completed"),
    ("money.view", "See money (overviews)"),
    ("money.edit", "Enter / edit prices and costs"),
    ("bookings.edit", "Hotels & transport bookings"),
    ("customers.edit", "Customers and ships: add / edit"),
    ("master.edit", "Master data"),
    ("closures.edit", "Port closures"),
    ("disposal.edit", "Garbage & sludge quantities"),
    ("exports", "Excel / data exports"),
    ("documents", "LOG letter and master receipt"),
    ("history.view", "History"),
    ("accounting.close", "Close / reopen lines"),
)
PERMISSION_KEYS = tuple(key for key, _ in PERMISSIONS)
PERMISSION_LABELS = dict(PERMISSIONS)

# The pages a person can be given (Ports and Accounts are Admin-only and never ticked). Vessels is always on; History
# is on exactly when the person has history.view.
PAGES = (
    ("vessels", "Vessels"),
    ("services", "Services"),
    ("hotels", "Hotels"),
    ("transport", "Transport"),
    ("closures", "Port closures"),
    ("disposal", "Garbage & Sludge"),
    ("calculations", "Calculations"),
    ("dashboard", "Dashboard"),
    ("ships", "Ships"),
    ("customers", "Customers"),
    ("master", "Master data"),
    ("rates", "Exchange rates"),
    ("history", "History"),
)
PAGE_KEYS = tuple(key for key, _ in PAGES)
PAGE_LABELS = dict(PAGES)
# A page or permission that only works together with another permission / page.
PAGE_NEEDS = {"calculations": "money.view", "rates": "money.view", "history": "history.view"}
PERMISSION_NEEDS = {"history.view": ("permission", "money.view"), "accounting.close": ("page", "calculations")}

_MARINE = ("vessels.edit", "services.edit", "services.complete", "money.edit")
_OPERATIONS = (*_MARINE, "services.cancel", "customers.edit", "bookings.edit")
# (key, label, permissions, pages): they only fill in the Accounts dialog's ticks; nothing links a person to one.
TEMPLATES = (
    ("marine", "Marine employee", _MARINE, ("vessels", "services")),
    ("operations", "Operations employee", _OPERATIONS,
     ("vessels", "services", "hotels", "transport", "ships", "customers")),
    ("manager", "Branch manager", PERMISSION_KEYS, PAGE_KEYS),
)
