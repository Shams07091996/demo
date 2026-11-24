"""Dashboard: jobs per agent, services per month, money per month, and the filters (dates, port, OPR, agent, type)."""

from datetime import date

from .models import HotelStay, Service, Vessel
from .serializers import month_rates, vessel_to_dict
from .tests import FAST_HASHER, ApiTestCase

WATER = {"cost": 100, "costCurrency": "EGP", "revenue": 250, "revenueCurrency": "EGP"}
CREW = {"onSigners": [{"name": "A"}, {"name": "B"}, {"name": "C"}], "offSigners": [], "cost": 40, "costCurrency": "EGP"}
NOV = "?from=2026-11-01&to=2026-11-30"


@FAST_HASHER
class DashboardFigureTests(ApiTestCase):
    def setUp(self):
        Vessel.objects.all().delete()  # start from this class's own vessels only
        self.v1 = Vessel.objects.create(name="V1", date=date(2026, 11, 10), port="alexandria", opr="MSK",
                                        arrival_agent="DELTA", sailing_agent="NILE")
        self.crew = Service.objects.create(vessel=self.v1, service_type="Crew Change", agent="DELTA", data=CREW)
        self.water = Service.objects.create(vessel=self.v1, service_type="Fresh Water", data=WATER)
        self.v2 = Vessel.objects.create(name="V2", date=date(2026, 11, 12), port="alexandria", opr="ARK",
                                        arrival_agent="DELTA")

    def dash(self, query=NOV, user="admin"):
        status, data = self.call(self.login(user), "get", f"/api/dashboard/{query}")
        self.assertEqual(status, 200, data)
        return data

    def agents(self, data):
        return {a["agent"]: a for a in data["agents"]}

    def test_jobs_per_agent(self):
        data = self.dash()
        self.assertEqual([a["agent"] for a in data["agents"]], ["DELTA", "NILE", ""])
        delta, none, nile = (self.agents(data)[k] for k in ("DELTA", "", "NILE"))
        self.assertEqual((delta["arrivals"], delta["sailings"], delta["by_type"], delta["total"]),
                         (2, 0, {"Crew Change": 1}, 3))
        self.assertEqual((nile["sailings"], nile["total"]), (1, 1))
        self.assertEqual((none["arrivals"], none["sailings"], none["by_type"], none["total"]),
                         (0, 1, {"Fresh Water": 1}, 2))
        self.assertEqual(data["service_types"], ["Crew Change", "Fresh Water"])
        self.assertEqual(data["totals"]["jobs"], 6)
        self.assertEqual(data["totals"]["services"], 2)

    def test_no_agent_is_last_even_when_busiest(self):
        for _ in range(3):
            Service.objects.create(vessel=self.v2, service_type="Landing")
        self.assertEqual(self.dash()["agents"][-1]["agent"], "")

    def test_months_zero_filled_and_money(self):
        sep = Vessel.objects.create(name="SEP", date=date(2026, 9, 5), port="alexandria")
        Service.objects.create(vessel=sep, service_type="Fresh Water", data=WATER)
        data = self.dash("?from=2026-09-01&to=2026-11-30")
        self.assertEqual([m["month"] for m in data["months"]], ["2026-09", "2026-10", "2026-11"])
        october = data["months"][1]
        self.assertEqual((october["total"], october["by_type"], october["cost_egp"], october["profit_egp"]), (0, {}, 0, 0))
        rates = month_rates()
        for month, vessels in (("2026-09", [sep]), ("2026-11", [self.v1, self.v2])):
            calcs = [s["calc"] for v in vessels for s in vessel_to_dict(v, rates)["services"]]
            entry = next(m for m in data["months"] if m["month"] == month)
            for key in ("cost_egp", "revenue_egp", "profit_egp"):
                self.assertAlmostEqual(entry[key], sum(c[key] for c in calcs), places=2)
        self.assertEqual(data["months"][2]["by_type"], {"Crew Change": 1, "Fresh Water": 1})
        self.assertAlmostEqual(data["totals"]["revenue_egp"], 500, places=2)

    def test_bookings_are_not_counted(self):
        before = self.dash()
        HotelStay.objects.create(vessel=self.v1, hotel="H", check_in=date(2026, 11, 10), nights=2,
                                 cost_per_night=1000, revenue_per_night=2000)
        after = self.dash()
        self.assertEqual(before["months"], after["months"])
        self.assertEqual(before["totals"], after["totals"])

    def test_service_filter_hides_arrivals_and_narrows_opr(self):
        data = self.dash(NOV + "&service=Fresh Water")
        self.assertEqual(data["service_types"], ["Fresh Water"])
        self.assertTrue(all(a["arrivals"] == 0 and a["sailings"] == 0 for a in data["agents"]))
        self.assertEqual([(a["agent"], a["total"]) for a in data["agents"]], [("", 1)])
        self.assertEqual([(o["opr"], o["vessels"], o["services"], o["cost_egp"]) for o in data["oprs"]],
                         [("MSK", 1, 1, 100.0)])
        self.assertEqual(data["count"], 1)

    def test_agent_filter(self):
        data = self.dash(NOV + "&agent=NILE")
        self.assertEqual([(a["agent"], a["sailings"], a["total"]) for a in data["agents"]], [("NILE", 1, 1)])
        self.assertEqual([(o["opr"], o["vessels"], o["services"], o["cost_egp"]) for o in data["oprs"]],
                         [("MSK", 1, 0, 0)])
        self.assertEqual(data["months"], [])  # no services, no money
        none = self.dash(NOV + "&agent=__none__")
        self.assertEqual([(a["agent"], a["total"]) for a in none["agents"]], [("", 2)])
        self.assertAlmostEqual(none["totals"]["cost_egp"], 100, places=2)

    def test_opr_filter(self):
        data = self.dash(NOV + "&opr=ARK")
        self.assertEqual([(a["agent"], a["total"]) for a in data["agents"]], [("DELTA", 1), ("", 1)])
        self.assertEqual(data["count"], 1)

    def test_no_filter_opr_figures_unchanged(self):
        oprs = {o["opr"]: o for o in self.dash()["oprs"]}
        self.assertEqual((oprs["ARK"]["vessels"], oprs["ARK"]["services"]), (1, 0))  # no services, still counted
        self.assertEqual(oprs["MSK"]["service_counts"], {"Crew Change (On)": 3, "Crew Change (Off)": 0, "Fresh Water": 1})

    def test_filters_lists_present_values(self):
        Vessel.objects.create(name="SUEZ", date=date(2026, 11, 11), port="suez", opr="ZIM", arrival_agent="SUEZ AG")
        data = self.dash(NOV + "&opr=ARK&agent=DELTA&service=Landing")
        self.assertEqual(data["filters"]["oprs"], ["ARK", "MSK", "ZIM"])
        self.assertEqual(data["filters"]["agents"], ["DELTA", "NILE", "SUEZ AG"])
        alex = self.dash(NOV, user="alex")
        self.assertEqual(alex["filters"]["agents"], ["DELTA", "NILE"])

    def test_port_user_pinned(self):
        Vessel.objects.create(name="SUEZ", date=date(2026, 11, 11), port="suez", arrival_agent="SUEZ AG")
        data = self.dash(NOV + "&port=suez", user="alex")
        self.assertNotIn("SUEZ AG", self.agents(data))
        self.assertEqual(data["count"], 2)

    def test_read_only_allowed(self):
        self.assertEqual(self.dash(user="viewer")["count"], 2)

    def test_bad_service_400(self):
        self.assertEqual(self.call(self.login("admin"), "get", "/api/dashboard/?service=Nope")[0], 400)

    def test_empty_range(self):
        data = self.dash("?from=2000-01-01&to=2000-01-31")
        self.assertEqual((data["count"], data["oprs"], data["agents"], data["months"]), (0, [], [], []))
        self.assertEqual(data["totals"], {"jobs": 0, "services": 0, "cost_egp": 0, "revenue_egp": 0, "profit_egp": 0})


@FAST_HASHER
class DashboardJobsTests(ApiTestCase):
    def setUp(self):
        Vessel.objects.all().delete()
        self.old = Vessel.objects.create(name="OLD", date=date(2026, 11, 1), port="alexandria", arrival_agent="DELTA")
        self.new = Vessel.objects.create(name="NEW", date=date(2026, 11, 20), port="alexandria", arrival_agent="DELTA")
        Service.objects.create(vessel=self.new, service_type="Crew Change", agent="DELTA", data=CREW)
        Vessel.objects.create(name="SUEZ", date=date(2026, 11, 21), port="suez", arrival_agent="DELTA")

    def jobs(self, query, user="admin"):
        return self.call(self.login(user), "get", f"/api/dashboard/jobs/{query}")

    def test_jobs_of_one_agent_newest_first(self):
        status, data = self.jobs(NOV + "&agent=DELTA&port=alexandria")
        self.assertEqual(status, 200)
        self.assertEqual([(j["vessel"], j["job"]) for j in data["jobs"]],
                         [("NEW", "Arrival"), ("NEW", "Crew Change"), ("OLD", "Arrival")])
        self.assertEqual(data["jobs"][0]["vessel_id"], self.new.id)
        self.assertEqual(data["jobs"][0]["date"], "2026-11-20")
        self.assertFalse(data["truncated"])

    def test_agent_is_required(self):
        self.assertEqual(self.jobs(NOV)[0], 400)

    def test_port_user_sees_own_port_only(self):
        _, data = self.jobs(NOV + "&agent=DELTA&port=suez", user="alex")
        self.assertNotIn("SUEZ", [j["vessel"] for j in data["jobs"]])

    def test_capped_at_500(self):
        Vessel.objects.bulk_create(
            [Vessel(name=f"B{i}", date=date(2026, 11, 2), port="alexandria", arrival_agent="BUSY") for i in range(501)]
        )
        _, data = self.jobs(NOV + "&agent=BUSY")
        self.assertEqual((len(data["jobs"]), data["truncated"]), (500, True))


@FAST_HASHER
class StatusCountTests(ApiTestCase):
    """Service status (In progress / Completed / Cancelled) and accounting (Open / Closed rows) per month."""

    def setUp(self):
        Vessel.objects.all().delete()
        self.v1 = Vessel.objects.create(name="V1", date=date(2026, 9, 10), port="alexandria", arrival_agent="DELTA")
        self.v2 = Vessel.objects.create(name="V2", date=date(2026, 11, 12), port="alexandria")
        Service.objects.create(vessel=self.v1, service_type="Fresh Water", agent="DELTA", status="completed",
                               data=WATER, acct_closed=True)
        Service.objects.create(vessel=self.v2, service_type="Fresh Water", agent="NILE", data=WATER)
        Service.objects.create(vessel=self.v2, service_type="Landing", agent="DELTA", status="cancelled",
                               cancel_reason="x", data={"entries": [{"cost": 1}, {"cost": 2}]})
        HotelStay.objects.create(vessel=self.v2, hotel="H", check_in=date(2026, 11, 12), nights=1,
                                 cost_per_night=5)

    def status(self, query="?from=2026-09-01&to=2026-11-30"):
        status, data = self.call(self.login("admin"), "get", f"/api/dashboard/{query}")
        self.assertEqual(status, 200, data)
        return data["status"]

    def test_status_counts_per_month(self):
        counts = self.status()
        zero = {"in_progress": 0, "completed": 0, "cancelled": 0, "open": 0, "closed": 0}
        self.assertEqual(counts["months"], [
            {"month": "2026-09", **zero, "completed": 1, "closed": 1},
            {"month": "2026-10", **zero},
            {"month": "2026-11", **zero, "in_progress": 1, "cancelled": 1, "open": 4},  # water, 2 landing, hotel
        ])
        self.assertEqual(counts["totals"], {"in_progress": 1, "completed": 1, "cancelled": 1, "open": 4, "closed": 1})

    def test_status_counts_follow_agent_filter(self):
        totals = self.status("?from=2026-09-01&to=2026-11-30&agent=DELTA")["totals"]
        # DELTA's services: V1 water (closed) and V2 landing (2 open rows); no bookings once narrowed
        self.assertEqual(totals, {"in_progress": 0, "completed": 1, "cancelled": 1, "open": 2, "closed": 1})
        self.assertEqual(self.status("?from=2026-01-01&to=2026-01-31"), {
            "months": [], "totals": {"in_progress": 0, "completed": 0, "cancelled": 0, "open": 0, "closed": 0}})
