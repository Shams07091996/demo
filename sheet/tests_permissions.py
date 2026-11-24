"""Access rework piece 2: per-person permissions and pages (constants.PERMISSIONS / PAGES, Profile.can / sees)."""

from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings

from .constants import PAGE_KEYS, PERMISSION_KEYS, TEMPLATES
from .models import Customer, HotelStay, Option, PortClosure, Profile, Service, Vessel, VesselDisposal
from .tests import NEEDED, allow, make_user
from .tests_logistics import BookingData, stay, trip
from .validators import clean_service_data


def profile(username, ports="alexandria", permissions=None, pages=None):
    return make_user(username, ports, permissions=permissions, pages=pages).profile


class PermissionModelTests(TestCase):
    def test_admin_has_everything(self):
        admin = User.objects.create_superuser("root", password="x")
        p = Profile.objects.create(user=admin)
        self.assertTrue(all(p.can(key) for key in PERMISSION_KEYS))
        self.assertTrue(all(p.sees(page) for page in PAGE_KEYS))

    def test_user_has_only_ticked(self):
        p = profile("u", permissions=["vessels.edit"], pages=["vessels", "services"])
        self.assertTrue(p.can("vessels.edit"))
        self.assertFalse(p.can("vessels.delete"))
        self.assertTrue(p.sees("services"))
        self.assertFalse(p.sees("hotels"))
        self.assertTrue(profile("v", permissions=[], pages=[]).sees("vessels"))

    def test_dependencies_apply_when_checking(self):
        p = profile("u", permissions=["accounting.close", "history.view"], pages=["calculations", "rates", "history"])
        checks = lambda: [p.sees("calculations"), p.sees("rates"), p.sees("history"),  # noqa: E731
                          p.can("history.view"), p.can("accounting.close")]
        self.assertEqual(checks(), [False] * 5)
        p.permissions = [*p.permissions, "money.view"]
        self.assertEqual(checks(), [True] * 5)

    def test_close_needs_the_calculations_page(self):
        p = profile("u", permissions=["accounting.close", "money.view"], pages=["vessels"])
        self.assertFalse(p.can("accounting.close"))

    def test_unknown_keys_are_false(self):
        p = profile("u")
        self.assertFalse(p.can("nope"))
        self.assertFalse(p.sees("nope"))

    def test_templates_are_consistent(self):
        found = {key: (set(perms), set(pages)) for key, _, perms, pages in TEMPLATES}
        self.assertEqual(set(found), {"marine", "operations", "manager", "accounts"})
        for perms, pages in found.values():
            self.assertLessEqual(perms, set(PERMISSION_KEYS))
            self.assertLessEqual(pages, set(PAGE_KEYS))
            self.assertIn("vessels", pages)
            self.assertEqual("history" in pages, "history.view" in perms)
        self.assertEqual(found["manager"], (set(PERMISSION_KEYS), set(PAGE_KEYS)))
        self.assertEqual(found["accounts"][0], {"money.view", "exports", "history.view", "accounting.close"})
        self.assertEqual(found["operations"][0] - found["marine"][0],
                         {"services.cancel", "customers.edit", "bookings.edit"})
        self.assertEqual(found["marine"][0], {"vessels.edit", "services.edit", "services.complete", "money.edit"})

    def test_make_user_gives_everything_by_default(self):
        p = profile("u")
        self.assertEqual((p.permissions, p.pages), (list(PERMISSION_KEYS), list(PAGE_KEYS)))


class PermissionMigrationTests(TransactionTestCase):
    """Migration 0025: every existing person gets all permissions and all pages (nobody loses anything)."""

    def test_migration_gives_existing_profiles_everything(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("sheet", "0024_profile_ports")])
        old = executor.loader.project_state([("sheet", "0024_profile_ports")]).apps
        OldUser, OldProfile = old.get_model("auth", "User"), old.get_model("sheet", "Profile")
        user = OldUser.objects.create(username="porter")
        OldProfile.objects.create(user=user, home_port="damietta", ports=["damietta"])
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        stored = Profile.objects.get(user_id=user.pk)
        self.assertEqual((stored.permissions, stored.pages), (list(PERMISSION_KEYS), list(PAGE_KEYS)))


WATER = {"type": "Fresh Water", "data": {"cost": "10", "costCurrency": "EGP"}}


class Limited(BookingData):
    """Helpers: an Alexandria User with every permission except some."""

    def without(self, *keys, pages=None):
        name = f"u{User.objects.count()}"
        make_user(name, "alexandria", permissions=[k for k in PERMISSION_KEYS if k not in keys], pages=pages)
        return self.login(name)

    def service(self, status="in_progress"):
        return Service.objects.create(vessel=self.alex_vessel, service_type="Fresh Water", status=status,
                                      cancel_reason="Owner" if status == "cancelled" else "",
                                      data={"cost": 10, "costCurrency": "EGP"})


@override_settings(RATE_LIMIT_EXPORTS_PER_USER=50)
class WritePermissionTests(Limited):
    """Refusal tests (piece 1 removed the old Read-only ones): a User with every permission but one is refused (403,
    nothing changed); with it, the same request works."""

    def put_status(self, client, service, status):
        reason = {"cancel_reason": "Owner"} if status == "cancelled" else {}
        return self.call(client, "put", f"/api/services/{service.id}/", {**WATER, "status": status, **reason})[0]

    def test_vessel_create_and_update_need_vessels_edit(self):
        body = {**NEEDED, "name": "NEW", "date": "2026-11-13"}
        client = self.without("vessels.edit")
        self.assertEqual(self.call(client, "post", "/api/vessels/", body)[0], 403)
        url = f"/api/vessels/{self.alex_vessel.id}/"
        self.assertEqual(self.call(client, "patch", url, {"notes": "x"})[0], 403)
        self.assertFalse(Vessel.objects.filter(name="NEW").exists())
        self.assertEqual(self.call(self.without(), "post", "/api/vessels/", body)[0], 201)

    def test_vessel_delete_needs_vessels_delete(self):
        vessel = Vessel.objects.create(name="GONE", date=self.alex_vessel.date, port="alexandria")
        url = f"/api/vessels/{vessel.id}/"
        self.assertEqual(self.call(self.without("vessels.delete"), "delete", url)[0], 403)
        self.assertTrue(Vessel.objects.filter(pk=vessel.pk).exists())
        self.assertEqual(self.call(self.without(), "delete", url)[0], 200)

    def test_service_writes_need_services_edit(self):
        client = self.without("services.edit")
        service = self.service()
        self.assertEqual(self.call(client, "post", f"/api/vessels/{self.alex_vessel.id}/services/", WATER)[0], 403)
        self.assertEqual(self.call(client, "put", f"/api/services/{service.id}/", WATER)[0], 403)
        self.assertEqual(self.call(client, "delete", f"/api/services/{service.id}/")[0], 403)
        self.assertEqual(Service.objects.filter(vessel=self.alex_vessel).count(), 1)
        self.assertEqual(self.call(self.without(), "delete", f"/api/services/{service.id}/")[0], 200)

    def test_cancel_needs_services_cancel(self):
        service = self.service()
        client = self.without("services.cancel")
        self.assertEqual(self.put_status(client, service, "cancelled"), 403)
        self.assertEqual(Service.objects.get(pk=service.pk).status, "in_progress")
        Service.objects.filter(pk=service.pk).update(status="cancelled", cancel_reason="Owner")
        self.assertEqual(self.put_status(client, service, "in_progress"), 403)
        self.assertEqual(self.put_status(self.without(), service, "in_progress"), 200)

    def test_complete_needs_services_complete(self):
        service = self.service()
        client = self.without("services.complete")
        self.assertEqual(self.put_status(client, service, "completed"), 403)
        Service.objects.filter(pk=service.pk).update(status="completed")
        self.assertEqual(self.put_status(client, service, "in_progress"), 403)
        self.assertEqual(self.put_status(self.without(), service, "in_progress"), 200)

    def test_cancelled_to_completed_needs_both(self):
        service = self.service(status="cancelled")
        self.assertEqual(self.put_status(self.without("services.cancel"), service, "completed"), 403)
        self.assertEqual(self.put_status(self.without("services.complete"), service, "completed"), 403)
        self.assertEqual(self.put_status(self.without(), service, "completed"), 200)

    def test_unchanged_cancelled_status_needs_only_services_edit(self):
        service = self.service(status="cancelled")
        client = self.without("services.cancel", "services.complete")
        self.assertEqual(self.put_status(client, service, "cancelled"), 200)
        # a save without the status key keeps it too
        self.assertEqual(self.call(client, "put", f"/api/services/{service.id}/", WATER)[0], 200)

    def test_create_completed_needs_services_complete(self):
        url = f"/api/vessels/{self.alex_vessel.id}/services/"
        self.assertEqual(self.call(self.without("services.complete"), "post", url,
                                   {**WATER, "status": "completed"})[0], 403)
        self.assertEqual(self.call(self.without("services.cancel"), "post", url,
                                   {**WATER, "status": "cancelled", "cancel_reason": "Owner"})[0], 403)
        self.assertFalse(Service.objects.filter(vessel=self.alex_vessel).exists())
        self.assertEqual(self.call(self.without("services.cancel"), "post", url, WATER)[0], 201)

    def test_cancel_bookings_needs_bookings_edit(self):
        service = self.service()
        payload = {**WATER, "status": "cancelled", "cancel_reason": "Owner",
                   "cancel_bookings": [{"kind": "hotel", "id": self.stay.id}]}
        status, body = self.call(self.without("bookings.edit"), "put", f"/api/services/{service.id}/", payload)
        self.assertEqual(status, 403, body)
        self.assertEqual(Service.objects.get(pk=service.pk).status, "in_progress")

    def test_service_bookings_list_needs_services_cancel(self):
        url = f"/api/services/{self.service().id}/bookings/"
        self.assertEqual(self.call(self.without("services.cancel"), "get", url)[0], 403)
        self.assertEqual(self.call(self.without(), "get", url)[0], 200)

    def test_documents_need_documents(self):
        on = {"name": "J SMITH", "uid": "abcdef123456"}
        crew = Service.objects.create(vessel=self.alex_vessel, service_type="Crew Change",
                                      data=clean_service_data("Crew Change", {"onSigners": [on], "offSigners": []}))
        client = self.without("documents")
        self.assertEqual(client.get(f"/api/services/{crew.id}/log/abcdef123456/").status_code, 403)
        url = f"/api/services/{crew.id}/receipt/"
        self.assertEqual(self.call(client, "get", url)[0], 403)
        receipt = {"port": "Alexandria", "date": "20/11/2026", "vessel": "ALEX SHIP", "services": "Crew change"}
        self.assertEqual(self.call(client, "post", url, receipt)[0], 403)
        self.assertEqual(self.without().get(f"/api/services/{crew.id}/log/abcdef123456/").status_code, 200)

    def test_master_values_need_master_edit(self):
        client = self.without("master.edit")
        self.assertEqual(self.call(client, "post", "/api/options/", {"kind": "opr", "value": "NEW OPR"})[0], 403)
        option = Option.objects.create(kind="opr", value="MINE", port="alexandria")
        self.assertEqual(self.call(client, "delete", f"/api/options/{option.id}/")[0], 403)
        self.assertTrue(Option.objects.filter(pk=option.pk).exists())
        self.assertEqual(self.call(self.without(), "delete", f"/api/options/{option.id}/")[0], 200)

    def test_ships_need_customers_edit(self):
        ship = {"name": "msc aurora", "imo": "9074729", "opr": NEEDED["opr"]}
        client = self.without("customers.edit")
        self.assertEqual(self.call(client, "post", "/api/ships/", ship)[0], 403)
        url = f"/api/ships/{self.test_ship.id}/"
        self.assertEqual(self.call(client, "put", url, {"name": "RENAMED", "imo": "9321483",
                                                         "opr": NEEDED["opr"]})[0], 403)
        self.assertEqual(self.call(self.without(), "post", "/api/ships/", ship)[0], 201)

    def test_customers_need_customers_edit(self):
        body = {"name": "Blue Owners", "notes": "", "contacts": [], "rates": {}}
        client = self.without("customers.edit")
        self.assertEqual(self.call(client, "post", "/api/customers/", body)[0], 403)
        status, made = self.call(self.without(), "post", "/api/customers/", body)
        self.assertEqual(status, 201, made)
        url = f"/api/customers/{made['id']}/"
        self.assertEqual(self.call(client, "put", url, {**body, "name": "Renamed"})[0], 403)
        self.assertEqual(self.call(self.without("money.edit"), "put", url, {**body, "name": "Renamed"})[0], 200)

    def test_customer_rates_need_money_edit(self):
        rates = {"Fresh Water": {"amount": 12.5, "currency": "USD"}}
        body = {"name": "Blue Owners", "notes": "", "contacts": [], "rates": rates}
        client = self.without("money.edit")
        self.assertEqual(self.call(client, "post", "/api/customers/", body)[0], 403)
        status, made = self.call(self.without(), "post", "/api/customers/", body)
        self.assertEqual(status, 201, made)
        url = f"/api/customers/{made['id']}/"
        self.assertEqual(self.call(client, "put", url, {**body, "name": "Same rates"})[0], 200)
        changed = {**body, "rates": {"Fresh Water": {"amount": 13, "currency": "USD"}}}
        self.assertEqual(self.call(client, "put", url, changed)[0], 403)
        self.assertEqual(self.call(client, "put", url, {**body, "rates": {}})[0], 403)
        self.assertEqual(Customer.objects.get(pk=made["id"]).rates.get().amount, Decimal("12.5"))

    def test_deletes_stay_admin(self):
        customer = Customer.objects.create(name="Red")
        client = self.without()
        self.assertEqual(self.call(client, "delete", f"/api/customers/{customer.id}/")[0], 403)
        self.assertEqual(self.call(client, "delete", f"/api/ships/{self.test_ship.id}/")[0], 403)

    def test_closure_writes_need_closures_edit(self):
        allow("closure", "WEATHER")
        body = {"port": "alexandria", "start_at": "2026-11-13T06:00", "end_at": "2026-11-13T14:00",
                "reason": "WEATHER"}
        client = self.without("closures.edit")
        self.assertEqual(self.call(client, "post", "/api/closures/", body)[0], 403)
        status, made = self.call(self.without(), "post", "/api/closures/", body)
        self.assertEqual(status, 201, made)
        url = f"/api/closures/{made['id']}/"
        self.assertEqual(self.call(client, "put", url, {**body, "notes": "x"})[0], 403)
        self.assertEqual(self.call(client, "delete", url)[0], 403)
        self.assertEqual(PortClosure.objects.count(), 1)

    def test_booking_writes_need_bookings_edit(self):
        client = self.without("bookings.edit")
        for kind, booking, body in (("hotels", self.stay, stay()), ("transfers", self.transfer, trip())):
            body = {**body, "vessel": self.alex_vessel.id}
            self.assertEqual(self.call(client, "post", f"/api/{kind}/", body)[0], 403)
            self.assertEqual(self.call(client, "put", f"/api/{kind}/{booking.id}/", body)[0], 403)
            self.assertEqual(self.call(client, "delete", f"/api/{kind}/{booking.id}/")[0], 403)
            status, made = self.call(self.without(), "post", f"/api/{kind}/", body)
            self.assertEqual(status, 201, made)
        self.assertTrue(HotelStay.objects.filter(pk=self.stay.pk).exists())

    def test_disposal_needs_disposal_edit(self):
        url = f"/api/disposal/{self.alex_vessel.id}/"
        self.assertEqual(self.call(self.without("disposal.edit"), "put", url, {"garbage": 2})[0], 403)
        self.assertFalse(VesselDisposal.objects.exists())
        status, body = self.call(self.without(), "put", url, {"garbage": 2})
        self.assertEqual(status, 200, body)

    def test_accounting_needs_accounting_close(self):
        service = self.service()
        body = {"kind": "service", "id": service.id, "closed": True}
        self.assertEqual(self.call(self.without("accounting.close"), "post", "/api/accounting/", body)[0], 403)
        self.assertFalse(Service.objects.get(pk=service.pk).acct_closed)
        status, result = self.call(self.without(), "post", "/api/accounting/", body)
        self.assertEqual((status, result), (200, {"ok": True, "closed": True}))
