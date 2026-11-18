"""Last resort for a lost phone: `manage.py reset_two_step <username>` (normally a superuser does it in the admin
pages). Removes the person's Authenticator and remembered computers and opens a new 72-hour setup window."""

from django.contrib.auth.models import User
from django.core.management.base import BaseCommand, CommandError

from sheet import twostep


class Command(BaseCommand):
    help = "Reset a person's two-step login (lost phone): they set up Authenticator again at their next sign-in."

    def add_arguments(self, parser):
        parser.add_argument("username")

    def handle(self, *args, **options):
        user = User.objects.filter(username=options["username"]).first()
        if user is None:
            raise CommandError("No such user.")
        twostep.reset(user)
        self.stdout.write(f"Two-step login reset for {user.get_username()}: set up Authenticator within 72 hours.")
