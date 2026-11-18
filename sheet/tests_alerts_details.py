"""The "Missing details" alert: past vessels missing port-call times, a needed delay reason, or an agent."""

from datetime import UTC, datetime, timedelta
from unittest import mock

from django.test import TestCase

from .listing import gap_filter
from .models import Service, Vessel
from .tests import FAST_HASHER, ApiTestCase
from .tests_agents import ALL_TIMES, DAY, TIME_NAMES, TODAY

ARRIVED = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)


@FAST_HASHER
@mock.patch("sheet.listing.timezone.localdate", return_value=TODAY)
class MissingDetailsTests(ApiTestCase):
    def setUp(self):
        Vessel.objects.update(arrival_agent="BASE", sailing_agent="BASE", **ALL_TIMES)
        Service.objects.update(agent="BASE")

    def vessel(self, name="GAP", when=TODAY - DAY, port="alexandria", **fields):
        values = {"arrival_agent": "DELTA", "sailing_agent": "NILE", **ALL_TIMES, **fields}
        return Vessel.objects.create(name=name, date=when, port=port, **values)

    def missing(self, user="admin", query=""):
        status, data = self.call(self.login(user), "get", f"/api/vessels/alerts/{query}")
        self.assertEqual(status, 200)
        return data["missing"]

    def test_missing_times_listed_in_order(self, _):
        self.vessel(**{key: None for key in ALL_TIMES})
        self.assertEqual(self.missing()[0]["missing"], ["Arrived", "Berthed", "Ops started", "Ops finished", "Sailed"])
        self.assertEqual(TIME_NAMES, ["Arrived", "Berthed", "Ops started", "Ops finished", "Sailed"])

    def test_one_missing_time(self, _):
        v = self.vessel(ops_end_at=None)
        self.assertEqual(self.missing(), [{"id": v.id, "name": "GAP", "date": "2026-11-17", "missing": ["Ops finished"]}])

    def test_complete_past_vessel_not_listed(self, _):
        self.vessel()
        self.assertEqual(self.missing(), [])

    def test_todays_vessel_not_listed(self, _):
        self.vessel(when=TODAY, **{key: None for key in ALL_TIMES})
        self.assertEqual(self.missing(), [])

    def test_old_delayed_vessel_without_reason_listed(self, _):
        self.vessel(arrival_at=ARRIVED, berthing_at=ARRIVED + timedelta(hours=3), sailing_at=None)
        self.assertEqual(self.missing()[0]["missing"], ["Sailed", "Delay reason"])

    def test_delayed_vessel_with_reason_not_listed(self, _):
        self.vessel(arrival_at=ARRIVED, berthing_at=ARRIVED + timedelta(hours=3), delay_reason="WEATHER")
        self.assertEqual(self.missing(), [])

    def test_two_hours_exactly_needs_no_reason(self, _):
        self.vessel(arrival_at=ARRIVED, berthing_at=ARRIVED + timedelta(hours=2))
        self.assertEqual(self.missing(), [])

    def test_full_order(self, _):
        v = self.vessel(ops_start_at=None, ops_end_at=None, arrival_at=ARRIVED,
                        berthing_at=ARRIVED + timedelta(hours=5), sailing_agent="")
        Service.objects.create(vessel=v, service_type="Landing")
        Service.objects.create(vessel=v, service_type="Crew Change")
        self.assertEqual(self.missing()[0]["missing"],
                         ["Ops started", "Ops finished", "Delay reason", "Sailing agent", "Crew Change agent",
                          "Landing agent"])

    def test_port_user_sees_own_port_only(self, _):
        mine = self.vessel("ALEX", sailing_at=None)
        self.vessel("SUEZ", port="suez", sailing_at=None)
        self.assertEqual([m["id"] for m in self.missing("alex", "?port=suez")], [mine.id])


class MissingDetailsQueryTests(TestCase):
    def test_database_filter_skips_complete_vessels_that_berthed_on_time(self):
        # The alert has no look-back limit: a past call with every time and agent, berthed within 2 hours, must not
        # even be read from the database (only vessels with a possible gap are).
        on_time = Vessel.objects.create(name="ON TIME", date=TODAY - DAY, arrival_agent="A", sailing_agent="B",
                                        **ALL_TIMES)
        late = Vessel.objects.create(name="LATE", date=TODAY - DAY, arrival_agent="A", sailing_agent="B",
                                     **{**ALL_TIMES, "berthing_at": ARRIVED + timedelta(hours=2, minutes=1)})
        found = set(Vessel.objects.filter(gap_filter()).values_list("pk", flat=True))
        self.assertNotIn(on_time.pk, found)
        self.assertIn(late.pk, found)
