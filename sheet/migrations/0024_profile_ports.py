"""Roles become ports. Admins are the superusers; every other account works in its ports (home port + extras).

- a port role (alexandria, portsaid, damietta, suez) -> home port and only port;
- role "admin" without being a superuser -> every port, home Alexandria;
- role "readonly" (the accountants, who are going) -> turned off, no ports;
- superusers -> nothing stored (they have every port);
- anyone with staff status who isn't a superuser loses it (the admin pages are for admins only).
"""

from django.db import migrations, models

FIRST_PORTS = ["alexandria", "portsaid", "damietta", "suez"]


def convert(apps, schema_editor):
    Profile = apps.get_model("sheet", "Profile")
    User = apps.get_model("auth", "User")
    for profile in Profile.objects.select_related("user"):
        user = profile.user
        if user.is_superuser:
            profile.home_port, profile.ports = "", []
        elif profile.role in FIRST_PORTS:
            profile.home_port, profile.ports = profile.role, [profile.role]
        elif profile.role == "admin":
            profile.home_port, profile.ports = "alexandria", list(FIRST_PORTS)
        else:  # readonly
            profile.home_port, profile.ports = "", []
            user.is_active = False
        if user.is_staff and not user.is_superuser:
            user.is_staff = False
        profile.save(update_fields=["home_port", "ports"])
        user.save(update_fields=["is_active", "is_staff"])
    User.objects.filter(is_staff=True, is_superuser=False).update(is_staff=False)


class Migration(migrations.Migration):
    dependencies = [
        ("sheet", "0023_port"),
    ]

    operations = [
        migrations.AddField(
            model_name="profile",
            name="home_port",
            field=models.CharField(blank=True, max_length=20),
        ),
        migrations.AddField(
            model_name="profile",
            name="ports",
            field=models.JSONField(blank=True, default=list),
        ),
        migrations.RunPython(convert, migrations.RunPython.noop),
        migrations.RemoveField(
            model_name="profile",
            name="role",
        ),
    ]
