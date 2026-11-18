"""Two-step login: exception / forced-password / setup-window fields on Profile (existing profiles get a 72-hour setup
window from the moment this runs) and remembered computers."""

import django.db.models.deletion
import sheet.models
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('sheet', '0011_agents_per_job'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.AddField(
            model_name='profile',
            name='must_change_password',
            field=models.BooleanField(default=False, help_text='Set when someone else set the password: they choose their own at the next sign-in.'),
        ),
        migrations.AddField(
            model_name='profile',
            name='setup_until',
            field=models.DateTimeField(blank=True, default=sheet.models.default_setup_until, null=True, verbose_name='Authenticator setup allowed until'),
        ),
        migrations.AddField(
            model_name='profile',
            name='two_step_exempt',
            field=models.BooleanField(default=False, help_text='Signs in with the password only. Never for admins.', verbose_name='Two-step exception'),
        ),
        migrations.CreateModel(
            name='RememberedComputer',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('token_hash', models.CharField(max_length=64, unique=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('expires_at', models.DateTimeField()),
                ('last_used_at', models.DateTimeField(blank=True, null=True)),
                ('ip', models.CharField(blank=True, max_length=45, verbose_name='Address')),
                ('agent', models.CharField(blank=True, max_length=200, verbose_name='Browser')),
                ('user', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='remembered_computers', to=settings.AUTH_USER_MODEL)),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
    ]
