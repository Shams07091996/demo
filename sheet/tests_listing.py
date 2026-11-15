"""Server-side vessel list: date range, search, buckets, sorting, paging, totals, alerts, dashboard, bulk check."""

from datetime import date
from unittest import mock

from .models import Service, Vessel
from .tests import ApiTestCase


class ListingData(ApiTestCase):
    """Adds Alexandria vessels to the base data (ALEX SHIP 13.11, SUEZ SHIP 13.11 in Suez)."""

    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        ark = Vessel.objects.create(name="ARK ONE", opr="ark ", date=date(2026, 11, 2), port="alexandria")
        Service.objects.create(
            vessel=ark,
            service_type="Fresh Water",
            data={"cost": 100, "costCurrency": "EGP", "revenue": 150, "revenueCurrency": "EGP"},
        )
        Service.objects.create(
            vessel=ark,
            service_type="Crew Change",
            data={"onSigners": [{"name": "A"}, {"name": "B"}], "offSigners": [{"name": "C"}]},
        )
        Vessel.objects.create(name="MSK TWO", opr="MSK", date=date(2026, 11, 20), port="alexandria")
        old = Vessel.objects.create(name="OLD SHIP", opr="CMA", date=date(2026, 10, 31), port="alexandria")
        Service.objects.create(
            vessel=old,
            service_type="Landing",
            data={"entries": [{"cost": 50, "costCurrency": "EGP", "revenue": 60, "revenueCurrency": "EGP"}]},
        )

    def _get(self, user, url, params):
        client = self.login(user)
        return client.get(url, params)

    def get(self, user, **params):
        response = self._get(user, "/api/vessels/", params)
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def status(self, user, **params):
        return self._get(user, "/api/vessels/", params).status_code


def names(data):
    return sorted(v["name"] for v in data["vessels"])


class ListingTests(ListingData):
    def test_range_is_inclusive_and_open_ended(self):
        self.assertEqual(
            names(self.get("admin", **{"from": "2026-11-02", "to": "2026-11-20", "port": "alexandria"})),
            ["ALEX SHIP", "ARK ONE", "MSK TWO"],
        )
        self.assertIn("OLD SHIP", names(self.get("admin", to="2026-10-31")))
        self.assertNotIn("OLD SHIP", names(self.get("admin", **{"from": "2026-11-01"})))

    def test_reversed_or_invalid_dates_are_rejected(self):
        for params in ({"from": "2026-12-01", "to": "2026-11-01"}, {"from": "13.11.2026"}):
            self.assertEqual(self.status("admin", **params), 400)

    def test_search_matches_fields_and_service_types_literally(self):
        self.assertEqual(names(self.get("admin", q="landing")), ["OLD SHIP"])
        self.assertEqual(names(self.get("admin", q="  msk ")), ["MSK TWO"])
        self.assertEqual(self.get("admin", q="   ")["count"], self.get("admin")["count"])
        self.assertEqual(self.get("admin", q="%")["count"], 0)
        self.assertEqual(self.get("admin", q="_")["count"], 0)

    def test_bucket_uses_trimmed_upper_case_opr(self):
        self.assertEqual(names(self.get("admin", bucket="ARK")), ["ARK ONE"])
        self.assertEqual(names(self.get("admin", bucket="SERVICES")), ["ARK ONE", "OLD SHIP", "SUEZ SHIP"])
        self.assertEqual(names(self.get("admin", bucket="OTH")), ["ALEX SHIP", "OLD SHIP", "SUEZ SHIP"])

    def test_totals_ignore_search_and_bucket_but_follow_range(self):
        base = {"from": "2026-11-01", "to": "2026-11-30", "port": "alexandria"}
        full = self.get("admin", **base)
        narrowed = self.get("admin", **base, q="MSK", bucket="MSK")
        self.assertEqual(full["totals"], narrowed["totals"])
        self.assertEqual(narrowed["count"], 1)
        self.assertEqual(
            full["totals"],
            {"vessels": 3, "ark": 1, "msk": 1, "oth": 1, "with_services": 1, "cost_egp": 100.0, "profit_egp": 50.0},
        )

    def test_sorting_by_cost_and_stable_ties(self):
        rows = self.get("admin", port="alexandria", sort="total_cost_egp", dir="desc")["vessels"]
        self.assertEqual([v["name"] for v in rows[:2]], ["ARK ONE", "OLD SHIP"])
        ids = [v["id"] for v in self.get("admin", sort="port", dir="asc")["vessels"] if v["port"] == "alexandria"]
        self.assertEqual(ids, sorted(ids, reverse=True))
        self.assertEqual(self.get("admin", sort="name", dir="asc")["vessels"][0]["name"], "ALEX SHIP")

    def test_default_order_is_newest_date_first(self):
        dates = [v["date"] for v in self.get("admin")["vessels"]]
        self.assertEqual(dates, sorted(dates, reverse=True))

    def test_paging_and_bad_parameters(self):
        page = self.get("admin", page_size=2, page=2)
        self.assertEqual((page["page"], page["page_size"], len(page["vessels"])), (2, 2, 2))  # 5 vessels in all
        self.assertEqual((page["count"], page["pages"]), (5, 3))
        past = self.get("admin", page=99)
        self.assertEqual(past["vessels"], [])
        self.assertEqual(past["totals"]["vessels"], 5)
        self.assertEqual(self.get("admin")["page_size"], 50)
        for params in ({"page": "0"}, {"page": "abc"}, {"page_size": "500"}, {"page_size": "0"},
                       {"sort": "data"}, {"dir": "up"}, {"bucket": "XYZ"}):
            self.assertEqual(self.status("admin", **params), 400, params)

    def test_port_users_cannot_widen_their_port(self):
        data = self.get("suezuser", port="alexandria")
        self.assertEqual({v["port"] for v in data["vessels"]}, {"suez"})
        self.assertEqual(data["totals"]["vessels"], 1)


class CsvFilterTests(ListingData):
    def test_exact_opr_filter(self):
        self.assertEqual(names(self.get("admin", opr="MSK")), ["MSK TWO"])
        self.assertEqual(self.get("admin", opr="msk")["count"], 0)
        self.assertEqual(names(self.get("admin", opr="ark ")), ["ARK ONE"])

    def test_csv_exports_all_matches_not_one_page(self):
        client = self.login("admin")
        params = {"from": "2026-11-01", "to": "2026-11-30", "port": "alexandria", "page_size": "1"}
        body = client.get("/export.csv", params).content.decode("utf-8-sig")
        lines = body.strip().splitlines()
        self.assertEqual(len(lines), 1 + 3)  # header + ALEX SHIP, ARK ONE, MSK TWO
        self.assertTrue(lines[1].startswith("MSK TWO,"))  # newest first, like the table
        self.assertIn("20.11.2026", lines[1])

    def test_csv_search_and_bad_filters(self):
        client = self.login("admin")
        body = client.get("/export.csv", {"q": "landing"}).content.decode("utf-8-sig")
        self.assertEqual(len(body.strip().splitlines()), 2)
        self.assertEqual(client.get("/export.csv", {"from": "x"}).status_code, 400)

    def test_csv_port_user_stays_in_own_port(self):
        body = self.login("suezuser").get("/export.csv", {"port": "alexandria"}).content.decode("utf-8-sig")
        self.assertEqual([line.split(",")[0] for line in body.strip().splitlines()[1:]], ["SUEZ SHIP"])


TODAY = date(2026, 11, 13)


@mock.patch("sheet.listing.timezone.localdate", return_value=TODAY)
class AlertsTests(ListingData):
    def alerts(self, user, query=""):
        status, data = self.call(self.login(user), "get", f"/api/vessels/alerts/{query}")
        self.assertEqual(status, 200)
        return data

    def test_alerts_use_cairo_today_and_ignore_the_range(self, _):
        data = self.alerts("admin", "?from=2020-01-01&to=2020-01-31&q=nothing")
        self.assertEqual({v["name"] for v in data["today"]}, {"ALEX SHIP", "SUEZ SHIP"})
        self.assertEqual(data["tomorrow"], [])

    def test_tomorrow_and_port_filter(self, _):
        Vessel.objects.create(name="NEXT DAY", date=date(2026, 11, 14), port="suez")
        data = self.alerts("admin", "?port=suez")
        self.assertEqual([v["name"] for v in data["today"]], ["SUEZ SHIP"])
        self.assertEqual([v["name"] for v in data["tomorrow"]], ["NEXT DAY"])

    def test_port_user_alerts_are_scoped(self, _):
        data = self.alerts("alex", "?port=suez")
        self.assertEqual({v["port"] for v in data["today"]}, {"alexandria"})


class DashboardTests(ListingData):
    def dash(self, user, query=""):
        return self.call(self.login(user), "get", f"/api/dashboard/{query}")

    def test_dashboard_equals_sum_of_vessel_figures(self):
        status, dash = self.dash("admin", "?from=2026-11-01&to=2026-11-30")
        self.assertEqual(status, 200)
        rows = self.get("admin", **{"from": "2026-11-01", "to": "2026-11-30", "page_size": 200})["vessels"]
        self.assertEqual(dash["count"], len(rows))
        self.assertEqual([e["opr"] for e in dash["oprs"]], ["MSK", "ark "])  # blank OPR left out, sorted
        for entry in dash["oprs"]:
            mine = [v for v in rows if v["opr"] == entry["opr"]]
            self.assertEqual(entry["vessels"], len(mine))
            self.assertEqual(entry["services"], sum(len(v["services"]) for v in mine))
            self.assertAlmostEqual(entry["cost_egp"], sum(v["total_cost_egp"] for v in mine), places=2)
            self.assertAlmostEqual(entry["profit_egp"], sum(v["total_profit_egp"] for v in mine), places=2)

    def test_crew_change_counts_signers(self):
        ark = self.dash("admin", "?from=2026-11-01&to=2026-11-30")[1]["oprs"][1]
        self.assertEqual(
            ark["service_counts"], {"Fresh Water": 1, "Crew Change (On)": 2, "Crew Change (Off)": 1}
        )

    def test_dashboard_is_port_scoped_and_validates_dates(self):
        self.assertEqual(self.dash("alex", "?port=suez")[1]["count"], Vessel.objects.filter(port="alexandria").count())
        self.assertEqual(self.dash("admin", "?from=bad")[0], 400)
        self.assertEqual(self.dash("admin", "?from=2026-12-01&to=2026-11-01")[0], 400)


class BulkCheckTests(ListingData):
    URL = "/api/vessels/bulk/check/"

    def test_duplicates_are_found_in_the_target_port_only(self):
        admin = self.login("admin")
        rows = [{"name": " alex ship ", "date": "2026-11-13"}, {"name": "NEW", "date": "2026-11-13"}]
        self.assertEqual(self.call(admin, "post", self.URL, {"rows": rows, "port": "alexandria"}), (200, {"existing": [0]}))
        self.assertEqual(self.call(admin, "post", self.URL, {"rows": rows, "port": "suez"}), (200, {"existing": []}))

    def test_same_name_other_date_is_not_a_duplicate_and_bad_rows_are_skipped(self):
        rows = [{"name": "ALEX SHIP", "date": "2026-11-14"}, {"name": "ALEX SHIP", "date": "nope"}, "junk"]
        self.assertEqual(self.call(self.login("alex"), "post", self.URL, {"rows": rows})[1], {"existing": []})

    def test_port_user_checks_own_port_and_viewer_is_refused(self):
        rows = [{"name": "SUEZ SHIP", "date": "2026-11-13"}]
        self.assertEqual(self.call(self.login("alex"), "post", self.URL, {"rows": rows, "port": "suez"})[1],
                         {"existing": []})
        self.assertEqual(self.call(self.login("suezuser"), "post", self.URL, {"rows": rows})[1], {"existing": [0]})
        self.assertEqual(self.call(self.login("viewer"), "post", self.URL, {"rows": rows})[0], 403)

    def test_limits_and_unknown_port(self):
        admin = self.login("admin")
        rows = [{"name": "X", "date": "2026-11-13"}]
        self.assertEqual(self.call(admin, "post", self.URL, {"rows": rows * 201, "port": "suez"})[0], 400)
        self.assertEqual(self.call(admin, "post", self.URL, {"rows": rows, "port": "mars"})[0], 400)
        self.assertEqual(self.call(admin, "post", self.URL, {"rows": "x", "port": "suez"})[0], 400)
        self.assertEqual(self.call(admin, "post", self.URL, {"rows": [], "port": "suez"}), (200, {"existing": []}))
