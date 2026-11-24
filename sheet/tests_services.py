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


class MissingTests(ApiTestCase):
    """services.missing / money_gaps / sailed: what a service still lacks (a typed 0 counts as filled in)."""

    def service(self, service_type="Medical Treatment", data=None, agent="SMOKE", status="in_progress"):
        return Service.objects.create(vessel=self.alex_vessel, service_type=service_type, agent=agent, status=status,
                                      data=data if data is not None else {"cost": 1, "revenue": 2})

    def gaps(self, service, rate=None, uids=frozenset()):
        from . import services
        return services.missing(service, rate, set(uids))

    def test_agent_missing(self):
        self.assertEqual(self.gaps(self.service(agent="")), ["Agent"])

    def test_zero_is_filled_in_empty_is_missing(self):
        self.assertEqual(self.gaps(self.service(data={"cost": 0, "revenue": 0})), [])
        self.assertEqual(self.gaps(self.service(data={"cost": None, "revenue": 5})), ["Cost"])
        self.assertEqual(self.gaps(self.service(data={"revenue": 5})), ["Cost"])
        landing = self.service("Landing", {"entries": [{"cost": 3, "revenue": 4}, {"cost": None, "revenue": 4}]})
        self.assertEqual(self.gaps(landing), ["Cost"])
        self.assertEqual(self.gaps(self.service("Landing", {"entries": []})), ["Cost", "Revenue"])

    def test_cash_to_master_boxes(self):
        ctm = lambda **d: self.service("Cash to Master", {"amount": 100, "shareMode": "percent", "percentage": 5, **d})  # noqa: E731
        self.assertEqual(self.gaps(ctm()), [])
        self.assertEqual(self.gaps(ctm(amount=None)), ["Revenue"])
        self.assertEqual(self.gaps(ctm(percentage=None)), ["Revenue"])
        self.assertEqual(self.gaps(ctm(shareMode="fixed", fixedRevenue=None)), ["Revenue"])
        self.assertEqual(self.gaps(ctm(shareMode="fixed", fixedRevenue=0, percentage=None)), [])

    def test_rate_missing_for_usd_without_rate(self):
        usd = self.service(data={"cost": 1, "revenue": 2, "revenueCurrency": "USD"})
        self.assertEqual(self.gaps(usd), ["Rate"])
        self.assertEqual(self.gaps(usd, rate=50), [])

    def test_crew_change_draft_booking_is_missing_bookings(self):
        from . import services
        from .models import Transfer
        crew = {"onSigners": [{"name": "Ahmed Test", "rank": "AB"}], "offSigners": [], "cost": 1, "revenue": 1}
        status, vessel = self.call(self.login("alex"), "post", f"/api/vessels/{self.alex_vessel.id}/services/",
                                   {"type": "Crew Change", "agent": "", "data": crew})
        self.assertEqual(status, 201, vessel)
        change = Service.objects.get(pk=vessel["services"][-1]["id"])
        uids = services.incomplete_crew_uids([self.alex_vessel.id])
        self.assertEqual(self.gaps(change, uids=uids), ["Agent", "Bookings"])
        Transfer.objects.filter(vessel=self.alex_vessel).update(draft=False, cost=0, revenue=0)
        self.assertEqual(self.gaps(change, uids=services.incomplete_crew_uids([self.alex_vessel.id])), ["Agent"])
        Transfer.objects.filter(vessel=self.alex_vessel).update(cost=None, cancelled=True)
        self.assertEqual(services.incomplete_crew_uids([self.alex_vessel.id]), set())

    def test_cancelled_never_missing(self):
        self.assertEqual(self.gaps(self.service(agent="", data={}, status="cancelled")), [])

    def test_order_of_labels(self):
        both = self.service(agent="", data={"revenueCurrency": "USD", "revenue": 3})
        self.assertEqual(self.gaps(both), ["Agent", "Cost", "Rate"])

    def test_sailed_rules(self):
        from datetime import date, datetime, timedelta
        from datetime import timezone as tz

        from . import services
        now = datetime(2026, 11, 24, 12, 0, tzinfo=tz.utc)
        today = date(2026, 11, 24)
        v = self.alex_vessel
        v.sailing_at, v.date = now - timedelta(hours=1), today
        self.assertTrue(services.sailed(v, today, now))
        v.sailing_at = now + timedelta(hours=1)
        self.assertFalse(services.sailed(v, today, now))
        v.sailing_at, v.date = None, today - timedelta(days=1)
        self.assertTrue(services.sailed(v, today, now))
        v.date = today
        self.assertFalse(services.sailed(v, today, now))
