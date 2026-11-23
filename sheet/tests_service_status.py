"""Operations status of a service (In progress / Completed / Cancelled with a reason) and what Cancelled does."""

import importlib

from django.apps import apps

from .models import ChangeRecord, Service
from .tests import ApiTestCase

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
