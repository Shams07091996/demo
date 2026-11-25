"""Every line of a Delivery Parcels / Delivery Courier / Landing service gets a stable uid (12 hex), like crew
members: a person without money.edit saves lines without their money, and the stored money is put back by uid."""

import re
import secrets

from django.db import migrations

UID_RE = re.compile(r"^[0-9a-f]{12}$")
MULTI_TYPES = ("Delivery Parcels", "Delivery Courier", "Landing")


def give_uids(apps, schema_editor):
    Service = apps.get_model("sheet", "Service")
    for service in Service.objects.filter(service_type__in=MULTI_TYPES).iterator():
        entries = (service.data or {}).get("entries")
        if not isinstance(entries, list):
            continue
        seen, changed = set(), False
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            uid = entry.get("uid")
            if not (isinstance(uid, str) and UID_RE.match(uid)) or uid in seen:
                uid = secrets.token_hex(6)
                while uid in seen:
                    uid = secrets.token_hex(6)
                entry["uid"] = uid
                changed = True
            seen.add(uid)
        if changed:
            service.save(update_fields=["data"])


class Migration(migrations.Migration):
    dependencies = [("sheet", "0025_profile_permissions")]

    operations = [migrations.RunPython(give_uids, migrations.RunPython.noop)]
