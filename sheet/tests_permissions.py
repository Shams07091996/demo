"""Access rework piece 2: per-person permissions and pages (constants.PERMISSIONS / PAGES, Profile.can / sees)."""

from django.contrib.auth.models import User
from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase

from .constants import PAGE_KEYS, PERMISSION_KEYS, TEMPLATES
from .models import Profile
from .tests import make_user


def profile(username, ports="alexandria", permissions=None, pages=None):
    return make_user(username, ports, permissions=permissions, pages=pages).profile


class PermissionModelTests(TestCase):
    def test_admin_has_everything(self):
        admin = User.objects.create_superuser("root", password="x")
        p = Profile.objects.create(user=admin)
        self.assertTrue(all(p.can(key) for key in PERMISSION_KEYS))
        self.assertTrue(all(p.sees(page) for page in PAGE_KEYS))

    def test_user_has_only_ticked(self):
        p = profile("u", permissions=["vessels.edit"], pages=["vessels", "services"])
        self.assertTrue(p.can("vessels.edit"))
        self.assertFalse(p.can("vessels.delete"))
        self.assertTrue(p.sees("services"))
        self.assertFalse(p.sees("hotels"))
        self.assertTrue(profile("v", permissions=[], pages=[]).sees("vessels"))

    def test_dependencies_apply_when_checking(self):
        p = profile("u", permissions=["accounting.close", "history.view"], pages=["calculations", "rates", "history"])
        checks = lambda: [p.sees("calculations"), p.sees("rates"), p.sees("history"),  # noqa: E731
                          p.can("history.view"), p.can("accounting.close")]
        self.assertEqual(checks(), [False] * 5)
        p.permissions = [*p.permissions, "money.view"]
        self.assertEqual(checks(), [True] * 5)

    def test_close_needs_the_calculations_page(self):
        p = profile("u", permissions=["accounting.close", "money.view"], pages=["vessels"])
        self.assertFalse(p.can("accounting.close"))

    def test_unknown_keys_are_false(self):
        p = profile("u")
        self.assertFalse(p.can("nope"))
        self.assertFalse(p.sees("nope"))

    def test_templates_are_consistent(self):
        found = {key: (set(perms), set(pages)) for key, _, perms, pages in TEMPLATES}
        self.assertEqual(set(found), {"marine", "operations", "manager", "accounts"})
        for perms, pages in found.values():
            self.assertLessEqual(perms, set(PERMISSION_KEYS))
            self.assertLessEqual(pages, set(PAGE_KEYS))
            self.assertIn("vessels", pages)
            self.assertEqual("history" in pages, "history.view" in perms)
        self.assertEqual(found["manager"], (set(PERMISSION_KEYS), set(PAGE_KEYS)))
        self.assertEqual(found["accounts"][0], {"money.view", "exports", "history.view", "accounting.close"})
        self.assertEqual(found["operations"][0] - found["marine"][0],
                         {"services.cancel", "customers.edit", "bookings.edit"})
        self.assertEqual(found["marine"][0], {"vessels.edit", "services.edit", "services.complete", "money.edit"})

    def test_make_user_gives_everything_by_default(self):
        p = profile("u")
        self.assertEqual((p.permissions, p.pages), (list(PERMISSION_KEYS), list(PAGE_KEYS)))


class PermissionMigrationTests(TransactionTestCase):
    """Migration 0025: every existing person gets all permissions and all pages (nobody loses anything)."""

    def test_migration_gives_existing_profiles_everything(self):
        executor = MigrationExecutor(connection)
        executor.migrate([("sheet", "0024_profile_ports")])
        old = executor.loader.project_state([("sheet", "0024_profile_ports")]).apps
        OldUser, OldProfile = old.get_model("auth", "User"), old.get_model("sheet", "Profile")
        user = OldUser.objects.create(username="porter")
        OldProfile.objects.create(user=user, home_port="damietta", ports=["damietta"])
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(executor.loader.graph.leaf_nodes())
        stored = Profile.objects.get(user_id=user.pk)
        self.assertEqual((stored.permissions, stored.pages), (list(PERMISSION_KEYS), list(PAGE_KEYS)))
