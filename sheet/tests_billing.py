"""Billing party and Cash / On account on services; their Calculations columns and filters."""

from .models import ChangeRecord, Customer, Service, Ship
from .tests import ApiTestCase


class ServiceBillingTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.blue = Customer.objects.create(name="Blue Owners")
        cls.red = Customer.objects.create(name="Red Managers")
        cls.ship = Ship.objects.create(name="ALEX SHIP", imo="9074729", customer=cls.blue)
        cls.alex_vessel.ship = cls.ship
        cls.alex_vessel.save()

    def add(self, client, **extra):
        status, vessel = self.call(client, "post", f"/api/vessels/{self.alex_vessel.id}/services/",
                                   {"type": "Landing", "data": {"entries": []}, **extra})
        self.assertEqual(status, 201, vessel)
        return vessel["services"][-1]

    def put(self, client, service, **extra):
        return self.call(client, "put", f"/api/services/{service['id']}/",
                         {"type": "Landing", "data": {"entries": []}, **extra})

    def test_new_service_defaults_to_account_and_ship_customer(self):
        service = self.add(self.login("alex"))
        self.assertEqual((service["billing"], service["billing_party"]),
                         ("account", {"id": self.blue.id, "name": "Blue Owners"}))

    def test_new_service_of_vessel_without_ship_has_no_party(self):
        status, vessel = self.call(self.login("suezuser"), "post", f"/api/vessels/{self.suez_vessel.id}/services/",
                                   {"type": "Landing", "data": {"entries": []}})
        self.assertEqual((status, vessel["services"][-1]["billing_party"]), (201, None))

    def test_billing_party_can_be_changed_or_emptied(self):
        alex = self.login("alex")
        service = self.add(alex, billing_party=self.red.id)
        self.assertEqual(service["billing_party"]["id"], self.red.id)
        status, vessel = self.put(alex, service, billing_party=None)
        self.assertEqual((status, vessel["services"][-1]["billing_party"]), (200, None))
        for bad in (999999, "1", True):
            self.assertEqual(self.put(alex, service, billing_party=bad)[0], 400, bad)

    def test_inactive_party_only_if_saved(self):
        alex = self.login("alex")
        service = self.add(alex, billing_party=self.red.id)
        Customer.objects.filter(pk=self.red.id).update(active=False)
        self.assertEqual(self.put(alex, service, billing_party=self.red.id)[0], 200)
        gone = Customer.objects.create(name="Gone", active=False)
        self.assertEqual(self.put(alex, service, billing_party=gone.id)[0], 400)

    def test_cash_saved_and_bad_value_refused(self):
        alex = self.login("alex")
        service = self.add(alex, billing="cash")
        self.assertEqual(service["billing"], "cash")
        status, body = self.put(alex, service, billing="credit")
        self.assertEqual((status, body["error"]), (400, "Choose Cash or On account."))

    def test_save_without_keys_keeps_values(self):
        alex = self.login("alex")
        service = self.add(alex, billing="cash", billing_party=self.red.id)
        status, vessel = self.put(alex, service)
        saved = vessel["services"][-1]
        self.assertEqual((status, saved["billing"], saved["billing_party"]["id"]), (200, "cash", self.red.id))

    def test_change_raises_version_and_is_in_history(self):
        alex = self.login("alex")
        service = self.add(alex)
        _, vessel = self.put(alex, service, billing="cash")
        self.assertEqual(vessel["services"][-1]["version"], service["version"] + 1)
        record = ChangeRecord.objects.filter(object_type="service", object_id=service["id"], action="update").last()
        self.assertIn("billing", record.changes)

    def test_closed_service_billing_locked(self):
        alex = self.login("alex")
        service = self.add(alex)
        Service.objects.filter(pk=service["id"]).update(acct_closed=True)
        status, body = self.put(alex, service, billing="cash")
        self.assertEqual(status, 400)
        self.assertIn("Accounting has closed this", body["error"])
