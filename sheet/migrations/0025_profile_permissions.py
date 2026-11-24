"""Access rework piece 2: per-person permissions and pages. Everyone who already has an account gets all of both,
so nobody loses anything on the day it lands; an Admin then takes away what each job doesn't need."""

from django.db import migrations, models

# Copied, not imported: a migration must keep working when constants.py changes later.
ALL_PERMISSIONS = [
    "vessels.edit", "vessels.delete", "services.edit", "services.cancel", "services.complete", "money.view",
    "money.edit", "bookings.edit", "customers.edit", "master.edit", "closures.edit", "disposal.edit", "exports",
    "documents", "history.view", "accounting.close",
]
ALL_PAGES = [
    "vessels", "services", "hotels", "transport", "closures", "disposal", "calculations", "dashboard", "ships",
    "customers", "master", "rates", "history",
]


def give_everything(apps, schema_editor):
    Profile = apps.get_model("sheet", "Profile")
    for profile in Profile.objects.all():
        profile.permissions, profile.pages = list(ALL_PERMISSIONS), list(ALL_PAGES)
        profile.save(update_fields=["permissions", "pages"])


class Migration(migrations.Migration):
    dependencies = [("sheet", "0024_profile_ports")]

    operations = [
        migrations.AddField(model_name="profile", name="permissions",
                            field=models.JSONField(blank=True, default=list)),
        migrations.AddField(model_name="profile", name="pages", field=models.JSONField(blank=True, default=list)),
        migrations.RunPython(give_everything, migrations.RunPython.noop),
    ]
