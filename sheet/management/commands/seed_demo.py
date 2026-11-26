import binascii
from base64 import b32decode
from datetime import date, datetime, time, timedelta

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone
from django.utils.crypto import get_random_string
from django_otp.plugins.otp_totp.models import TOTPDevice

from sheet import crewbookings
from sheet.constants import PAGE_KEYS, PERMISSION_KEYS, TEMPLATES
from sheet.models import (
    Customer,
    CustomerRate,
    DisposalPrice,
    ExchangeRate,
    Option,
    PortClosure,
    Profile,
    Service,
    Ship,
    Vessel,
)
from sheet.validators import clean_service_data

DEMO_USERS = [
    ("admin", "admin"),
    ("viewer", ["alexandria", "portsaid", "damietta"]),
    ("alex", "alexandria"),
    ("portsaid", "portsaid"),
    ("damietta", "damietta"),
    ("suez", "suez"),
    ("marine", "alexandria"),
]
# Demo users that start from a template (constants.TEMPLATES); every other User gets every permission and page.
DEMO_TEMPLATES = {"marine": "marine"}
# Ticks a demo user does not get (viewer looks at the Operation pages without changing them).
DEMO_WITHOUT = {"viewer": ("operation.edit", "operation.delete", "operation.master")}
# The berthing workbook's terminals (all in Alexandria / Dekheila) and one in Port Said for the scoping checks.
DEMO_TERMINALS = [
    ("ACCHCO - ALX", "EGALY", "alexandria", 500, 4, ["23", "24", "25"]),
    ("AICT - ALX", "EGAIT", "alexandria", 350, 2, ["40/1", "40/2"]),
    ("ACCHCO - DKH", "EGEDK", "alexandria", 1000, 8, ["96/1", "96/2", "96/3", "96/4"]),
    ("AICT - DKH", "EGACT", "alexandria", 500, 3, ["98/1", "98/2"]),
    ("TMT - ALX", "TMT", "alexandria", 1200, 4, ["27", "28"]),
    ("PSD EAST", "PSDE", "portsaid", 600, 3, ["1", "2"]),
]
# MAERSK has two weekly windows at ACCHCO - ALX and one at PSD EAST; the other lines have none.
DEMO_WINDOWS = (("ACCHCO - ALX", "MAERSK", 1, (6, 0), 2, (18, 0)), ("ACCHCO - ALX", "MAERSK", 4, (22, 0), 5, (20, 0)),
                ("PSD EAST", "MAERSK", 2, (8, 0), 3, (8, 0)))
DEMO_LINES = ("ARKAS", "MAERSK", "SOC", "ICR", "CUL", "MCL")
# The vessels working now and due soon (below) for the vessel list, with their LOA.
DEMO_MORE_VESSELS = (("NORDIC STAR", "ARKAS", 210), ("CAPE ORION", "MAERSK", 180), ("SEA FALCON", "CUL", 190),
                     ("BLUE MARLIN", "MCL", 140), ("RED CORAL", "ICR", 230), ("PORT STAR", "SOC", 160))
# The workbook's seven visits: name, line, terminal, LOA, hours from day 0 of ETA / ATA / ATB / ATD, cranes,
# discharge, loading, planned / actual berth. Day 0 is 14 days ago, so all of them have sailed.
DEMO_VISITS = [
    ("ALLEGRI", "ARKAS", "ACCHCO - ALX", 200, 6, 7, 11, 46, 2, 700, 800, "25", "25"),
    ("EGYCROWN", "MAERSK", "AICT - ALX", 150, 32, 33, 38, 53, 2, 500, 500, "40/1", "40/1"),
    ("MYD", "MCL", "AICT - DKH", 200, 249, 251, 254, 265, 2, 200, 300, "98/2", "98/2"),
    ("TB QUANZHOU", "MCL", "AICT - DKH", 150, 278, 289, 290, 317, 2, 250, 400, "98/1", "98/2"),
    ("ZHONG GU", "CUL", "AICT - ALX", 150, 102, 103, 106, 134, 2, 500, 500, "40/1", "40/2"),
    ("GLEVIN", "ICR", "AICT - DKH", 100, 54, 55, 59, 122, 2, 200, 500, "98/2", "98/2"),
    ("ROZA", "ARKAS", "ACCHCO - ALX", 200, 169, 171, 186, 193, 1, 100, 500, "25", "23"),
]


class Command(BaseCommand):
    help = "Create demo users, an exchange rate and a few vessels (development only)."

    def add_arguments(self, parser):
        parser.add_argument("--password", help="Use this password for the demo users (default: a random one each).")
        parser.add_argument("--force", action="store_true", help="Allow running with DJANGO_DEBUG=0.")
        parser.add_argument(
            "--two-step-key",
            help="Give every demo user a ready Authenticator with this base32 key (for the smoke test). "
            "Without it, each demo user sets up their own at the first sign-in.",
        )

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            raise CommandError(
                "Refusing to create demo accounts while DEBUG is off. Use --force if you really mean it."
            )
        key = self._hex_key(options["two_step_key"]) if options["two_step_key"] else None
        self._create_users(options["password"])
        if key:
            self._give_devices(key)
        self._create_vessels()
        self._create_operation()

    @staticmethod
    def _hex_key(text):
        cleaned = "".join(text.split()).upper()
        try:
            raw = b32decode(cleaned + "=" * (-len(cleaned) % 8))
        except (binascii.Error, ValueError):
            raise CommandError("--two-step-key must be base32 (letters A-Z and digits 2-7).") from None
        if len(raw) < 20:
            raise CommandError("--two-step-key must be at least 32 base32 characters (160 bits).")
        return raw.hex()

    @staticmethod
    def _give_devices(key):
        for username, _ in DEMO_USERS:
            user = User.objects.get(username=username)
            TOTPDevice.objects.filter(user=user).delete()
            TOTPDevice.objects.create(user=user, name="Authenticator", key=key, confirmed=True)

    def _create_users(self, shared_password):
        for username, role in DEMO_USERS:
            user, created = User.objects.get_or_create(username=username)
            if created:
                password = shared_password or get_random_string(14)
                user.set_password(password)
                user.is_staff = user.is_superuser = role == "admin"
                user.save()
                self.stdout.write(f"  {username:<9} {', '.join(role) if isinstance(role, list) else role:<10}"
                                  f" password: {password}")
            ports = [] if role == "admin" else ([role] if isinstance(role, str) else list(role))
            template = next((t for t in TEMPLATES if t[0] == DEMO_TEMPLATES.get(username)), None)
            permissions, pages = (template[2], template[3]) if template else (PERMISSION_KEYS, PAGE_KEYS)
            permissions = [key for key in permissions if key not in DEMO_WITHOUT.get(username, ())]
            Profile.objects.update_or_create(user=user, defaults={"home_port": ports[0] if ports else "",
                                                                  "ports": ports, "permissions": list(permissions),
                                                                  "pages": list(pages)})

    @staticmethod
    def _create_operation():
        """Berthing demo: the workbook's terminals, shipping lines and visits, plus vessels working now and due
        in the next days (so Live data always has rows)."""
        from operation.models import BerthingWindow, ListedVessel, Terminal, Visit

        terminals = {}
        for position, (name, code, port, quay, cranes, berths) in enumerate(DEMO_TERMINALS):
            terminals[name], _ = Terminal.objects.get_or_create(name=name, defaults={
                "code": code, "port": port, "quay_length": quay, "cranes": cranes, "berths": berths,
                "position": position})
        for value in DEMO_LINES:
            Option.objects.get_or_create(kind="line", value=value, port="")
        fleet = [(row[0], row[1], row[3]) for row in DEMO_VISITS] + list(DEMO_MORE_VESSELS)
        for name, line, loa in fleet:  # the vessel list: each demo vessel's operator and fixed LOA
            ListedVessel.objects.get_or_create(name=name, defaults={"loa": loa, "line": line})
        for term, line, start_day, start, end_day, end in DEMO_WINDOWS:  # weekly berthing windows (Mon = 0)
            BerthingWindow.objects.get_or_create(terminal=terminals[term], line=line, start_day=start_day,
                                                 start_time=time(*start), defaults={"end_day": end_day,
                                                                                    "end_time": time(*end)})
        if Visit.objects.exists():
            return
        day0 = timezone.make_aware(datetime.combine(date.today() - timedelta(days=14), time()))
        for name, line, term, loa, eta, ata, atb, atd, cranes, disch, load, planned, actual in DEMO_VISITS:
            Visit.objects.create(
                terminal=terminals[term], vessel_name=name, shipping_line=line, loa=loa,
                eta=day0 + timedelta(hours=eta), ata=day0 + timedelta(hours=ata), atb=day0 + timedelta(hours=atb),
                atd=day0 + timedelta(hours=atd), cranes=cranes, discharge=disch, loading=load,
                planned_berth=planned, actual_berth=actual)
        now = timezone.now().replace(minute=0, second=0, microsecond=0)
        hour = timedelta(hours=1)
        Visit.objects.create(terminal=terminals["ACCHCO - ALX"], vessel_name="NORDIC STAR", shipping_line="ARKAS",
                             loa=210, eta=now - 9 * hour, ata=now - 8 * hour, atb=now - 5 * hour, cranes=3,
                             discharge=180, loading=60, planned_berth="24", actual_berth="24")
        Visit.objects.create(terminal=terminals["AICT - DKH"], vessel_name="CAPE ORION", shipping_line="MAERSK",
                             loa=180, eta=now - 4 * hour, ata=now - 3 * hour, atb=now - 2 * hour, cranes=2,
                             planned_berth="98/1", actual_berth="98/1")
        for name, line, term, hours_ahead, loa, berth in (
                ("SEA FALCON", "CUL", "ACCHCO - ALX", 20, 190, "23"),
                ("BLUE MARLIN", "MCL", "AICT - ALX", 40, 140, "40/1"),
                ("RED CORAL", "ICR", "TMT - ALX", 70, 230, "27"),
                ("PORT STAR", "SOC", "PSD EAST", 30, 160, "1")):
            eta = now + hours_ahead * hour
            Visit.objects.create(terminal=terminals[term], vessel_name=name, shipping_line=line, loa=loa, eta=eta,
                                 etb=eta + 3 * hour, etc=eta + 27 * hour, planned_berth=berth)

    def _create_vessels(self):
        today = date.today()
        ExchangeRate.objects.get_or_create(month=today.replace(day=1), defaults={"rate": "50.00"})
        # Garbage & Sludge prices for Alexandria this month: minimum 3 m3 / 25 t, then an extra per unit.
        DisposalPrice.objects.get_or_create(month=today.replace(day=1), port="alexandria", defaults={
            "garbage_revenue_min_qty": 3, "garbage_revenue_min": 250, "garbage_revenue_currency": "USD",
            "garbage_revenue_extra": 60, "garbage_cost_min_qty": 3, "garbage_cost_min": 5200,
            "garbage_cost_currency": "EGP", "garbage_cost_extra": 1500, "sludge_revenue_min_qty": 25,
            "sludge_revenue_min": 875, "sludge_revenue_currency": "USD", "sludge_revenue_extra": 30,
            "sludge_cost_min_qty": 25, "sludge_cost_min": 11000, "sludge_cost_currency": "EGP",
            "sludge_cost_extra": 400})
        for kind, values in (("delay", ("WAITING FOR BERTH", "PORT CLOSED", "WEATHER", "PILOT DELAY", "OTHER")),
                             ("closure", ("WEATHER", "FOG", "STRIKE", "OTHER"))):
            for value in values:
                Option.objects.get_or_create(kind=kind, value=value, port="")
        for port, values in (("alexandria", ("ACCHCO", "AICT")), ("portsaid", ("TMT",)), ("damietta", ("DIGCT",)),
                             ("suez", ("SUEZ TERMINAL",))):
            for value in values:
                Option.objects.get_or_create(kind="terminal", value=value, port=port)
        if Vessel.objects.exists():
            return
        # Port closures: yesterday's weather closure in Alexandria, and Port Said still closed by fog.
        def at(day, hour):
            return timezone.make_aware(datetime.combine(day, time(hour)))

        yesterday = today - timedelta(days=1)
        PortClosure.objects.create(port="alexandria", start_at=at(yesterday, 6), end_at=at(yesterday, 14),
                                   reason="WEATHER", notes="Strong wind")
        PortClosure.objects.create(port="portsaid", start_at=at(today, 5), reason="FOG")
        for agent in ("DELTA SHIPPING", "NILE AGENCY"):
            Option.objects.get_or_create(kind="agent", value=agent, port="")
        # Customers with agreed rates, and one ship per demo vessel (MSC AURORA's customer is Blue Owners).
        blue = Customer.objects.create(name="Blue Owners")
        CustomerRate.objects.create(customer=blue, service_type="Fresh Water", amount=50, currency="USD")
        CustomerRate.objects.create(customer=blue, service_type="Crew Change", amount=300, currency="USD")
        red = Customer.objects.create(name="Red Managers")
        ships = {
            name: Ship.objects.create(name=name, imo=imo, opr=opr, customer=customer)
            for name, imo, opr, customer in (
                ("MSC AURORA", "9074729", "MSK", blue),
                ("ARKAS STAR", "9321483", "ARK", red),
                ("NORTHERN LIGHT", "9811000", "Other", None),
                ("SEA BREEZE", "9700005", "MSK", blue),
            )
        }
        v1 = Vessel.objects.create(
            name="MSC AURORA", opr="MSK", poc="ALY", date=today, port="alexandria", arrival_agent="DELTA SHIPPING",
            ship=ships["MSC AURORA"],
        )
        Service.objects.create(
            vessel=v1,
            service_type="Fresh Water",
            agent="NILE AGENCY",
            data={"quantity": 50, "revenue": 900, "revenueCurrency": "USD", "cost": 30000, "costCurrency": "EGP"},
        )
        Service.objects.create(
            vessel=v1,
            service_type="Cash to Master",
            data={"amount": 1000, "amountCurrency": "USD", "shareMode": "percent", "percentage": 5},
        )
        landing = f"{today:%d} {today:%b}".upper() + " 10:00"  # e.g. "16 NOV 10:00", as the flight parser stores it
        flight = {"segments": [{"flightNo": "MS123", "airline": "EGYPTAIR", "arrivalCity": "Alexandria",
                                "arrivalTime": landing}]}
        early_day = today - timedelta(days=3)  # lands 3 days before the vessel: the "Early arrival" alert
        early = {"segments": [{"flightNo": "MS125", "airline": "EGYPTAIR", "arrivalCity": "Alexandria",
                               "arrivalTime": f"{early_day:%d} {early_day:%b}".upper() + " 09:00"}]}
        # Cleaned like a browser save (crew uids); Ahmed Test needs a hotel, both need transport; sync makes drafts.
        Service.objects.create(
            vessel=v1,
            service_type="Crew Change",
            data=clean_service_data("Crew Change", {
                "onSigners": [
                    {"name": "Ahmed Test", "personalStructured": {"rank": "2/E", "nationality": "Egyptian"},
                     "flightStructured": flight, "needsHotel": True, "needsTransport": True,
                     "flightData": f"MS123 EGYPTAIR ARRIVAL ALEXANDRIA {landing}",
                     "personalData": "Surname: Test\nGiven name: Ahmed\nRank: 2/E\nNationality: Egyptian"},
                    {"name": "Ali Sayed", "personalStructured": {"rank": "OS", "nationality": "Egyptian"},
                     "flightStructured": early, "needsTransport": True},
                ],
                "offSigners": [],
            }),
        )
        crewbookings.sync(v1)
        v2 = Vessel.objects.create(
            name="ARKAS STAR", opr="ARK", poc="AIT", date=today + timedelta(days=1), port="portsaid",
            arrival_agent="NILE AGENCY", sailing_agent="NILE AGENCY", ship=ships["ARKAS STAR"],
        )
        Service.objects.create(
            vessel=v2,
            service_type="Crew Change",
            data={
                "onSigners": [
                    {"name": "Sample Crew", "personalStructured": {"rank": "2/E", "nationality": "Egyptian"}}
                ],
                "offSigners": [],
            },
        )
        Vessel.objects.create(
            name="NORTHERN LIGHT", opr="Other", poc="ACT", date=today - timedelta(days=3), port="suez",
            arrival_agent="DELTA SHIPPING", ship=ships["NORTHERN LIGHT"],
        )
        # A past Alexandria call with no times that still misses its sailing agent and a service agent: the "Missing
        # details" alert.
        v4 = Vessel.objects.create(
            name="SEA BREEZE", opr="MSK", poc="ALY", date=today - timedelta(days=1), port="alexandria",
            arrival_agent="DELTA SHIPPING", ship=ships["SEA BREEZE"],
        )
        Service.objects.create(vessel=v4, service_type="Landing", data={"entries": []})
        self.stdout.write(self.style.SUCCESS("Demo data created."))
