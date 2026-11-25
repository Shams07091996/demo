"""Transport became opt-in (the crew card's Transport button, `needsTransport`): every crew member that already has a
transfer linked to it gets the button pressed, so no existing transfer disappears. Nothing else changes."""

from django.db import migrations

_GROUPS = ("onSigners", "offSigners")


def press_transport(apps, schema_editor):
    Service = apps.get_model("sheet", "Service")
    Guest = apps.get_model("sheet", "Guest")
    linked = {}  # vessel id -> crew uids with a transfer
    for vessel_id, uid in Guest.objects.filter(transfer__isnull=False).exclude(crew_uid="").values_list(
            "transfer__vessel_id", "crew_uid"):
        linked.setdefault(vessel_id, set()).add(uid)
    for service in Service.objects.filter(service_type="Crew Change"):
        data = service.data if isinstance(service.data, dict) else {}
        uids = linked.get(service.vessel_id, set())
        changed = False
        for group in _GROUPS:
            for member in data.get(group) or []:
                if not isinstance(member, dict) or "needsTransport" in member:
                    continue
                member["needsTransport"] = member.get("uid") in uids
                changed = True
        if changed:
            Service.objects.filter(pk=service.pk).update(data=data)  # no signals: a migration writes no history


class Migration(migrations.Migration):
    dependencies = [("sheet", "0026_entry_uids")]

    operations = [migrations.RunPython(press_transport, migrations.RunPython.noop)]
