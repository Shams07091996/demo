"""Agents per job: the vessel's agent becomes its arrival agent (renamed, data kept), plus a sailing agent and an agent
on every service."""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("sheet", "0010_change_history")]

    operations = [
        migrations.RenameField(model_name="vessel", old_name="agent", new_name="arrival_agent"),
        migrations.AlterField(
            model_name="vessel",
            name="arrival_agent",
            field=models.CharField(blank=True, max_length=100, verbose_name="Arrival agent"),
        ),
        migrations.AddField(
            model_name="vessel",
            name="sailing_agent",
            field=models.CharField(blank=True, max_length=100, verbose_name="Sailing agent"),
        ),
        migrations.AddField(
            model_name="service",
            name="agent",
            field=models.CharField(blank=True, max_length=100, verbose_name="Agent"),
        ),
    ]
