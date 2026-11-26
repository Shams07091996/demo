"""Access rework piece 2: per-person permissions and pages (constants.PERMISSIONS / PAGES, Profile.can / sees)."""

from datetime import date
from decimal import Decimal

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .constants import PAGE_KEYS, PERMISSION_KEYS, TEMPLATES
from .models import (
    ChangeRecord,
    Customer,
    ExchangeRate,
    Guest,
    HotelStay,
    Option,
    PortClosure,
    Profile,
    Service,
    Transfer,
    Vessel,
    VesselDisposal,
)
from .tests import NEEDED, allow, make_user
from .tests_dataexport import read
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

    def test_lists_that_are_not_lists_give_nothing(self):
        """Review fix: a value typed as text (e.g. in the admin pages) is no list: `"exports money.view"` must not
        match as a substring."""
        p = profile("u")
        p.permissions, p.pages = "exports money.view", "calculations hotels"
        self.assertFalse(p.can("exports"))
        self.assertFalse(p.can("money.view"))
        self.assertFalse(p.sees("hotels"))

    def test_admin_pages_cannot_type_the_lists(self):
        from django.contrib import admin as django_admin
        from django.test import RequestFactory

        from .admin import ProfileInline

        request = RequestFactory().get("/")
        request.user = User.objects.create_superuser("root", password="x")
        inline = ProfileInline(User, django_admin.site)
        self.assertLessEqual({"permissions", "pages"}, set(inline.get_readonly_fields(request)))

    def test_unknown_keys_are_false(self):
        p = profile("u")
        self.assertFalse(p.can("nope"))
        self.assertFalse(p.sees("nope"))

    def test_templates_are_marine_operations_manager(self):
        """The Accounts employee template was cancelled (2026-11-25): three templates, in this order."""
        self.assertEqual([key for key, *_ in TEMPLATES], ["marine", "operations", "manager"])

    def test_templates_are_consistent(self):
        found = {key: (set(perms), set(pages)) for key, _, perms, pages in TEMPLATES}
        self.assertEqual(set(found), {"marine", "operations", "manager"})
        for perms, pages in found.values():
            self.assertLessEqual(perms, set(PERMISSION_KEYS))
            self.assertLessEqual(pages, set(PAGE_KEYS))
            self.assertIn("vessels", pages)
            self.assertEqual("history" in pages, "history.view" in perms)
        self.assertEqual(found["manager"], (set(PERMISSION_KEYS), set(PAGE_KEYS)))
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
        # Everything that existed then; later ticks (the Operation pages) stay off until an Admin gives them.
        before_operation = ([k for k in PERMISSION_KEYS if not k.startswith("operation.")],
                            [k for k in PAGE_KEYS if not k.startswith("op_")])
        self.assertEqual((stored.permissions, stored.pages), before_operation)


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

    def test_cancel_bookings_needs_services_cancel(self):
        """Review fix: cancelling a crew change's bookings is part of cancelling the service (spec), so it needs
        services.cancel too, even when the service is already Cancelled."""
        service = self.service(status="cancelled")
        payload = {**WATER, "status": "cancelled", "cancel_reason": "Owner",
                   "cancel_bookings": [{"kind": "hotel", "id": self.stay.id}]}
        status, body = self.call(self.without("services.cancel"), "put", f"/api/services/{service.id}/", payload)
        self.assertEqual(status, 403, body)
        self.assertFalse(HotelStay.objects.get(pk=self.stay.pk).cancelled)

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
        no_rates = {key: value for key, value in body.items() if key != "rates"}
        self.assertEqual(self.call(self.without("money.edit"), "put", url, {**no_rates, "name": "Renamed"})[0], 200)

    def test_customer_rates_need_money_edit(self):
        rates = {"Fresh Water": {"amount": 12.5, "currency": "USD"}}
        body = {"name": "Blue Owners", "notes": "", "contacts": [], "rates": rates}
        client = self.without("money.edit")
        self.assertEqual(self.call(client, "post", "/api/customers/", body)[0], 403)
        status, made = self.call(self.without(), "post", "/api/customers/", body)
        self.assertEqual(status, 201, made)
        url = f"/api/customers/{made['id']}/"
        # Piece 3: rates are never sent to a person without money.edit, so sending any (even unchanged) is refused;
        # a save without them keeps them.
        self.assertEqual(self.call(client, "put", url, {**body, "name": "Same rates"})[0], 403)
        no_rates = {key: value for key, value in body.items() if key != "rates"}
        self.assertEqual(self.call(client, "put", url, {**no_rates, "name": "Same rates"})[0], 200)
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


ALL_PAGES_BUT = lambda *gone: [p for p in PAGE_KEYS if p not in gone]  # noqa: E731
RANGE = {"from": "2026-11-01", "to": "2026-11-30"}


@override_settings(RATE_LIMIT_EXPORTS_PER_USER=100)
class PageTests(Limited):
    """A page not ticked is refused on the routes that only serve it; exports and alerts follow the pages."""

    def status(self, client, url, params=None):
        return client.get(url, params or {}).status_code

    def test_page_reads_need_the_page(self):
        for page, url in (("services", "/api/services/"), ("hotels", "/api/hotels/"),
                          ("transport", "/api/transfers/"), ("closures", "/api/closures/"),
                          ("disposal", "/api/disposal/"), ("calculations", "/api/calculations/"),
                          ("dashboard", "/api/dashboard/"), ("dashboard", "/api/dashboard/jobs/"),
                          ("rates", "/api/rates/"), ("rates", "/api/disposal-prices/")):
            self.assertEqual(self.status(self.without(pages=ALL_PAGES_BUT(page)), url, RANGE), 403, url)
            self.assertNotEqual(self.status(self.without(), url, RANGE), 403, url)  # jobs: 400 without an agent
        url = f"/api/hotels/{self.stay.id}/"
        self.assertEqual(self.status(self.without(pages=ALL_PAGES_BUT("hotels")), url), 403)
        url = f"/api/disposal/{self.alex_vessel.id}/"
        client = self.without(pages=ALL_PAGES_BUT("disposal"))
        self.assertEqual(self.call(client, "put", url, {"garbage": 2})[0], 403)

    def test_shared_lists_stay_readable(self):
        client = self.without(*PERMISSION_KEYS, pages=["vessels"])
        for url in ("/api/vessels/", "/api/vessels/alerts/", "/api/options/", "/api/ships/", "/api/customers/",
                    f"/api/vessels/{self.alex_vessel.id}/"):
            self.assertEqual(self.status(client, url), 200, url)

    def test_crew_picker_needs_a_booking_page(self):
        url = f"/api/vessels/{self.alex_vessel.id}/crew/"
        self.assertEqual(self.status(self.without(pages=ALL_PAGES_BUT("hotels", "transport")), url), 403)
        self.assertEqual(self.status(self.without(pages=ALL_PAGES_BUT("hotels")), url), 200)

    def test_page_export_needs_page_and_exports(self):
        for name, page in (("hotels", "hotels"), ("transfers", "transport"), ("closures", "closures"),
                           ("disposal", "disposal"), ("calculations", "calculations"), ("services", "services")):
            url = f"/api/export/{name}/"
            self.assertEqual(self.status(self.without(pages=ALL_PAGES_BUT(page)), url, RANGE), 403, name)
            self.assertEqual(self.status(self.without("exports"), url, RANGE), 403, name)
            self.assertEqual(self.status(self.without(), url, RANGE), 200, name)

    def test_vessels_excel_needs_exports(self):
        self.assertEqual(self.status(self.without("exports"), "/api/export/vessels/"), 403)
        self.assertEqual(self.status(self.without(), "/api/export/vessels/"), 200)

    def test_all_data_leaves_out_pages_not_had(self):
        response = self.without(pages=ALL_PAGES_BUT("hotels", "calculations")).get("/api/export/all/", RANGE)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(list(read(response.content)), ["Transport", "Port closures", "Garbage & Sludge"])
        client = self.without(pages=ALL_PAGES_BUT("hotels", "transport", "closures", "disposal", "calculations"))
        self.assertEqual(self.status(client, "/api/export/all/", RANGE), 403)
        self.assertEqual(self.status(self.without("exports"), "/api/export/all/", RANGE), 403)
        self.assertEqual(self.status(self.without(pages=ALL_PAGES_BUT("dashboard")), "/api/export/all/", RANGE), 403)

    def test_management_excel_leaves_out_figures_of_pages_not_had(self):
        """Review fix: without Hotels / Transport / Garbage, their money lines and the Crew sheet's hotel / transfer
        columns are not in the management Excel."""
        url = "/api/dashboard/export/"
        full = read(self.without().get(url, RANGE).content)
        service_names = [row[0] for row in full["Profit by service"] if row]
        self.assertIn("Hotels", service_names)
        self.assertIn("Transport", service_names)
        client = self.without(pages=ALL_PAGES_BUT("hotels", "transport", "disposal"))
        limited = read(client.get(url, RANGE).content)
        service_names = [row[0] for row in limited["Profit by service"] if row]
        self.assertNotIn("Hotels", service_names)
        self.assertNotIn("Transport", service_names)
        crew_cells = {cell for row in limited["Crew"] for cell in row if isinstance(cell, str)}
        self.assertEqual(crew_cells & {"Hotel nights", "Transfers"}, set())
        summary_cells = {cell for row in limited["Summary"] for cell in row if isinstance(cell, str)}
        self.assertFalse(any("hotels" in str(cell).lower() for cell in summary_cells), summary_cells)

    def test_management_excel_leaves_out_closures_and_disposal(self):
        url = "/api/dashboard/export/"
        full = read(self.without().get(url, RANGE).content)
        self.assertIn("Port closures", full)
        self.assertIn("Garbage & Sludge", full)
        names = read(self.without(pages=ALL_PAGES_BUT("closures", "disposal")).get(url, RANGE).content)
        self.assertEqual(set(full) - set(names), {"Port closures", "Garbage & Sludge"})
        self.assertEqual(self.status(self.without("exports"), url, RANGE), 403)
        self.assertEqual(self.status(self.without(pages=ALL_PAGES_BUT("dashboard")), url, RANGE), 403)

    def test_booking_alert_lines_follow_pages(self):
        gone = Vessel.objects.create(name="GONE", date=date(2026, 1, 5), port="alexandria", arrival_agent="A",
                                     sailing_agent="B")
        hotel = HotelStay.objects.create(vessel=gone, hotel="HILTON", check_in=date(2026, 1, 5), nights=1)
        Guest.objects.create(stay=hotel, name="J SMITH")
        car = Transfer.objects.create(vessel=gone, from_place="airport", to_place="port", airport="BORG EL ARAB",
                                      at=timezone.now())
        Guest.objects.create(transfer=car, name="A OFF")

        def missing(client):
            rows = [r for r in self.call(client, "get", "/api/vessels/alerts/")[1]["missing"] if r["id"] == gone.id]
            return [item for item in rows[0]["missing"] if ": " in item]  # the line stays for the missing times

        self.assertEqual(missing(self.without()), ["Hotel: J SMITH", "Transport: A OFF"])
        self.assertEqual(missing(self.without(pages=ALL_PAGES_BUT("hotels"))), ["Transport: A OFF"])
        self.assertEqual(missing(self.without(pages=ALL_PAGES_BUT("hotels", "transport"))), [])


class HistoryTests(Limited):
    """A User's History (history.view): only records of their ports, never people / shared records."""

    def records(self, client):
        status, body = self.call(client, "get", "/api/history/?page_size=100")
        self.assertEqual(status, 200, body)
        return body["records"]

    def test_history_needs_history_view(self):
        self.assertEqual(self.call(self.without("history.view"), "get", "/api/history/")[0], 403)
        self.assertEqual(self.call(self.login("admin"), "get", "/api/history/")[0], 200)

    def test_user_history_shows_only_their_ports(self):
        alex_ship = Vessel.objects.create(name="ALEX NEW", date=date(2026, 11, 13), port="alexandria")
        suez_ship = Vessel.objects.create(name="SUEZ NEW", date=date(2026, 11, 13), port="suez")
        seen = {(r["object_type"], r["object_id"]) for r in self.records(self.without())}
        self.assertIn(("vessel", alex_ship.id), seen)
        self.assertNotIn(("vessel", suez_ship.id), seen)
        admin_seen = {(r["object_type"], r["object_id"]) for r in self.records(self.login("admin"))}
        self.assertIn(("vessel", suez_ship.id), admin_seen)

    def test_user_history_hides_people_records(self):
        alex = Profile.objects.get(user__username="alex")
        alex.permissions = []
        alex.save()  # a Profile record carries the home port, alexandria
        Option.objects.create(kind="opr", value="SHARED", port="")
        Customer.objects.create(name="Blue")
        ExchangeRate.objects.create(month=date(2026, 10, 1), rate=50)
        self.assertTrue(ChangeRecord.objects.filter(object_type="profile", port="alexandria").exists())
        types = {r["object_type"] for r in self.records(self.without())}
        self.assertEqual(types & {"profile", "user", "customer", "exchangerate", "ship", "totpdevice"}, set())
        self.assertNotIn(("option", ""), {(r["object_type"], r["port"]) for r in self.records(self.without())})

    def test_history_follows_booking_and_closure_pages(self):
        """Review fix: someone with History but no Hotels / Transport / Port closures page: those records stay out of
        their History (asking with type= too)."""
        HotelStay.objects.filter(pk=self.stay.pk).update(nights=4)
        self.stay.refresh_from_db()
        self.stay.save()
        PortClosure.objects.create(port="alexandria", start_at=timezone.now(), reason="WEATHER")
        client = self.without(pages=ALL_PAGES_BUT("hotels", "transport", "closures"))
        types = {r["object_type"] for r in self.records(client)}
        self.assertEqual(types & {"hotelstay", "transfer", "guest", "portclosure"}, set())
        self.assertIn("vessel", types)
        self.assertEqual(self.call(client, "get", "/api/history/?type=guest")[1]["records"], [])
        types = {r["object_type"] for r in self.records(self.without(pages=ALL_PAGES_BUT("transport", "closures")))}
        self.assertLessEqual({"hotelstay", "guest"}, types)
        self.assertEqual(types & {"transfer", "portclosure"}, set())

    def test_closure_changes_carry_their_port(self):
        closure = PortClosure.objects.create(port="alexandria", start_at=timezone.now(), reason="WEATHER")
        record = ChangeRecord.objects.filter(object_type="portclosure", object_id=closure.id).get()
        self.assertEqual(record.port, "alexandria")
        self.assertIn(("portclosure", closure.id),
                      {(r["object_type"], r["object_id"]) for r in self.records(self.without())})


class IndexTests(Limited):
    """The page names only the person's pages in the sidebar and carries their ticks for the screens."""

    def me(self, response):
        import json
        import re
        found = re.search(r'<script id="me-data" type="application/json">(.*?)</script>', response.content.decode())
        return json.loads(found[1])

    def test_marine_sidebar_and_ticks(self):
        marine = next(t for t in TEMPLATES if t[0] == "marine")
        make_user("marine", "alexandria", permissions=list(marine[2]), pages=list(marine[3]))
        response = self.login("marine").get("/")
        html = response.content.decode()
        self.assertIn('data-page="services"', html)
        for page in ("hotels", "transport", "closures", "disposal", "calculations", "dashboard", "ships",
                     "customers", "master", "rates", "history"):
            self.assertNotIn(f'class="nav-item" data-page="{page}"', html, page)
        me = self.me(response)
        self.assertEqual(me["permissions"], list(marine[2]))
        self.assertEqual(me["pages"], ["vessels", "services"])
        self.assertNotIn("canEdit", me)

    def test_sidebar_folders(self):
        import re
        html = self.login("admin").get("/").content.decode()
        nav = html[html.index('id="nav"'):html.index("</nav>")]
        groups = re.findall(r'data-group="(\w+)"', nav)
        self.assertEqual(groups, ["marine", "operation", "reports", "master"])
        heads = re.findall(r'<span class="nav-group-label">(?:<svg.*?</svg>)?([^<]+)</span>', nav)
        self.assertEqual(heads, ["Marine", "Operation", "Reports", "Master data"])
        pages = re.findall(r'class="nav-item" data-page="(\w+)"', nav)
        self.assertEqual(pages, ["vessels", "services", "closures", "ships",
                                 "op_vessels", "op_live", "op_list", "terminals", "op_windows",
                                 "dashboard", "disposal", "hotels", "transport", "calculations", "op_analysis",
                                 "op_charts",
                                 "master", "customers", "rates", "ports", "accounts", "history"])
        make_user("vonly", "alexandria", permissions=[], pages=["vessels"])
        html = self.login("vonly").get("/").content.decode()
        nav = html[html.index('id="nav"'):html.index("</nav>")]
        self.assertEqual(re.findall(r'data-group="(\w+)"', nav), ["marine"])

    def test_admin_has_everything(self):
        me = self.me(self.login("admin").get("/"))
        self.assertEqual((me["permissions"], me["pages"]), (list(PERMISSION_KEYS), list(PAGE_KEYS)))

    def test_effective_lists_apply_dependencies(self):
        make_user("odd", "alexandria", permissions=["accounting.close"], pages=["calculations"])
        me = self.me(self.login("odd").get("/"))
        self.assertEqual((me["permissions"], me["pages"]), ([], ["vessels"]))


class TickGroupsTwinTests(TestCase):
    """js/tickGroups.js (the Accounts dialog's groups) names every permission and page once, with the server's needs."""

    def setUp(self):
        from pathlib import Path

        self.js = (Path(__file__).parent / "static/sheet/js/tickGroups.js").read_text(encoding="utf-8")

    def _block(self, name):
        import re

        body = re.search(name + r" = Object\.freeze\(([\s\S]*?)\n\]\);", self.js).group(1)
        return re.findall(r"'([a-z_.]+)'", re.sub(r"\['[A-Z][^']*', ", "[", body))

    def test_every_key_in_exactly_one_group(self):
        for name, keys in (("CAN_GROUPS", PERMISSION_KEYS), ("PAGE_GROUPS", PAGE_KEYS)):
            listed = self._block(name)
            self.assertEqual(sorted(listed), sorted(keys), name)

    def test_needs_equal_the_server(self):
        import re

        from .constants import PAGE_NEEDS, PERMISSION_NEEDS

        js = dict(re.findall(r"'(\w+:[a-z_.]+)': '(\w+:[a-z_.]+)'", self.js))
        server = {f"page:{k}": f"perm:{v}" for k, v in PAGE_NEEDS.items()}
        server |= {f"perm:{k}": f"{'perm' if kind == 'permission' else 'page'}:{v}"
                   for k, (kind, v) in PERMISSION_NEEDS.items()}
        self.assertEqual(js, server)
