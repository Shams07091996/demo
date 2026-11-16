from datetime import timedelta

from django.conf import settings
from django.db import models

from .constants import OPTION_KINDS, PLACES, PORT_KEYS, PORTS, ROLES, SERVICE_TYPES


class Profile(models.Model):
    """A user's role: admin, read-only, or tied to one port (edits only that port)."""

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=20, choices=ROLES, default="readonly")

    def __str__(self):
        return f"{self.user} ({self.role})"

    @property
    def port(self):
        """The one port this user is restricted to, or None for admin / read-only."""
        return self.role if self.role in PORT_KEYS else None

    @property
    def is_admin(self):
        return self.role == "admin"

    @property
    def can_edit(self):
        return self.is_admin or self.port is not None


class Vessel(models.Model):
    name = models.CharField(max_length=120)
    opr = models.CharField("OPR", max_length=100, blank=True)
    poc = models.CharField("POC", max_length=100, blank=True)
    agent = models.CharField(max_length=100, blank=True)
    date = models.DateField(db_index=True)
    # Port-call milestones (see constants.TIME_FIELDS); all optional.
    arrival_at = models.DateTimeField(null=True, blank=True)
    berthing_at = models.DateTimeField(null=True, blank=True)
    ops_start_at = models.DateTimeField(null=True, blank=True)
    ops_end_at = models.DateTimeField(null=True, blank=True)
    sailing_at = models.DateTimeField(null=True, blank=True)
    port = models.CharField(max_length=20, choices=PORTS, default="alexandria", db_index=True)
    summary = models.JSONField(default=dict, blank=True)  # optional vendor / invoice notes
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-date", "-id"]

    def __str__(self):
        return f"{self.name} ({self.date:%d.%m.%Y})"


class Service(models.Model):
    """A service performed on a vessel. A vessel may have zero or many."""

    vessel = models.ForeignKey(Vessel, on_delete=models.CASCADE, related_name="services")
    service_type = models.CharField(max_length=40, choices=[(t, t) for t in SERVICE_TYPES])
    data = models.JSONField(default=dict, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

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
    created_at = models.DateTimeField(auto_now_add=True)

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
    created_at = models.DateTimeField(auto_now_add=True)

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
