"""Agents per job: arrival / sailing agent on a vessel, an agent on every service, the missing-agent alert."""

from datetime import UTC, date, datetime, timedelta
from unittest import mock

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext

from .constants import TIME_FIELDS, TIME_KEYS
from .models import ChangeRecord, Service, Vessel
from .tests import FAST_HASHER, NEEDED, ApiTestCase, allow


class AgentFieldTests(TestCase):
    def test_vessel_has_arrival_and_sailing_agent(self):
        vessel = Vessel.objects.create(
            name="AGENTS", date=date(2026, 11, 13), arrival_agent="DELTA", sailing_agent="NILE"
        )
        vessel.refresh_from_db()
        self.assertEqual((vessel.arrival_agent, vessel.sailing_agent), ("DELTA", "NILE"))

    def test_agents_default_to_empty(self):
        vessel = Vessel.objects.create(name="EMPTY", date=date(2026, 11, 13))
        service = Service.objects.create(vessel=vessel, service_type="Fresh Water")
        self.assertEqual((vessel.arrival_agent, vessel.sailing_agent, service.agent), ("", "", ""))

    def test_service_has_agent(self):
        vessel = Vessel.objects.create(name="SVC", date=date(2026, 11, 13))
        service = Service.objects.create(vessel=vessel, service_type="Crew Change", agent="RED SEA")
        service.refresh_from_db()
        self.assertEqual(service.agent, "RED SEA")

    def test_agent_changes_are_in_history(self):
        vessel = Vessel.objects.create(name="HIST", date=date(2026, 11, 13))
        vessel.sailing_agent = "DELTA"
        vessel.save()
        update = ChangeRecord.objects.get(object_type="vessel", object_id=vessel.id, action="update")
        self.assertEqual(update.changes, {"sailing_agent": ["", "DELTA"]})


WATER = {"cost": 10, "costCurrency": "EGP"}


@FAST_HASHER
class AgentApiTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        allow("agent", "DELTA", "NILE", "X")

    def new_vessel(self, client, **fields):
        return self.call(client, "post", "/api/vessels/", {**NEEDED, "name": "AG", "date": "2026-11-13", **fields})

    def test_create_vessel_with_agents(self):
        status, vessel = self.new_vessel(self.login("alex"), arrival_agent=" DELTA ", sailing_agent="")
        self.assertEqual(status, 201)
        self.assertEqual((vessel["arrival_agent"], vessel["sailing_agent"]), ("DELTA", ""))
        self.assertNotIn("agent", vessel)

    def test_too_long_agent_is_refused(self):
        status, body = self.new_vessel(self.login("alex"), arrival_agent="A" * 150)
        self.assertEqual(status, 400)
        self.assertIn("at most 100", body["error"])

    def test_update_keeps_or_clears_agents(self):
        alex = self.login("alex")
        _, vessel = self.new_vessel(alex, arrival_agent="DELTA")
        _, updated = self.call(alex, "put", f"/api/vessels/{vessel['id']}/",
                               {**NEEDED, "name": "AG", "date": "2026-11-13", "arrival_agent": "DELTA", "sailing_agent": "NILE"})
        self.assertEqual((updated["arrival_agent"], updated["sailing_agent"]), ("DELTA", "NILE"))

    def test_service_agent_round_trip(self):
        alex = self.login("alex")
        url = f"/api/vessels/{self.alex_vessel.id}/services/"
        status, vessel = self.call(alex, "post", url, {"type": "Fresh Water", "agent": " NILE ", "data": WATER})
        self.assertEqual(status, 201)
        service = vessel["services"][-1]
        self.assertEqual(service["agent"], "NILE")
        self.assertNotIn("agent", service["data"])
        _, vessel = self.call(alex, "put", f"/api/services/{service['id']}/",
                              {"type": "Fresh Water", "agent": "   ", "data": WATER})
        self.assertEqual(vessel["services"][-1]["agent"], "")

    def test_port_user_cannot_touch_another_ports_service(self):
        status, _ = self.call(self.login("alex"), "put", f"/api/services/{self.suez_service.id}/",
                              {"type": "Fresh Water", "agent": "X", "data": WATER})
        self.assertEqual(status, 404)

    def test_search_matches_each_agent(self):
        a = Vessel.objects.create(name="ONE", date=date(2026, 11, 13), port="alexandria", arrival_agent="ZETA ARR")
        b = Vessel.objects.create(name="TWO", date=date(2026, 11, 13), port="alexandria", sailing_agent="ZETA SAIL")
        c = Vessel.objects.create(name="THREE", date=date(2026, 11, 13), port="alexandria")
        Service.objects.create(vessel=c, service_type="Fresh Water", agent="ZETA SVC", data=WATER)
        admin = self.login("admin")
        for needle, vessel in (("zeta arr", a), ("zeta sail", b), ("zeta svc", c)):
            _, data = self.call(admin, "get", f"/api/vessels/?q={needle}")
            self.assertEqual([v["id"] for v in data["vessels"]], [vessel.id], needle)

    def test_sort_by_sailing_agent(self):
        Vessel.objects.create(name="S1", date=date(2026, 11, 13), port="alexandria", sailing_agent="B")
        Vessel.objects.create(name="S2", date=date(2026, 11, 13), port="alexandria", sailing_agent="A")
        _, data = self.call(self.login("alex"), "get", "/api/vessels/?sort=sailing_agent&dir=asc")
        names = [v["name"] for v in data["vessels"] if v["name"] in ("S1", "S2")]
        self.assertEqual(names, ["S2", "S1"])
        self.assertEqual(self.call(self.login("alex"), "get", "/api/vessels/?sort=arrival_agent")[0], 200)

    def test_old_sort_key_agent_is_rejected(self):
        self.assertEqual(self.call(self.login("alex"), "get", "/api/vessels/?sort=agent")[0], 400)

    def test_csv_has_arrival_and_sailing_agent_columns(self):
        Vessel.objects.create(name="CSV", date=date(2026, 11, 13), port="alexandria",
                              arrival_agent="DELTA", sailing_agent="NILE")
        header, *rows = self.login("admin").get("/export.csv").content.decode("utf-8-sig").splitlines()
        columns = header.split(",")
        self.assertIn("Arrival agent", columns)
        self.assertIn("Sailing agent", columns)
        self.assertNotIn("Agent", columns)
        row = next(r.split(",") for r in rows if r.startswith("CSV,"))
        self.assertEqual(row[columns.index("Arrival agent")], "DELTA")
        self.assertEqual(row[columns.index("Sailing agent")], "NILE")

    def test_usage_counts_each_vessel_once_for_any_role(self):
        admin = self.login("admin")
        self.call(admin, "post", "/api/options/", {"kind": "agent", "value": "DELTA"})
        v1 = Vessel.objects.create(name="V1", date=date(2026, 11, 13), port="alexandria", arrival_agent="DELTA")
        v2 = Vessel.objects.create(name="V2", date=date(2026, 11, 13), port="alexandria", sailing_agent="DELTA")
        v3 = Vessel.objects.create(name="V3", date=date(2026, 11, 13), port="suez")
        Service.objects.create(vessel=v2, service_type="Fresh Water", agent="DELTA", data=WATER)
        Service.objects.create(vessel=v3, service_type="Fresh Water", agent="DELTA", data=WATER)
        Service.objects.create(vessel=v3, service_type="Landing", agent="DELTA")
        Service.objects.create(vessel=v1, service_type="Landing", agent="OTHER")
        used = lambda client: next(  # noqa: E731
            o for o in self.call(client, "get", "/api/options/")[1]["options"] if o["value"] == "DELTA")["used"]
        self.assertEqual(used(admin), 3)
        self.assertEqual(used(self.login("alex")), 2)


TODAY = date(2026, 11, 18)
DAY = timedelta(days=1)
# A complete, not delayed port call (aware datetimes; the exact day doesn't matter to the alert).
_START = datetime(2026, 11, 10, 6, 0, tzinfo=UTC)
ALL_TIMES = {key: _START + timedelta(hours=i) for i, key in enumerate(TIME_KEYS)}
TIME_NAMES = [label for _, label in TIME_FIELDS]


@FAST_HASHER
@mock.patch("sheet.listing.timezone.localdate", return_value=TODAY)
class MissingAgentTests(ApiTestCase):
    def setUp(self):
        # The shared fixture vessels (13.11.2026, past) are complete, so each test sees only its own gaps.
        # Their port-call times are filled in too (the alert also asks for those: tests_alerts_details).
        Vessel.objects.update(arrival_agent="BASE", sailing_agent="BASE", **ALL_TIMES)
        Service.objects.update(agent="BASE")

    def vessel(self, name, when, port="alexandria", arrival="DELTA", sailing="NILE"):
        return Vessel.objects.create(
            name=name, date=when, port=port, arrival_agent=arrival, sailing_agent=sailing, **ALL_TIMES
        )

    def missing(self, user="admin", query=""):
        status, data = self.call(self.login(user), "get", f"/api/vessels/alerts/{query}")
        self.assertEqual(status, 200)
        return data["missing"]

    def test_past_vessel_with_every_agent_and_no_services_is_fine(self, _):
        self.vessel("COMPLETE", TODAY - DAY)
        self.assertEqual(self.missing(), [])

    def test_missing_sailing_agent(self, _):
        v = self.vessel("NO SAIL", TODAY - DAY, sailing="")
        self.assertEqual(self.missing(), [{"id": v.id, "name": "NO SAIL", "date": "2026-11-17", "missing": ["Sailing agent"]}])

    def test_blank_arrival_agent_sent_by_the_api_counts_as_missing(self, _):
        allow("agent", "NILE")
        alex = self.login("alex")
        _, sent = self.call(alex, "post", "/api/vessels/",
                            {**NEEDED, "name": "BLANK", "date": "2026-11-17", "arrival_agent": "   ", "sailing_agent": "NILE"})
        self.assertEqual([(m["id"], m["missing"]) for m in self.missing()], [(sent["id"], TIME_NAMES + ["Arrival agent"])])

    def test_services_without_agent_are_listed_once_per_type_in_order(self, _):
        v = self.vessel("SERVICES", TODAY - DAY)
        Service.objects.create(vessel=v, service_type="Others / Remarks")
        Service.objects.create(vessel=v, service_type="Crew Change")
        Service.objects.create(vessel=v, service_type="Crew Change")
        Service.objects.create(vessel=v, service_type="Fresh Water", agent="NILE")
        self.assertEqual(self.missing()[0]["missing"], ["Crew Change agent", "Others / Remarks agent"])

    def test_everything_missing_is_listed_in_order(self, _):
        v = self.vessel("ALL", TODAY - DAY, arrival="", sailing="")
        Service.objects.create(vessel=v, service_type="Landing")
        self.assertEqual(self.missing()[0]["missing"], ["Arrival agent", "Sailing agent", "Landing agent"])

    def test_today_and_later_never_count(self, _):
        for offset, name in ((0, "TODAY"), (1, "TOMORROW"), (30, "LATER")):
            v = self.vessel(name, TODAY + offset * DAY, arrival="", sailing="")
            Service.objects.create(vessel=v, service_type="Landing")
        self.assertEqual(self.missing(), [])

    def test_no_look_back_limit_and_oldest_first(self, _):
        recent = self.vessel("RECENT", TODAY - DAY, sailing="")
        old = self.vessel("OLD", TODAY - 365 * DAY, sailing="")
        self.assertEqual([m["id"] for m in self.missing()], [old.id, recent.id])

    def test_port_user_sees_only_their_port_whatever_port_they_ask(self, _):
        alex_gap = self.vessel("ALEX GAP", TODAY - DAY, sailing="")
        self.vessel("SUEZ GAP", TODAY - DAY, port="suez", sailing="")
        self.assertEqual([m["id"] for m in self.missing("alex", "?port=suez")], [alex_gap.id])

    def test_read_only_sees_every_port_and_the_port_filter_applies(self, _):
        self.vessel("ALEX GAP", TODAY - DAY, sailing="")
        suez = self.vessel("SUEZ GAP", TODAY - DAY, port="suez", sailing="")
        self.assertEqual(len(self.missing("viewer")), 2)
        self.assertEqual([m["id"] for m in self.missing("viewer", "?port=suez")], [suez.id])

    def test_the_alert_reads_only_the_columns_it_needs(self, _):
        # No look-back limit: the query must stay light as the history grows (no service data, no complete vessels).
        done = self.vessel("DONE", TODAY - DAY)
        Service.objects.create(vessel=done, service_type="Landing", agent="NILE", data={"entries": [{"awb": "X"}]})
        gap = self.vessel("GAP", TODAY - DAY, sailing="")
        Service.objects.create(vessel=gap, service_type="Landing", data={"entries": [{"awb": "Y"}]})
        client = self.login("admin")
        with CaptureQueriesContext(connection) as queries:
            status, data = self.call(client, "get", "/api/vessels/alerts/")
        self.assertEqual([m["name"] for m in data["missing"]], ["GAP"])
        # Early arrival reads crew data, but only of Crew Change services in its 60-day look-back (crewbookings).
        sql = " ".join(q["sql"] for q in queries.captured_queries if "'Crew Change'" not in q["sql"])
        self.assertNotIn('"sheet_service"."data"', sql)
