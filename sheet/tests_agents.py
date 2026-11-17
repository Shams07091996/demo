"""Agents per job: arrival / sailing agent on a vessel, an agent on every service, the missing-agent alert."""

from datetime import date

from django.test import TestCase

from .models import ChangeRecord, Service, Vessel
from .tests import FAST_HASHER, ApiTestCase


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


@FAST_HASHER
class AgentApiTests(ApiTestCase):
    pass
