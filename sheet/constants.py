"""Fixed business vocabulary shared by models, validation and the front end."""

PORTS = [
    ("alexandria", "Alexandria"),
    ("portsaid", "Port Said"),
    ("damietta", "Damietta"),
    ("suez", "Suez"),
]
PORT_KEYS = [key for key, _ in PORTS]
PORT_LABELS = dict(PORTS)

ROLES = [("admin", "Admin"), ("readonly", "Read-only")] + PORTS

SERVICE_TYPES = [
    "Crew Change",
    "Delivery Parcels",
    "Delivery Courier",
    "Medical Treatment",
    "Landing",
    "Certificates",
    "Fresh Water",
    "Cash to Master",
    "Others / Remarks",
]

# Services made of several priced entries (AWB / weight / cost / revenue).
MULTI_TYPES = ("Delivery Parcels", "Delivery Courier", "Landing")
# Single-priced services and the one extra descriptive field each of them has.
SINGLE_EXTRAS = {
    "Medical Treatment": "patientName",
    "Certificates": "certName",
    "Fresh Water": "quantity",
}

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
    ("opr", "OPR"), ("poc", "POC"), ("agent", "Agent"), ("hotel", "Hotel"), ("airport", "Airport"), ("port", "Port")
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

# Hotels and Transport: a booking is one room / one car trip shared by 1..MAX_GUESTS guests of one vessel.
PLACES = [("airport", "Airport"), ("hotel", "Hotel"), ("port", "Port")]
PLACE_KEYS = [key for key, _ in PLACES]
GUEST_GROUPS = ("on", "off", "")  # on-signer, off-signer, typed by hand
MAX_GUESTS = 6
MAX_NIGHTS = 60
