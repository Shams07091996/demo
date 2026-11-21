"""Edit conflicts: the version counter and how a conflict is described (conflicts.py)."""

from contextlib import contextmanager
from datetime import date, timedelta
from decimal import Decimal

from django.contrib.auth.models import User
from django.test import RequestFactory
from django.utils import timezone

from . import conflicts, history
from .errors import BadRequest
from .models import ChangeRecord, Guest, HotelStay, PortClosure, Service, Transfer
from .tests import ApiTestCase


@contextmanager
def as_user(username):
    """Saves inside are recorded in the History as made by this user (as the HistoryMiddleware does)."""
    request = RequestFactory().put("/api/")
    request.user = User.objects.get(username=username)
    token = history._request.set(request)
    try:
        yield
    finally:
        history._request.reset(token)


def change(instance, username, **values):
    """A person's save as the update views do it: new values, the counter raised if they differ, one save."""
    with as_user(username):
        before = conflicts.snapshot(instance)
        for field, value in values.items():
            setattr(instance, field, value)
        conflicts.bump_if_changed(instance, before)
        instance.save()
    instance.refresh_from_db()


class VersionTests(ApiTestCase):
    def test_new_records_start_at_version_one(self):
        vessel = self.alex_vessel
        stay = HotelStay.objects.create(vessel=vessel, hotel="H", check_in=date(2026, 11, 13), nights=1)
        transfer = Transfer.objects.create(vessel=vessel, from_place="airport", to_place="port", at=timezone.now())
        closure = PortClosure.objects.create(port="alexandria", start_at=timezone.now(), reason="WEATHER")
        for record in (vessel, self.suez_service, stay, transfer, closure):
            record.refresh_from_db()
            self.assertEqual(record.version, 1, type(record).__name__)

    def test_sent_version_refuses_missing_and_non_numbers(self):
        for payload in ({}, {"version": "2"}, {"version": True}, {"version": 0}, {"version": 1.5}, {"version": None}):
            with self.subTest(payload=payload), self.assertRaisesMessage(BadRequest, conflicts.OUT_OF_DATE):
                conflicts.sent_version(payload)
        self.assertEqual(conflicts.sent_version({"version": 3}), 3)

    def test_bump_only_when_changed(self):
        vessel = self.alex_vessel
        change(vessel, "admin", name=vessel.name)
        self.assertEqual(vessel.version, 1)
        change(vessel, "admin", berthing_at=timezone.now())
        self.assertEqual(vessel.version, 2)

    def test_check_passes_on_current_version_and_refuses_an_old_one(self):
        vessel = self.alex_vessel
        conflicts.check(vessel, 1, User.objects.get(username="admin"))
        change(vessel, "alex", poc="X")
        with self.assertRaises(conflicts.Conflict) as caught:
            conflicts.check(vessel, 1, User.objects.get(username="admin"))
        self.assertEqual(caught.exception.status, 409)
        self.assertEqual(caught.exception.extra["conflict"]["version"], 2)


class DescribeTests(ApiTestCase):
    def test_describe_names_last_person_and_all_fields(self):
        vessel = self.alex_vessel
        change(vessel, "alex", berthing_at=timezone.now())
        change(vessel, "admin", sailing_agent="AG")
        found = conflicts.describe(vessel, 1, User.objects.get(username="viewer"))
        self.assertEqual(found["who"], "admin")
        self.assertIs(found["same_person"], False)
        self.assertEqual(found["fields"], ["Berthed", "Sailing agent"])
        self.assertEqual(found["version"], 3)
        self.assertRegex(found["at"], r"^\d\d:\d\d$")  # today: the time only

    def test_describe_only_counts_saves_after_the_version_sent(self):
        vessel = self.alex_vessel
        change(vessel, "alex", poc="A")
        change(vessel, "alex", opr="B")
        found = conflicts.describe(vessel, 2, User.objects.get(username="alex"))
        self.assertEqual(found["fields"], ["OPR"])
        self.assertIs(found["same_person"], True)

    def test_describe_older_save_shows_the_date(self):
        vessel = self.alex_vessel
        change(vessel, "alex", poc="A")
        ChangeRecord.objects.filter(object_type="vessel", object_id=vessel.pk).update(
            at=timezone.now() - timedelta(days=2))
        self.assertRegex(conflicts.describe(vessel, 1, User.objects.get(username="admin"))["at"],
                         r"^\d\d/\d\d \d\d:\d\d$")

    def test_describe_service_data_keys(self):
        service = Service.objects.create(vessel=self.alex_vessel, service_type="Crew Change",
                                         data={"onSigners": [{"name": "A"}], "offSigners": []})
        change(service, "alex", data={"onSigners": [{"name": "B"}], "offSigners": []})
        fields = conflicts.describe(service, 1, User.objects.get(username="admin"))["fields"]
        self.assertIn("On signers", fields)
        self.assertNotIn("Off signers", fields)
        self.assertNotIn("Data", fields)

    def test_describe_booking_guests_only(self):
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="H", check_in=date(2026, 11, 13), nights=1,
                                        cost_per_night=Decimal("10"))
        Guest.objects.create(stay=stay, name="A")
        with as_user("alex"):
            before = conflicts.snapshot(stay)
            conflicts.bump_if_changed(stay, before, guests=[{"name": "B"}])
            stay.save()
        stay.refresh_from_db()
        self.assertEqual(stay.version, 2)
        self.assertEqual(conflicts.describe(stay, 1, User.objects.get(username="admin"))["fields"], ["Guests"])

    def test_same_guests_rebuilt_is_no_change(self):
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="H", check_in=date(2026, 11, 13), nights=1)
        Guest.objects.create(stay=stay, name="A", group="on", crew_uid="abcdef123456")
        before = conflicts.snapshot(stay)
        conflicts.bump_if_changed(stay, before, guests=[{"name": "A", "group": "on", "crew_uid": "abcdef123456"}])
        self.assertEqual(stay.version, 1)
        conflicts.bump_if_changed(stay, before, guests=[{"name": "A", "group": "off", "crew_uid": "abcdef123456"}])
        self.assertEqual(stay.version, 2)


class HistoryPageTests(ApiTestCase):
    def test_history_page_hides_version(self):
        vessel = self.alex_vessel
        change(vessel, "alex", poc="A")
        records = self.call(self.login("admin"), "get", "/api/history/")[1]["records"]
        self.assertTrue(records)
        for record in records:
            self.assertNotIn("version", record["changes"])
        self.assertFalse([r for r in records if not r["changes"] and r["action"] == "update"])

    def test_history_page_guest_only_booking_save_says_guests(self):
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="H", check_in=date(2026, 11, 13), nights=1)
        with as_user("alex"):
            conflicts.bump_if_changed(stay, conflicts.snapshot(stay), guests=[{"name": "B"}])
            stay.save()
        records = self.call(self.login("admin"), "get", "/api/history/?type=hotelstay")[1]["records"]
        self.assertEqual(records[0]["changes"], {"guests": [None, "changed"]})
