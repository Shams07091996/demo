"""Customers: contacts, agreed rates, linked ships; admins write, everyone reads."""

from datetime import date

from .models import Customer, CustomerContact, CustomerRate, Service, Ship, Vessel
from .tests import ApiTestCase, make_user

BLUE = {
    "name": "Blue Owners",
    "notes": "Pays monthly",
    "contacts": [
        {"name": "Mona Adel", "role": "Accounts", "email": "mona@example.com", "phone": "+20 (3) 555-0101"},
        {"name": "Karim", "role": "", "email": "", "phone": ""},
    ],
    "rates": {"Fresh Water": {"amount": 12.5, "currency": "USD"}, "Cash to Master": {"amount": 5}},
}


class CustomerApiTests(ApiTestCase):
    def create(self, payload=BLUE):
        return self.call(self.login("admin"), "post", "/api/customers/", payload)

    def test_admin_creates_customer_with_contacts_and_rates(self):
        status, customer = self.create()
        self.assertEqual(status, 201, customer)
        self.assertEqual((customer["name"], customer["notes"], customer["active"]), ("Blue Owners", "Pays monthly", True))
        self.assertEqual(customer["contacts"][0],
                         {"name": "Mona Adel", "role": "Accounts", "email": "mona@example.com", "phone": "+20 (3) 555-0101"})
        self.assertEqual(len(customer["contacts"]), 2)
        self.assertEqual(customer["rates"], {"Fresh Water": {"amount": 12.5, "currency": "USD"},
                                             "Cash to Master": {"amount": 5.0, "currency": "USD"}})
        self.assertEqual(customer["ships"], [])

    def test_customers_edit_writes_everyone_reads(self):
        self.create()
        make_user("reader", "alexandria", permissions=[])
        self.assertEqual(self.call(self.login("reader"), "post", "/api/customers/", {**BLUE, "name": "Other"})[0], 403)
        for name in ("alex", "viewer", "reader"):
            client = self.login(name)
            status, body = self.call(client, "get", "/api/customers/")
            self.assertEqual(status, 200)
            self.assertEqual(body["customers"][0]["rates"]["Fresh Water"]["amount"], 12.5)
            self.assertEqual(body["customers"][0]["contacts"][0]["email"], "mona@example.com")

    def test_update_replaces_contacts_and_rates(self):
        _, customer = self.create()
        status, body = self.call(self.login("admin"), "put", f"/api/customers/{customer['id']}/",
                                 {"name": "Blue Owners", "contacts": [], "rates": {"Landing": {"amount": 40, "currency": "EGP"}},
                                  "active": False})
        self.assertEqual(status, 200, body)
        self.assertEqual((body["contacts"], body["rates"], body["active"]),
                         ([], {"Landing": {"amount": 40.0, "currency": "EGP"}}, False))
        self.assertEqual(CustomerContact.objects.count(), 0)

    def test_bad_rates_refused_and_nothing_saved(self):
        _, customer = self.create()
        admin = self.login("admin")
        url = f"/api/customers/{customer['id']}/"
        for rates in ({"Others / Remarks": {"amount": 1}}, {"Cash to Master": {"amount": 101}},
                      {"Fresh Water": {"amount": -1}}, {"Unknown": {"amount": 1}}, {"Landing": {"amount": "x"}},
                      {"Landing": {}}, ["Landing"]):
            status, _ = self.call(admin, "put", url, {**BLUE, "contacts": [], "rates": rates})
            self.assertEqual(status, 400, rates)
        self.assertEqual(CustomerContact.objects.count(), 2)
        self.assertEqual(CustomerRate.objects.count(), 2)

    def test_contact_limits(self):
        good = BLUE["contacts"][0]
        for contacts in ([{**good, "email": "not-an-email"}], [{**good, "phone": "12ab"}], [good] * 21,
                         [{**good, "name": "x" * 101}], [{**good, "name": ""}]):
            self.assertEqual(self.create({**BLUE, "contacts": contacts})[0], 400)

    def test_name_unique_case_insensitive(self):
        self.create()
        self.assertEqual(self.create({**BLUE, "name": "blue owners"})[0], 400)
        self.assertEqual(self.create({**BLUE, "name": ""})[0], 400)

    def test_linked_ships_listed(self):
        _, customer = self.create()
        ship = Ship.objects.create(name="MSC AURORA", imo="9074729", customer_id=customer["id"])
        body = self.call(self.login("viewer"), "get", "/api/customers/")[1]
        self.assertEqual(body["customers"][0]["ships"], [{"id": ship.id, "name": "MSC AURORA", "imo": "9074729"}])

    def test_delete_refused_in_use(self):
        admin = self.login("admin")
        unused = Customer.objects.create(name="Unused")
        by_ship = Customer.objects.create(name="By ship")
        by_service = Customer.objects.create(name="By service")
        Ship.objects.create(name="X", imo="", customer=by_ship)
        vessel = Vessel.objects.create(name="X", date=date(2026, 11, 13), port="alexandria")
        Service.objects.create(vessel=vessel, service_type="Landing", billing_party=by_service)
        self.assertEqual(self.call(self.login("alex"), "delete", f"/api/customers/{unused.id}/")[0], 403)
        self.assertEqual(self.call(admin, "delete", f"/api/customers/{unused.id}/")[0], 200)
        for customer in (by_ship, by_service):
            status, body = self.call(admin, "delete", f"/api/customers/{customer.id}/")
            self.assertEqual((status, body["error"]), (400, "In use: mark it inactive instead."))


class CustomerSaveReviewTests(ApiTestCase):
    """A save never wipes contacts or rates by accident, and leaves unchanged ones alone (the History stays readable)."""

    def setUp(self):
        self.admin = self.login("admin")
        status, self.customer = self.call(self.admin, "post", "/api/customers/", BLUE)
        self.assertEqual(status, 201, self.customer)
        self.url = f"/api/customers/{self.customer['id']}/"

    def test_missing_or_malformed_contacts_or_rates_refused_and_nothing_lost(self):
        base = {"name": "Blue Owners", "contacts": BLUE["contacts"], "rates": BLUE["rates"]}
        for bad in ({k: v for k, v in base.items() if k != "contacts"}, {**base, "contacts": {}},
                    {**base, "contacts": "Mona"}, {k: v for k, v in base.items() if k != "rates"},
                    {**base, "rates": None}, {**base, "rates": ""}):
            status, body = self.call(self.admin, "put", self.url, bad)
            self.assertEqual(status, 400, (bad, body))
        self.assertEqual(CustomerContact.objects.count(), 2)
        self.assertEqual(CustomerRate.objects.count(), 2)

    def test_unchanged_save_touches_no_contact_or_rate(self):
        from .models import ChangeRecord
        before = ChangeRecord.objects.count()
        ids = sorted(CustomerContact.objects.values_list("id", flat=True)), sorted(CustomerRate.objects.values_list("id", flat=True))
        status, _ = self.call(self.admin, "put", self.url, {**BLUE, "notes": "Pays weekly"})
        self.assertEqual(status, 200)
        self.assertEqual((sorted(CustomerContact.objects.values_list("id", flat=True)),
                          sorted(CustomerRate.objects.values_list("id", flat=True))), ids)
        self.assertEqual(list(ChangeRecord.objects.filter(id__gt=before).values_list("object_type", flat=True)
                              if before else []), ["customer"])

    def test_one_changed_rate_is_one_update(self):
        from .models import ChangeRecord
        before = ChangeRecord.objects.order_by("-id").first().id
        rates = {**BLUE["rates"], "Fresh Water": {"amount": 13, "currency": "USD"}, "Landing": {"amount": 40, "currency": "EGP"}}
        status, body = self.call(self.admin, "put", self.url, {**BLUE, "rates": rates})
        self.assertEqual(status, 200, body)
        changes = sorted(ChangeRecord.objects.filter(id__gt=before).values_list("object_type", "action"))
        self.assertEqual(changes, [("customerrate", "create"), ("customerrate", "update")])
        self.assertEqual(body["rates"]["Fresh Water"]["amount"], 13.0)
