"""The Services page: when a service was completed, what it is missing, the list API and its Excel export."""

from .models import Service
from .tests import ApiTestCase


class CompletedAtTests(ApiTestCase):
    def add(self, client, **extra):
        status, vessel = self.call(client, "post", f"/api/vessels/{self.alex_vessel.id}/services/",
                                   {"type": "Landing", "data": {"entries": []}, **extra})
        self.assertEqual(status, 201, vessel)
        return vessel["services"][-1]

    def put(self, client, service_id, **extra):
        status, vessel = self.call(client, "put", f"/api/services/{service_id}/",
                                   {"type": "Landing", "data": {"entries": []}, **extra})
        self.assertEqual(status, 200, vessel)
        return next(s for s in vessel["services"] if s["id"] == service_id)

    def stored(self, service_id):
        return Service.objects.get(pk=service_id).completed_at

    def test_new_completed_service_gets_time(self):
        service = self.add(self.login("alex"), status="completed")
        self.assertIsNotNone(self.stored(service["id"]))
        self.assertEqual(service["completed_at"], self.stored(service["id"]).isoformat())

    def test_completed_at_follows_status(self):
        alex = self.login("alex")
        service = self.add(alex)
        self.assertIsNone(self.stored(service["id"]))
        self.put(alex, service["id"], status="completed")
        first = self.stored(service["id"])
        self.assertIsNotNone(first)
        self.put(alex, service["id"], status="completed", agent="")
        self.assertEqual(self.stored(service["id"]), first)
        self.put(alex, service["id"], status="in_progress")
        self.assertIsNone(self.stored(service["id"]))
        self.put(alex, service["id"], status="completed")
        self.assertIsNotNone(self.stored(service["id"]))
        self.assertGreaterEqual(self.stored(service["id"]), first)

    def test_cancelled_has_none(self):
        service = self.add(self.login("alex"), status="cancelled", cancel_reason="Owner cancelled")
        self.assertIsNone(self.stored(service["id"]))

    def test_not_from_payload(self):
        alex = self.login("alex")
        service = self.add(alex, completed_at="2020-01-01T00:00:00Z")
        self.assertIsNone(self.stored(service["id"]))
        self.put(alex, service["id"], completed_at="2020-01-01T00:00:00Z")
        self.assertIsNone(self.stored(service["id"]))
