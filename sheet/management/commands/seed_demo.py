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
from sheet.models import DisposalPrice, ExchangeRate, Option, PortClosure, Profile, Service, Vessel
from sheet.validators import clean_service_data

DEMO_USERS = [
    ("admin", "admin"),
    ("viewer", "readonly"),
    ("alex", "alexandria"),
    ("portsaid", "portsaid"),
    ("damietta", "damietta"),
    ("suez", "suez"),
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
                self.stdout.write(f"  {username:<9} {role:<10} password: {password}")
            Profile.objects.update_or_create(user=user, defaults={"role": role})

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
        v1 = Vessel.objects.create(
            name="MSC AURORA", opr="MSK", poc="ALY", date=today, port="alexandria", arrival_agent="DELTA SHIPPING"
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
        # Cleaned like a browser save (crew uids); Ahmed Test needs a hotel. sync() makes the draft bookings.
        Service.objects.create(
            vessel=v1,
            service_type="Crew Change",
            data=clean_service_data("Crew Change", {
                "onSigners": [
                    {"name": "Ahmed Test", "personalStructured": {"rank": "2/E", "nationality": "Egyptian"},
                     "flightStructured": flight, "needsHotel": True,
                     "flightData": f"MS123 EGYPTAIR ARRIVAL ALEXANDRIA {landing}",
                     "personalData": "Surname: Test\nGiven name: Ahmed\nRank: 2/E\nNationality: Egyptian"},
                    {"name": "Ali Sayed", "personalStructured": {"rank": "OS", "nationality": "Egyptian"},
                     "flightStructured": early},
                ],
                "offSigners": [],
            }),
        )
        crewbookings.sync(v1)
        v2 = Vessel.objects.create(
            name="ARKAS STAR", opr="ARK", poc="AIT", date=today + timedelta(days=1), port="portsaid",
            arrival_agent="NILE AGENCY", sailing_agent="NILE AGENCY",
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
            arrival_agent="DELTA SHIPPING",
        )
        # A past Alexandria call with no times that still misses its sailing agent and a service agent: the "Missing
        # details" alert.
        v4 = Vessel.objects.create(
            name="SEA BREEZE", opr="MSK", poc="ALY", date=today - timedelta(days=1), port="alexandria",
            arrival_agent="DELTA SHIPPING",
        )
        Service.objects.create(vessel=v4, service_type="Landing", data={"entries": []})
        self.stdout.write(self.style.SUCCESS("Demo data created."))
