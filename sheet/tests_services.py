"""The Services page: when a service was completed, what it is missing, the list API and its Excel export."""

from datetime import UTC, datetime

from .models import Service
from .serializers import local_iso
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
        self.assertEqual(service["completed_at"], local_iso(self.stored(service["id"])))

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

    def test_completed_before_tracking_stays_without_time(self):
        """A service completed before migration 0022 has no time; editing it must not stamp today's date on it."""
        alex = self.login("alex")
        service = self.add(alex, status="completed")
        Service.objects.filter(pk=service["id"]).update(completed_at=None)
        self.put(alex, service["id"], status="completed", agent="")
        self.assertIsNone(self.stored(service["id"]))
        self.assertEqual(Service.objects.get(pk=service["id"]).version, 1)

    def test_completed_time_is_cairo_local(self):
        alex = self.login("alex")
        service = self.add(alex, status="completed")
        Service.objects.filter(pk=service["id"]).update(completed_at=datetime(2026, 11, 24, 23, 30, tzinfo=UTC))
        status, vessel = self.call(alex, "get", f"/api/vessels/{self.alex_vessel.id}/")
        self.assertEqual(next(s for s in vessel["services"] if s["id"] == service["id"])["completed_at"],
                         "2026-11-25T01:30")
        status, data = self.call(alex, "get", "/api/services/?status=completed")
        self.assertEqual(next(r for r in rows(data) if r["id"] == service["id"])["completed_at"],
                         "2026-11-25T01:30")

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
        crew = {"onSigners": [{"name": "Ahmed Test", "rank": "AB", "needsTransport": True}], "offSigners": [], "cost": 1, "revenue": 1}
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

        from . import services
        now = datetime(2026, 11, 24, 12, 0, tzinfo=UTC)
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


def rows(body):
    """Every service row of a grouped list response, in order."""
    return [r for group in body["vessels"] for r in group["services"]]


class ServiceListTests(ApiTestCase):
    """GET /api/services/: the work list, its filters, scoping and paging."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        from datetime import date

        from .models import Vessel
        Service.objects.all().delete()  # the shared fixture's own service: each test makes exactly what it lists
        cls.old =Vessel.objects.create(name="OLD ONE", date=date(2026, 11, 1), port="alexandria")
        cls.mk = lambda vessel, t="Medical Treatment", agent="AG", status="in_progress", data=None, **kw: (  # noqa: E731
            Service.objects.create(vessel=vessel, service_type=t, agent=agent, status=status,
                                   data=data if data is not None else {"cost": 1, "revenue": 1}, **kw))

    def get(self, user="admin", **params):
        from urllib.parse import urlencode
        status, body = self.call(self.login(user), "get", f"/api/services/?{urlencode(params)}")
        return status, body

    def ids(self, user="admin", **params):
        status, body = self.get(user, **params)
        self.assertEqual(status, 200, body)
        return [r["id"] for r in rows(body)]

    def test_defaults_to_in_progress_oldest_first(self):
        a = self.mk(self.alex_vessel)
        b = self.mk(self.old)
        self.mk(self.old, status="completed")
        self.assertEqual(self.ids(), [b.id, a.id])
        _, body = self.get()
        row = rows(body)[0]
        self.assertEqual((row["vessel"]["name"], row["type"], row["status"], row["missing"]),
                         ("OLD ONE", "Medical Treatment", "in_progress", []))
        self.assertTrue(row["sailed"])

    def test_status_list_and_junk(self):
        a = self.mk(self.alex_vessel)
        c = self.mk(self.alex_vessel, status="cancelled", cancel_reason="x")
        self.assertEqual(sorted(self.ids(status="in_progress,cancelled,")), sorted([a.id, c.id]))
        self.assertEqual(self.get(status="done")[0], 400)

    def test_missing_only(self):
        self.mk(self.alex_vessel)
        gap = self.mk(self.alex_vessel, agent="")
        self.assertEqual(self.ids(missing="1"), [gap.id])

    def test_type_agent_none_and_search(self):
        a = self.mk(self.alex_vessel, t="Landing", data={"entries": [{"cost": 1, "revenue": 1}]})
        b = self.mk(self.old, agent="")
        self.assertEqual(self.ids(type="Landing"), [a.id])
        self.assertEqual(self.get(type="Nope")[0], 400)
        self.assertEqual(self.ids(agent="__none__"), [b.id])
        self.assertEqual(self.ids(agent="AG"), [a.id])
        self.assertEqual(self.ids(q="old o"), [b.id])

    def test_vessel_date_range(self):
        self.mk(self.alex_vessel)
        b = self.mk(self.old)
        self.assertEqual(self.ids(**{"from": "2026-10-01", "to": "2026-11-05"}), [b.id])
        self.assertEqual(self.get(**{"from": "nope"})[0], 400)

    def test_completed_range_uses_completed_date(self):
        from datetime import datetime
        inside = self.mk(self.old, status="completed", completed_at=datetime(2026, 11, 20, 9, tzinfo=UTC))
        guess = self.mk(self.alex_vessel, status="completed")  # before tracking: its vessel date (13.11) counts
        self.mk(self.alex_vessel, status="completed", completed_at=datetime(2026, 10, 2, 9, tzinfo=UTC))
        found = self.ids(status="completed", **{"from": "2026-11-10", "to": "2026-11-21"})
        self.assertEqual(found, [inside.id, guess.id])  # newest first
        _, body = self.get(status="completed", **{"from": "2026-11-10", "to": "2026-11-21"})
        self.assertEqual([r["completed_guess"] for r in rows(body)], [False, True])
        # Mixed statuses: the vessel date again (OLD ONE is dated 1.11).
        self.assertNotIn(inside.id, self.ids(status="completed,in_progress", **{"from": "2026-11-10"}))

    def test_port_user_pinned_to_own_port(self):
        a = self.mk(self.alex_vessel)
        self.mk(self.suez_vessel)
        self.assertEqual(self.ids("alex", port="suez"), [a.id])

    def test_users_read_their_ports(self):
        a = self.mk(self.alex_vessel)
        s = self.mk(self.suez_vessel)
        self.assertEqual(sorted(self.ids("admin")), sorted([a.id, s.id]))
        self.assertEqual(self.ids("viewer"), [a.id])

    def test_paging_and_agents(self):
        for i in range(3):
            self.mk(self.alex_vessel, agent=f"AG{i % 2}")
        _, body = self.get(agent="AG1")
        self.assertEqual(body["agents"], ["AG0", "AG1"])

    def test_grouped_by_vessel_matching_only(self):
        a = self.mk(self.alex_vessel)
        self.mk(self.alex_vessel, status="completed")
        b = self.mk(self.old)
        _, body = self.get()
        self.assertEqual([g["vessel"]["name"] for g in body["vessels"]], ["OLD ONE", "ALEX SHIP"])
        self.assertEqual([[r["id"] for r in g["services"]] for g in body["vessels"]], [[b.id], [a.id]])
        self.assertEqual((body["count"], body["services_count"]), (2, 2))

    def test_pages_count_vessels(self):
        from datetime import date

        from .models import Vessel
        third = Vessel.objects.create(name="THIRD", date=date(2026, 11, 20), port="alexandria")
        for vessel in (self.old, self.alex_vessel, third):
            self.mk(vessel)
            self.mk(vessel)
        _, body = self.get(page_size="2")
        self.assertEqual((body["count"], body["services_count"], body["pages"]), (3, 6, 2))
        self.assertEqual((len(body["vessels"]), len(rows(body))), (2, 4))
        _, body = self.get(page_size="2", page="2")
        self.assertEqual([g["vessel"]["name"] for g in body["vessels"]], ["THIRD"])

    def test_only_completed_newest_vessel_first(self):
        from datetime import datetime
        self.mk(self.old, status="completed", completed_at=datetime(2026, 11, 25, 9, tzinfo=UTC))
        self.mk(self.alex_vessel, status="completed", completed_at=datetime(2026, 11, 14, 9, tzinfo=UTC))
        _, body = self.get(status="completed")
        self.assertEqual([g["vessel"]["name"] for g in body["vessels"]], ["OLD ONE", "ALEX SHIP"])

    def test_vessel_carries_opr_terminal_berth(self):
        from .models import Vessel
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(opr="MSK", terminal="AICT", berth="B7")
        self.mk(self.alex_vessel)
        _, body = self.get()
        v = body["vessels"][0]["vessel"]
        self.assertEqual((v["opr"], v["terminal"], v["berth"]), ("MSK", "AICT", "B7"))

    def test_list_query_count_is_fixed(self):
        from django.db import connection
        from django.test.utils import CaptureQueriesContext
        client = self.login("admin")

        def count():
            with CaptureQueriesContext(connection) as ctx:
                self.assertEqual(self.call(client, "get", "/api/services/")[0], 200)
            return len(ctx.captured_queries)

        self.mk(self.alex_vessel)
        few = count()
        for _ in range(8):
            self.mk(self.old)
            self.mk(self.suez_vessel, t="Crew Change", data={"onSigners": [], "offSigners": []})
        self.assertEqual(count(), few)


class ServiceExportTests(ApiTestCase):
    """GET /api/export/services/: the page's filtered rows, every page of them, as a plain table."""

    HEAD = ["Vessel", "Date", "Service", "Agent", "Status", "Missing"]

    def export(self, user, query=""):
        from .tests_dataexport import read, table
        response = self.login(user).get(f"/api/export/services/?{query}")
        self.assertEqual(response.status_code, 200)
        return table(next(iter(read(response.content).values())))

    def test_services_export_header_and_rows(self):
        Service.objects.all().delete()
        gap = Service.objects.create(vessel=self.alex_vessel, service_type="Landing", agent="",
                                     data={"entries": [{"cost": 1, "revenue": None}]})
        Service.objects.create(vessel=self.suez_vessel, service_type="Medical Treatment", agent="AG",
                               data={"cost": 1, "revenue": 1})
        Service.objects.create(vessel=self.alex_vessel, service_type="Certificates", status="completed",
                               data={"cost": 1, "revenue": 1})
        rows = self.export("admin", "page_size=1&page=2")
        self.assertEqual(rows[0], self.HEAD)
        self.assertEqual(len(rows), 3)  # both in-progress services: every page, not page 2 of 1
        self.assertEqual(rows[1], ["ALEX SHIP", rows[1][1], "Landing", None, "In progress · Sailed",
                                   "Agent, Revenue"])
        self.assertEqual(self.export("admin", "status=completed")[0],
                         ["Vessel", "Date", "Service", "Agent", "Status", "Completed", "Missing"])
        self.assertTrue(gap.id)
        self.assertEqual(len(self.export("alex")), 2)  # a port user: only their port
        self.assertEqual(len(self.export("admin", "missing=1")), 2)

    def test_all_data_still_five_sheets(self):
        from .tests_dataexport import read
        response = self.login("admin").get("/api/export/all/?from=2026-11-01&to=2026-11-30")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(read(response.content)),
                         ["Hotels", "Transport", "Port closures", "Garbage & Sludge", "Calculations"])
