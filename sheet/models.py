from datetime import timedelta

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q
from django.utils import timezone

from .constants import (
    BILLING,
    CANCEL_REASON_MAX,
    OPTION_KINDS,
    PLACES,
    SERVICE_STATUSES,
    SERVICE_TYPES,
)

SETUP_WINDOW = timedelta(hours=72)  # how long after creation / a reset a person may set up their Authenticator
EXEMPT_REFUSED = "Remove the two-step exception first."


def default_setup_until():
    return timezone.now() + SETUP_WINDOW


class Profile(models.Model):
    """A user's ports and their two-step login state. Admins are the superusers (every port, everything); everyone
    else works in `ports` (Port keys, always including `home_port`, where the screens open). No ports: blocked."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    home_port = models.CharField(max_length=20, blank=True)
    ports = models.JSONField(default=list, blank=True)
    # Two-step login (sheet/twostep.py). Only superusers change these, in the admin pages.
    two_step_exempt = models.BooleanField(
        "Two-step exception", default=False, help_text="Signs in with the password only. Never for admins."
    )
    must_change_password = models.BooleanField(
        default=False, help_text="Set when someone else set the password: they choose their own at the next sign-in."
    )
    setup_until = models.DateTimeField(
        "Authenticator setup allowed until", null=True, blank=True, default=default_setup_until
    )

    def __str__(self):
        return f"{self.user} ({'admin' if self.is_admin else ', '.join(self.ports) or 'no port'})"

    def may_be_exempt(self):
        """Admins (superusers) and anyone who can open the admin pages always need the code."""
        user = self.user
        return not (user.is_superuser or user.is_staff)

    def clean(self):
        if self.two_step_exempt and not self.may_be_exempt():
            raise ValidationError(EXEMPT_REFUSED)

    def save(self, *args, **kwargs):
        self.clean()
        if self.pk is not None and not self.two_step_exempt:
            was_exempt = Profile.objects.filter(pk=self.pk, two_step_exempt=True).exists()
            if was_exempt:  # the exception is removed: a fresh window to set up an Authenticator, like a reset
                self.setup_until = default_setup_until()
        super().save(*args, **kwargs)

    @property
    def port(self):
        """Until every caller reads `ports`: the one port of a single-port user, else None."""
        if self.is_admin or len(self.ports) != 1:
            return None
        return self.ports[0]

    @property
    def is_admin(self):
        return self.user.is_superuser

    @property
    def can_edit(self):
        return self.is_admin or bool(self.ports)


class Customer(models.Model):
    """Who we bill (e.g. the ship's owner / manager), separate from the OPR; shared by all ports."""

    name = models.CharField(max_length=120)
    notes = models.CharField(max_length=500, blank=True)
    active = models.BooleanField(default=True)  # inactive: kept on old records, left out of dropdowns
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]

    def __str__(self):
        return self.name


class CustomerContact(models.Model):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="contacts")
    name = models.CharField(max_length=100)
    role = models.CharField(max_length=60, blank=True)
    email = models.CharField(max_length=254, blank=True)
    phone = models.CharField(max_length=40, blank=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "id"]

    def __str__(self):
        return f"{self.name} ({self.customer})"


class CustomerRate(models.Model):
    """The agreed rate for one service type; its meaning per type is constants.RATE_UNITS."""

    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="rates")
    service_type = models.CharField(max_length=40, choices=[(t, t) for t in SERVICE_TYPES])
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    currency = models.CharField(max_length=3, default="USD")

    class Meta:
        ordering = ["id"]
        constraints = [models.UniqueConstraint(fields=["customer", "service_type"], name="unique_customer_rate")]

    def __str__(self):
        return f"{self.customer}: {self.service_type} {self.amount} {self.currency}"


class Ship(models.Model):
    """One real ship, reused by every port call (Vessel). Shared by all ports. The IMO is empty only for a ship
    marked "No IMO"."""

    name = models.CharField(max_length=120)
    imo = models.CharField("IMO", max_length=7, blank=True)
    opr = models.CharField("OPR", max_length=100, blank=True)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, null=True, blank=True, related_name="ships")
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(fields=["imo"], condition=~Q(imo=""), name="unique_imo")]

    def __str__(self):
        return f"{self.name} ({self.imo or 'no IMO'})"


class Port(models.Model):
    """A port the company works in. `key` is stored on records and never changes; `name` can be renamed; a turned-off
    port takes no new records (sheet/ports.py)."""

    key = models.CharField(max_length=20, unique=True)
    name = models.CharField(max_length=40)
    active = models.BooleanField(default=True)
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["position", "name"]

    def __str__(self):
        return self.name


class Vessel(models.Model):
    name = models.CharField(max_length=120)
    opr = models.CharField("OPR", max_length=100, blank=True)
    poc = models.CharField("POC", max_length=100, blank=True)
    arrival_agent = models.CharField("Arrival agent", max_length=100, blank=True)  # who entered the vessel
    sailing_agent = models.CharField("Sailing agent", max_length=100, blank=True)  # who sailed it
    date = models.DateField(db_index=True)
    # Port-call milestones (see constants.TIME_FIELDS); all optional.
    arrival_at = models.DateTimeField(null=True, blank=True)
    berthing_at = models.DateTimeField(null=True, blank=True)
    ops_start_at = models.DateTimeField(null=True, blank=True)
    ops_end_at = models.DateTimeField(null=True, blank=True)
    sailing_at = models.DateTimeField(null=True, blank=True)
    # From the Master data "delay" list; required when berthing is more than 2 hours after arrival (validators).
    delay_reason = models.CharField("Delay reason", max_length=100, blank=True)
    port = models.CharField(max_length=20, default="alexandria", db_index=True)  # a Port key
    summary = models.JSONField(default=dict, blank=True)  # optional vendor / invoice notes
    ship = models.ForeignKey(Ship, on_delete=models.PROTECT, null=True, blank=True, related_name="vessels")
    created_at = models.DateTimeField(auto_now_add=True)
    version = models.PositiveIntegerField(default=1)  # edit conflicts: +1 per person save that changes it

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.name} ({self.date:%d.%m.%Y})"


class Service(models.Model):
    """A service performed on a vessel. A vessel may have zero or many."""

    vessel = models.ForeignKey(Vessel, on_delete=models.CASCADE, related_name="services")
    service_type = models.CharField(max_length=40, choices=[(t, t) for t in SERVICE_TYPES])
    agent = models.CharField("Agent", max_length=100, blank=True)  # who did this service
    data = models.JSONField(default=dict, blank=True)
    status = models.CharField(max_length=12, choices=list(SERVICE_STATUSES.items()), default="in_progress")
    cancel_reason = models.CharField(max_length=CANCEL_REASON_MAX, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)  # set by the server when it becomes Completed
    acct_closed = models.BooleanField(default=False)  # accounting: settled (Closed) — locks the service
    billing_party = models.ForeignKey(
        Customer, on_delete=models.PROTECT, null=True, blank=True, related_name="services"
    )  # who pays; the dialog starts it at the ship's customer
    billing = models.CharField(max_length=8, choices=list(BILLING.items()), default="account")  # a label only
    created_at = models.DateTimeField(auto_now_add=True)
    version = models.PositiveIntegerField(default=1)  # edit conflicts: +1 per person save that changes it

    class Meta:
        ordering = ["id"]

    def __str__(self):
        return f"{self.service_type} - {self.vessel.name}"


class ExchangeRate(models.Model):
    """USD -> EGP rate for one month (stored as the 1st of that month)."""

    month = models.DateField(unique=True)
    rate = models.DecimalField(max_digits=10, decimal_places=4)

    class Meta:
        ordering = ["-month"]

    def __str__(self):
        return f"{self.month:%m.%Y}: {self.rate}"


MONEY_CURRENCIES = [("EGP", "EGP"), ("USD", "USD")]


def _price_qty(label):
    return models.DecimalField(label, max_digits=12, decimal_places=3, default=0)


def _price_amount(label):
    return models.DecimalField(label, max_digits=12, decimal_places=2, default=0)


def _price_currency(label, default):
    return models.CharField(label, max_length=3, choices=MONEY_CURRENCIES, default=default)


class DisposalPrice(models.Model):
    """Garbage & Sludge prices for one month (stored as the 1st) and one port. Garbage revenue, garbage cost, sludge
    revenue and sludge cost each have a minimum quantity, a minimum amount in its currency and an extra amount per m³ /
    ton above the minimum (disposal.block_amount)."""

    month = models.DateField()
    port = models.CharField(max_length=20)  # a Port key
    garbage_revenue_min_qty = _price_qty("Garbage revenue: minimum quantity (m³)")
    garbage_revenue_min = _price_amount("Garbage revenue: minimum amount")
    garbage_revenue_currency = _price_currency("Garbage revenue: currency", "USD")
    garbage_revenue_extra = _price_amount("Garbage revenue: extra per m³ above the minimum")
    garbage_cost_min_qty = _price_qty("Garbage cost: minimum quantity (m³)")
    garbage_cost_min = _price_amount("Garbage cost: minimum amount")
    garbage_cost_currency = _price_currency("Garbage cost: currency", "EGP")
    garbage_cost_extra = _price_amount("Garbage cost: extra per m³ above the minimum")
    sludge_revenue_min_qty = _price_qty("Sludge revenue: minimum quantity (t)")
    sludge_revenue_min = _price_amount("Sludge revenue: minimum amount")
    sludge_revenue_currency = _price_currency("Sludge revenue: currency", "USD")
    sludge_revenue_extra = _price_amount("Sludge revenue: extra per t above the minimum")
    sludge_cost_min_qty = _price_qty("Sludge cost: minimum quantity (t)")
    sludge_cost_min = _price_amount("Sludge cost: minimum amount")
    sludge_cost_currency = _price_currency("Sludge cost: currency", "EGP")
    sludge_cost_extra = _price_amount("Sludge cost: extra per t above the minimum")

    class Meta:
        ordering = ["-month", "port"]
        constraints = [models.UniqueConstraint(fields=["month", "port"], name="one_disposal_price_per_month_port")]

    def __str__(self):
        return f"{self.month:%m.%Y} {self.port}"


class VesselDisposal(models.Model):
    """A vessel's garbage (m³) and sludge (tons), typed on the Garbage & Sludge page. `hidden` = the vessel has none
    (it leaves the page's normal views and counts 0). Made on the first change; no row = nothing entered yet."""

    vessel = models.OneToOneField(Vessel, on_delete=models.CASCADE, related_name="disposal")
    garbage = models.DecimalField("Garbage (m³)", max_digits=12, decimal_places=3, null=True, blank=True)
    sludge = models.DecimalField("Sludge (t)", max_digits=12, decimal_places=3, null=True, blank=True)
    hidden = models.BooleanField(default=False)
    acct_closed = models.BooleanField(default=False)  # accounting: settled (Closed) — locks the quantities
    # Written when accounting closes it (then kept, also after reopening): the month's rate and price at that time.
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    frozen_price = models.JSONField(null=True, blank=True)

    def __str__(self):
        return f"Garbage & Sludge of vessel {self.vessel_id}"


class Option(models.Model):
    """Master data: the OPR / POC choices. An empty port means shared by everyone."""

    kind = models.CharField(max_length=10, choices=OPTION_KINDS)
    value = models.CharField(max_length=100)
    port = models.CharField(max_length=20, blank=True, default="")
    position = models.PositiveIntegerField(default=0)

    class Meta:
        ordering = ["kind", "position", "id"]
        constraints = [models.UniqueConstraint(fields=["kind", "value", "port"], name="unique_option")]

    def __str__(self):
        return f"{self.kind}: {self.value}" + (f" ({self.port})" if self.port else "")


class PortClosure(models.Model):
    """A port closed from start_at until end_at (empty while still closed). Not linked to vessels."""

    port = models.CharField(max_length=20, db_index=True)  # a Port key
    start_at = models.DateTimeField("Closed from")
    end_at = models.DateTimeField("Reopened", null=True, blank=True)
    reason = models.CharField(max_length=100)  # from the Master data "closure" list
    notes = models.CharField(max_length=500, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    version = models.PositiveIntegerField(default=1)  # edit conflicts: +1 per person save that changes it

    class Meta:
        ordering = ["-start_at", "-id"]

    def __str__(self):
        return f"{self.get_port_display()} closed {timezone.localtime(self.start_at):%d.%m.%Y %H:%M} ({self.reason})"


CURRENCIES = [("EGP", "EGP"), ("USD", "USD")]


class HotelStay(models.Model):
    """One hotel room for one or more guests of a vessel's crew change. Cost (what we pay) and revenue (what we
    get) are per room per night; the stay's money is that times the nights."""

    vessel = models.ForeignKey(Vessel, on_delete=models.CASCADE, related_name="hotel_stays")
    hotel = models.CharField(max_length=100)
    check_in = models.DateField(db_index=True)
    nights = models.PositiveSmallIntegerField()
    cost_per_night = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    cost_currency = models.CharField(max_length=3, choices=CURRENCIES, default="EGP")
    revenue_per_night = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    revenue_currency = models.CharField(max_length=3, choices=CURRENCIES, default="EGP")
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    draft = models.BooleanField(default=False)  # made automatically from a crew change, not completed yet
    cancelled = models.BooleanField(default=False)  # did not happen: kept for its record, no alert, money 0 or a fee
    acct_closed = models.BooleanField(default=False)  # accounting: settled (Closed) — locks the booking
    created_at = models.DateTimeField(auto_now_add=True)
    version = models.PositiveIntegerField(default=1)  # edit conflicts: +1 per person save that changes it

    class Meta:
        ordering = ["check_in", "id"]

    @property
    def check_out(self):
        return self.check_in + timedelta(days=self.nights)

    def __str__(self):
        return f"{self.hotel} {self.check_in:%d.%m.%Y} ({self.nights} nights)"


class Transfer(models.Model):
    """One car trip (airport / hotel / port) for one or more guests of a vessel's crew change."""

    vessel = models.ForeignKey(Vessel, on_delete=models.CASCADE, related_name="transfers")
    from_place = models.CharField(max_length=10, choices=PLACES)
    to_place = models.CharField(max_length=10, choices=PLACES)
    hotel = models.CharField(max_length=100, blank=True)  # which hotel, when one end is "hotel"
    airport = models.CharField(max_length=100, blank=True)  # which airport, when one end is "airport"
    port_name = models.CharField(max_length=100, blank=True)  # which port, when one end is "port"
    at = models.DateTimeField(db_index=True)
    cost = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # what we pay, per trip
    cost_currency = models.CharField(max_length=3, choices=CURRENCIES, default="EGP")
    revenue = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)  # what we get, per trip
    revenue_currency = models.CharField(max_length=3, choices=CURRENCIES, default="EGP")
    exchange_rate = models.DecimalField(max_digits=10, decimal_places=4, null=True, blank=True)
    draft = models.BooleanField(default=False)  # made automatically from a crew change, not completed yet
    cancelled = models.BooleanField(default=False)  # did not happen: kept for its record, no alert, money 0 or a fee
    acct_closed = models.BooleanField(default=False)  # accounting: settled (Closed) — locks the booking
    created_at = models.DateTimeField(auto_now_add=True)
    version = models.PositiveIntegerField(default=1)  # edit conflicts: +1 per person save that changes it

    class Meta:
        ordering = ["at", "id"]

    def __str__(self):
        return f"{self.from_place} -> {self.to_place} {self.at:%d.%m.%Y %H:%M}"


class Guest(models.Model):
    """A guest of exactly one hotel stay or one transfer: a copy of the crew member's details at booking time,
    so later edits to the crew change never change a booking."""

    stay = models.ForeignKey(HotelStay, on_delete=models.CASCADE, null=True, blank=True, related_name="guests")
    transfer = models.ForeignKey(Transfer, on_delete=models.CASCADE, null=True, blank=True, related_name="guests")
    position = models.PositiveSmallIntegerField(default=0)
    name = models.CharField(max_length=120)
    rank = models.CharField(max_length=60, blank=True)
    nationality = models.CharField(max_length=60, blank=True)
    group = models.CharField(max_length=3, blank=True)  # "on", "off" or "" (typed by hand)
    flight = models.CharField(max_length=20, blank=True)
    crew_uid = models.CharField(max_length=12, blank=True, db_index=True)  # the crew member it was copied from

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.CheckConstraint(
                condition=(models.Q(stay__isnull=False, transfer__isnull=True)
                           | models.Q(stay__isnull=True, transfer__isnull=False)),
                name="guest_has_one_booking",
            )
        ]

    def __str__(self):
        return self.name


class LoginAttempt(models.Model):
    """Failed-login counter used to slow down password guessing (see throttle.py)."""

    key = models.CharField(max_length=200, unique=True)
    failures = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()

    def __str__(self):
        return f"{self.key}: {self.failures}"


class RateCounter(models.Model):
    """Requests counted per key in a time window: API rate limits and alert thresholds (ratelimit.py, alerts.py)."""

    key = models.CharField(max_length=200, unique=True)
    count = models.PositiveIntegerField(default=0)
    window_start = models.DateTimeField()

    def __str__(self):
        return f"{self.key}: {self.count}"


class ChangeRecord(models.Model):
    """One create / update / delete of a tracked object (history.py). Append-only: no edit or delete path in the
    app or the Django admin; on PostgreSQL a trigger refuses UPDATE and DELETE (migration 0010). Kept forever."""

    ACTIONS = [("create", "Created"), ("update", "Changed"), ("delete", "Deleted"), ("letter", "LOG made"),
               ("receipt", "Receipt made")]

    at = models.DateTimeField(auto_now_add=True, db_index=True)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )
    username = models.CharField(max_length=150)  # kept if the user is deleted; "system" without a request
    ip = models.CharField(max_length=45, blank=True)
    action = models.CharField(max_length=7, choices=ACTIONS)
    object_type = models.CharField(max_length=30, db_index=True)
    object_id = models.BigIntegerField()
    port = models.CharField(max_length=20, blank=True)
    changes = models.JSONField(default=dict)  # {field: [old, new]}; old is None on create, new is None on delete

    class Meta:
        ordering = ["-id"]

    def __str__(self):
        return f"{self.at:%Y-%m-%d %H:%M} {self.username} {self.action} {self.object_type} #{self.object_id}"


class RememberedComputer(models.Model):
    """"Remember this computer for 30 days": one browser of one user may skip the code. The browser holds a random
    token in a cookie; only its SHA-256 is stored here (sheet/twostep.py)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="remembered_computers")
    token_hash = models.CharField(max_length=64, unique=True)
    created_at = models.DateTimeField(auto_now_add=True)
    expires_at = models.DateTimeField()
    last_used_at = models.DateTimeField(null=True, blank=True)
    ip = models.CharField("Address", max_length=45, blank=True)
    agent = models.CharField("Browser", max_length=200, blank=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.user} · {self.agent[:40]} · until {self.expires_at:%d.%m.%Y}"
