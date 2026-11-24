"""Operations status of a service (In progress / Completed / Cancelled with a reason) and what Cancelled does."""

import importlib
from datetime import timedelta

from django.apps import apps
from django.utils import timezone

from .constants import TIME_KEYS
from .models import ChangeRecord, HotelStay, Service, Transfer, Vessel
from .tests import ApiTestCase
from .tests_crew import landing_text, seg

WATER = {"type": "Fresh Water", "data": {"cost": "10", "costCurrency": "EGP"}}


class StatusTests(ApiTestCase):
    def setUp(self):
        self.alex = self.login("alex")

    def add(self, **extra):
        status, vessel = self.call(self.alex, "post", f"/api/vessels/{self.alex_vessel.id}/services/", {**WATER, **extra})
        self.assertEqual(status, 201, vessel)
        return vessel["services"][-1]

    def put(self, service_id, **extra):
        return self.call(self.alex, "put", f"/api/services/{service_id}/", {**WATER, **extra})

    def test_new_service_starts_in_progress(self):
        service = self.add()
        self.assertEqual(service["status"], "in_progress")
        self.assertEqual(service["cancel_reason"], "")
        self.assertIs(service["closed"], False)

    def test_status_saved_and_returned(self):
        service = self.add()
        status, vessel = self.put(service["id"], status="completed")
        self.assertEqual(status, 200, vessel)
        self.assertEqual(vessel["services"][0]["status"], "completed")
        self.assertEqual(Service.objects.get(pk=service["id"]).status, "completed")

    def test_missing_status_keeps_the_saved_one(self):
        service = self.add(status="completed")
        _, vessel = self.put(service["id"])
        self.assertEqual(vessel["services"][0]["status"], "completed")

    def test_cancel_needs_reason(self):
        service = self.add()
        status, _ = self.put(service["id"], status="cancelled")
        self.assertEqual(status, 400)
        status, vessel = self.put(service["id"], status="cancelled", cancel_reason="  Weather  ")
        self.assertEqual(status, 200, vessel)
        self.assertEqual(vessel["services"][0]["cancel_reason"], "Weather")

    def test_reason_refused_unless_cancelled(self):
        status, _ = self.call(self.alex, "post", f"/api/vessels/{self.alex_vessel.id}/services/",
                              {**WATER, "status": "completed", "cancel_reason": "x"})
        self.assertEqual(status, 400)

    def test_unknown_status_refused(self):
        status, _ = self.call(self.alex, "post", f"/api/vessels/{self.alex_vessel.id}/services/",
                              {**WATER, "status": "done"})
        self.assertEqual(status, 400)

    def test_reason_too_long_refused(self):
        service = self.add()
        status, _ = self.put(service["id"], status="cancelled", cancel_reason="x" * 501)
        self.assertEqual(status, 400)
        status, _ = self.put(service["id"], status="cancelled", cancel_reason="x" * 500)
        self.assertEqual(status, 200)

    def test_status_change_raises_version(self):
        service = self.add()
        before = Service.objects.get(pk=service["id"]).version
        self.put(service["id"], status="completed")
        self.assertEqual(Service.objects.get(pk=service["id"]).version, before + 1)
        record = ChangeRecord.objects.filter(object_type="service", object_id=service["id"], action="update").order_by("id").last()
        self.assertIn("status", record.changes)

    def test_existing_services_become_completed(self):
        migration = importlib.import_module("sheet.migrations.0019_service_status")
        Service.objects.update(status="in_progress")
        migration.mark_existing_completed(apps, None)
        self.assertEqual(set(Service.objects.values_list("status", flat=True)), {"completed"})


CREW = {"type": "Crew Change", "data": {"onSigners": [{"name": "Ahmed Test", "rank": "AB", "needsHotel": True}],
                                        "offSigners": []}}


class CancelTests(ApiTestCase):
    """A cancelled service drops its draft bookings and raises no alerts; un-cancelling brings the drafts back."""

    def setUp(self):
        self.alex = self.login("alex")

    def crew_change(self):
        status, vessel = self.call(self.alex, "post", f"/api/vessels/{self.alex_vessel.id}/services/", CREW)
        self.assertEqual(status, 201, vessel)
        return vessel["services"][-1]

    def put(self, service, **extra):
        data = Service.objects.get(pk=service["id"]).data
        status, body = self.call(self.alex, "put", f"/api/services/{service['id']}/",
                                 {"type": "Crew Change", "data": data, **extra})
        self.assertEqual(status, 200, body)
        return body

    def drafts(self):
        return (HotelStay.objects.filter(vessel=self.alex_vessel, draft=True).count(),
                Transfer.objects.filter(vessel=self.alex_vessel, draft=True).count())

    def test_cancel_deletes_drafts_keeps_saved(self):
        service = self.crew_change()
        self.assertEqual(self.drafts(), (1, 1))
        Transfer.objects.filter(vessel=self.alex_vessel).update(draft=False)  # saved in the dialog
        self.put(service, status="cancelled", cancel_reason="Owner cancelled")
        self.assertEqual(self.drafts(), (0, 0))
        self.assertEqual(Transfer.objects.filter(vessel=self.alex_vessel).count(), 1)

    def test_uncancel_brings_drafts_back(self):
        service = self.crew_change()
        self.put(service, status="cancelled", cancel_reason="Owner cancelled")
        self.put(service, status="in_progress")
        self.assertEqual(self.drafts(), (1, 1))

    def test_cancel_keeps_closed_drafts(self):
        service = self.crew_change()
        HotelStay.objects.filter(vessel=self.alex_vessel).update(acct_closed=True)
        self.put(service, status="cancelled", cancel_reason="Owner cancelled")
        self.assertEqual(self.drafts(), (1, 0))

    def test_cancelled_service_raises_no_alerts(self):
        today = timezone.localdate()
        past = Vessel.objects.create(name="PAST", date=today - timedelta(days=3), port="alexandria",
                                     arrival_agent="A", sailing_agent="B", **{k: timezone.now() for k in TIME_KEYS})
        Service.objects.create(vessel=past, service_type="Fresh Water", status="cancelled", cancel_reason="x")
        when = today + timedelta(days=1)
        early = Vessel.objects.create(name="EARLY", date=when, port="alexandria")
        person = {"name": "J SMITH", "uid": "abcdef123456",
                  "flightStructured": {"segments": [seg(landing_text(when - timedelta(days=3)))]}}
        Service.objects.create(vessel=early, service_type="Crew Change", status="cancelled", cancel_reason="x",
                               data={"onSigners": [person], "offSigners": []})
        status, alerts = self.call(self.login("admin"), "get", "/api/vessels/alerts/")
        self.assertEqual(status, 200)
        self.assertNotIn(past.id, [row["id"] for row in alerts["missing"]])
        self.assertNotIn(early.id, [row["id"] for row in alerts["early"]])
        Service.objects.filter(vessel__in=[past, early]).update(status="in_progress", cancel_reason="")
        _, alerts = self.call(self.login("admin"), "get", "/api/vessels/alerts/")
        self.assertIn(past.id, [row["id"] for row in alerts["missing"]])
        self.assertIn(early.id, [row["id"] for row in alerts["early"]])
