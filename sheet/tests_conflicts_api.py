"""Edit conflicts through the API: a save sent with an old version is refused (409), nothing is saved."""

import json
from datetime import date
from types import SimpleNamespace

from django.contrib.admin.sites import site
from django.test import RequestFactory
from django.utils import timezone

from . import conflicts
from .admin import HotelStayAdmin, ServiceInline, VesselAdmin
from .models import Guest, HotelStay, PortClosure, Service, Transfer, Vessel
from .tests import NEEDED, ApiTestCase, allow
from .tests_conflicts import as_user

GUESTS = [{"name": "ahmed test", "rank": "2/E", "group": "on"}]


class ConflictApiTests(ApiTestCase):
    def setUp(self):
        allow("hotel", "HILTON")
        allow("airport", "BORG EL ARAB")
        allow("closure", "WEATHER")
        Vessel.objects.filter(pk=self.alex_vessel.pk).update(**NEEDED)
        self.alex = self.login("alex")
        self.admin = self.login("admin")
        self.stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="HILTON", check_in=date(2026, 11, 14),
                                             nights=2)
        Guest.objects.create(stay=self.stay, name="AHMED TEST", rank="2/E", group="on")
        self.trip = Transfer.objects.create(vessel=self.alex_vessel, from_place="airport", to_place="hotel",
                                            airport="BORG EL ARAB", hotel="HILTON", at=timezone.now())
        self.closure = PortClosure.objects.create(port="alexandria", start_at=timezone.now(), reason="WEATHER")
        self.service = Service.objects.create(vessel=self.alex_vessel, service_type="Fresh Water",
                                              data={"cost": 10, "costCurrency": "EGP"})

    def raw(self, client, method, url, payload):
        """A request exactly as given (ApiTestCase.call adds the current version to updates by itself)."""
        response = getattr(client, method)(url, data=json.dumps(payload), content_type="application/json",
                                           HTTP_X_CSRFTOKEN=client.cookies["csrftoken"].value)
        return response.status_code, response.json()

    def vessel_body(self, **o):
        return {**NEEDED, "name": "ALEX SHIP", "date": "2026-11-13", "port": "alexandria", **o}

    def updates(self):
        """(url, a valid body) for each of the five records."""
        return [
            (f"/api/vessels/{self.alex_vessel.id}/", self.vessel_body(name="RENAMED")),
            (f"/api/services/{self.service.id}/", {"type": "Fresh Water", "data": {"cost": 20, "costCurrency": "EGP"}}),
            (f"/api/hotels/{self.stay.id}/", {"vessel": self.alex_vessel.id, "hotel": "HILTON",
                                              "check_in": "2026-11-14", "nights": 3, "guests": GUESTS}),
            (f"/api/transfers/{self.trip.id}/", {"vessel": self.alex_vessel.id, "from_place": "airport",
                                                 "to_place": "hotel", "airport": "BORG EL ARAB", "hotel": "HILTON",
                                                 "at": "2026-11-14T14:30", "guests": GUESTS}),
            (f"/api/closures/{self.closure.id}/", {"port": "alexandria", "start_at": "2026-11-13T06:00",
                                                   "reason": "WEATHER", "notes": "wind"}),
        ]

    def test_update_returns_new_version(self):
        for url, body in self.updates():
            with self.subTest(url=url):
                status, data = self.raw(self.alex, "put", url, {**body, "version": 1})
                self.assertEqual(status, 200, data)
                if "/services/" in url:
                    data = next(s for s in data["services"] if s["id"] == self.service.id)
                self.assertEqual(data["version"], 2)

    def test_stale_version_refused_nothing_saved(self):
        url = f"/api/vessels/{self.alex_vessel.id}/"
        self.assertEqual(self.raw(self.alex, "put", url, {**self.vessel_body(name="FIRST"), "version": 1})[0], 200)
        status, data = self.raw(self.admin, "put", url, {**self.vessel_body(name="SECOND", poc=""), "version": 1})
        self.assertEqual(status, 409)
        self.assertEqual(data["error"], "conflict")
        found = data["conflict"]
        self.assertEqual((found["who"], found["same_person"], found["version"]), ("alex", False, 2))
        self.assertEqual(found["fields"], ["Name"])
        self.alex_vessel.refresh_from_db()
        self.assertEqual((self.alex_vessel.name, self.alex_vessel.version), ("FIRST", 2))

    def test_stale_version_refused_on_every_record(self):
        for url, body in self.updates():
            with self.subTest(url=url):
                self.assertEqual(self.raw(self.alex, "put", url, {**body, "version": 1})[0], 200)
                self.assertEqual(self.raw(self.admin, "put", url, {**body, "version": 1})[0], 409)

    def test_missing_version_is_out_of_date(self):
        for url, body in self.updates():
            for version in (None, "1", 0, True):
                with self.subTest(url=url, version=version):
                    sent = body if version is None else {**body, "version": version}
                    status, data = self.raw(self.alex, "put", url, sent)
                    self.assertEqual((status, data["error"]), (400, conflicts.OUT_OF_DATE))
        self.alex_vessel.refresh_from_db()
        self.assertEqual((self.alex_vessel.name, self.alex_vessel.version), ("ALEX SHIP", 1))

    def test_patch_needs_version_too(self):
        url = f"/api/vessels/{self.alex_vessel.id}/"
        self.assertEqual(self.raw(self.alex, "patch", url, {"name": "X"})[0], 400)

    def test_same_values_no_bump(self):
        url = f"/api/vessels/{self.alex_vessel.id}/"
        status, data = self.raw(self.alex, "put", url, {**self.vessel_body(), "version": 1})
        self.assertEqual((status, data["version"]), (200, 1))

    def test_unchanged_resave_of_every_record_keeps_its_version(self):
        """Times (UTC in the database, Cairo from the form) and amounts (50 vs 50.0000) that are equal are no change."""
        resaves = [
            (f"/api/vessels/{self.alex_vessel.id}/", self.vessel_body(arrival_at="2026-11-13T06:00",
                                                                     berthing_at="2026-11-13T07:00")),
            (f"/api/transfers/{self.trip.id}/", {**self.updates()[3][1], "exchange_rate": "50", "cost": "12.5",
                                                 "cost_currency": "USD"}),
            (f"/api/hotels/{self.stay.id}/", {**self.updates()[2][1], "cost_per_night": "80", "exchange_rate": "50.0"}),
            (f"/api/closures/{self.closure.id}/", {**self.updates()[4][1], "end_at": "2026-11-13T14:00"}),
        ]
        for url, body in resaves:
            with self.subTest(url=url):
                status, first = self.raw(self.alex, "put", url, {**body, "version": 1})
                self.assertEqual(status, 200, first)
                status, again = self.raw(self.alex, "put", url, {**body, "version": first["version"]})
                self.assertEqual((status, again["version"]), (200, first["version"]))

    def test_booking_same_guests_no_bump(self):
        url, body = self.updates()[2]
        same = {**body, "nights": 2}
        status, data = self.raw(self.alex, "put", url, {**same, "version": 1})
        self.assertEqual((status, data["version"]), (200, 1))
        status, data = self.raw(self.alex, "put", url, {**same, "guests": [{**GUESTS[0], "rank": "OS"}], "version": 1})
        self.assertEqual((status, data["version"]), (200, 2))

    def test_sync_does_not_bump_drafts(self):
        url = f"/api/vessels/{self.alex_vessel.id}/services/"
        crew = {"type": "Crew Change", "data": {"onSigners": [{"name": "J SMITH", "needsHotel": True}],
                                                "offSigners": []}}
        self.assertEqual(self.call(self.alex, "post", url, crew)[0], 201)
        service = Service.objects.get(vessel=self.alex_vessel, service_type="Crew Change")
        renamed = {**service.data["onSigners"][0], "name": "JOHN SMITH"}
        body = {"type": "Crew Change", "data": {"onSigners": [renamed], "offSigners": []}, "version": 1}
        self.assertEqual(self.raw(self.alex, "put", f"/api/services/{service.id}/", body)[0], 200)
        for draft in (*HotelStay.objects.filter(draft=True), *Transfer.objects.filter(draft=True)):
            self.assertEqual(draft.guests.get().name, "JOHN SMITH")
            self.assertEqual(draft.version, 1)

    def test_vessel_date_rule_does_not_bump_services(self):
        url = f"/api/vessels/{self.alex_vessel.id}/"
        body = {**self.vessel_body(sailing_at="2026-11-20T10:00"), "version": 1}
        self.assertEqual(self.raw(self.alex, "put", url, body)[0], 200)
        self.service.refresh_from_db()
        self.assertEqual(self.service.version, 1)

    def test_force_with_old_conflict_version_warns_again(self):
        url = f"/api/vessels/{self.alex_vessel.id}/"
        self.raw(self.alex, "put", url, {**self.vessel_body(name="A"), "version": 1})
        status, data = self.raw(self.admin, "put", url, {**self.vessel_body(name="MINE"), "version": 1})
        offered = data["conflict"]["version"]
        self.raw(self.alex, "put", url, {**self.vessel_body(name="B"), "version": offered})  # a third save meanwhile
        status, data = self.raw(self.admin, "put", url, {**self.vessel_body(name="MINE"), "version": offered})
        self.assertEqual((status, data["conflict"]["fields"]), (409, ["Name"]))
        status, data = self.raw(self.admin, "put", url, {**self.vessel_body(name="MINE"),
                                                         "version": data["conflict"]["version"]})
        self.assertEqual((status, data["name"], data["version"]), (200, "MINE", 4))

    def test_same_person_flag(self):
        url = f"/api/closures/{self.closure.id}/"
        body = self.updates()[4][1]
        self.raw(self.alex, "put", url, {**body, "version": 1})
        status, data = self.raw(self.alex, "put", url, {**body, "notes": "other tab", "version": 1})
        self.assertEqual((status, data["conflict"]["same_person"], data["conflict"]["who"]), (409, True, "alex"))

    def test_port_user_conflict_scoped(self):
        suez = self.login("suezuser")
        self.raw(self.alex, "put", f"/api/vessels/{self.alex_vessel.id}/", {**self.vessel_body(name="A"), "version": 1})
        for url, body in self.updates():
            with self.subTest(url=url):
                status, data = self.raw(suez, "put", url, {**body, "version": 1})
                self.assertEqual(status, 404)
                self.assertNotIn("conflict", data)
        viewer = self.login("viewer")
        status, data = self.raw(viewer, "put", self.updates()[0][0], {**self.updates()[0][1], "version": 1})
        self.assertEqual(status, 403)
        self.assertNotIn("conflict", data)

    def test_service_version_in_vessel_json(self):
        status, data = self.call(self.alex, "get", f"/api/vessels/{self.alex_vessel.id}/")
        self.assertEqual(data["version"], 1)
        self.assertEqual(data["services"][0]["version"], 1)
        listed = self.call(self.alex, "get", "/api/hotels/?from=2026-11-01&to=2026-11-30")[1]["bookings"]
        self.assertEqual(listed[0]["version"], 1)
        closures = self.call(self.alex, "get", "/api/closures/?from=2000-01-01&to=2100-01-01")[1]["closures"]
        self.assertEqual(closures[0]["version"], 1)


class AdminVersionTests(ApiTestCase):
    """Saves in the Django admin pages raise the version too (version itself is read-only there)."""

    def request(self):
        request = RequestFactory().post("/admin/")
        request.user = self.admin_user
        request._messages = SimpleNamespace(add=lambda *a, **k: None)
        return request

    def setUp(self):
        from django.contrib.auth.models import User
        self.admin_user = User.objects.get(username="admin")

    def form(self, changed):
        return SimpleNamespace(has_changed=lambda: changed)

    def test_admin_edit_raises_version(self):
        admin = VesselAdmin(Vessel, site)
        vessel = self.alex_vessel
        with as_user("admin"):
            admin.save_model(self.request(), vessel, self.form(False), change=True)
            vessel.refresh_from_db()
            self.assertEqual(vessel.version, 1)
            vessel.name = "BY ADMIN"
            admin.save_model(self.request(), vessel, self.form(True), change=True)
        vessel.refresh_from_db()
        self.assertEqual((vessel.name, vessel.version), ("BY ADMIN", 2))

    def test_admin_inline_service_edit_raises_its_version(self):
        admin = VesselAdmin(Vessel, site)
        service = Service.objects.get(pk=self.suez_service.pk)
        service.agent = "AG"
        saved = []
        changed = SimpleNamespace(has_changed=lambda: True, instance=service)
        untouched = SimpleNamespace(has_changed=lambda: False, instance=Service.objects.get(pk=service.pk))
        formset = SimpleNamespace(model=Service, forms=[changed, untouched], new_objects=[], changed_objects=[],
                                  deleted_objects=[], save=lambda: [f.instance.save() or saved.append(f) for f in
                                                                    (changed,)])
        with as_user("admin"):
            admin.save_formset(self.request(), SimpleNamespace(instance=self.suez_vessel), formset, change=True)
        service.refresh_from_db()
        self.assertEqual(service.version, 2)
        self.assertTrue(saved)

    def test_admin_guest_edit_raises_booking_version_once(self):
        admin = HotelStayAdmin(HotelStay, site)
        stay = HotelStay.objects.create(vessel=self.alex_vessel, hotel="H", check_in=date(2026, 11, 13), nights=1)
        formset = SimpleNamespace(model=Guest, forms=[], new_objects=[object()], changed_objects=[],
                                  deleted_objects=[], save=lambda: None)
        with as_user("admin"):
            admin.save_formset(self.request(), SimpleNamespace(instance=stay), formset, change=True)
        stay.refresh_from_db()
        self.assertEqual(stay.version, 2)
        stay._version_bumped = True  # the booking's own fields were changed in the same admin save
        with as_user("admin"):
            admin.save_formset(self.request(), SimpleNamespace(instance=stay), formset, change=True)
        stay.refresh_from_db()
        self.assertEqual(stay.version, 2)

    def test_version_read_only_in_admin(self):
        for admin_class, model in ((VesselAdmin, Vessel), (HotelStayAdmin, HotelStay)):
            self.assertIn("version", admin_class(model, site).get_readonly_fields(self.request()))
        self.assertIn("version", ServiceInline(Vessel, site).get_readonly_fields(self.request()))
