"""The Operation pages and permissions: new ticks, off for existing accounts, edit / delete need Vessel Data."""

from sheet.constants import PAGE_KEYS, PERMISSION_KEYS, TEMPLATES
from sheet.models import Profile
from sheet.tests import ApiTestCase, make_user

OLD_PERMISSIONS = [k for k in PERMISSION_KEYS if not k.startswith("operation.")]
OLD_PAGES = [k for k in PAGE_KEYS if not k.startswith("op_")]
OPERATION_PAGES = ["op_vessels", "op_live", "op_analysis", "op_charts"]


class OperationTicksTests(ApiTestCase):
    def test_new_pages_and_permissions_exist(self):
        for page in OPERATION_PAGES:
            self.assertIn(page, PAGE_KEYS)
        self.assertIn("operation.edit", PERMISSION_KEYS)
        self.assertIn("operation.delete", PERMISSION_KEYS)
        self.assertEqual(len(PERMISSION_KEYS), 18)

    def test_existing_profile_does_not_get_them(self):
        user = make_user("oldtimer", "alexandria", permissions=OLD_PERMISSIONS, pages=OLD_PAGES)
        profile = Profile.objects.get(user=user)
        for page in OPERATION_PAGES:
            self.assertFalse(profile.sees(page))
        self.assertFalse(profile.can("operation.edit"))
        self.assertFalse(profile.can("operation.delete"))

    def test_branch_manager_template_has_them(self):
        manager = next(t for t in TEMPLATES if t[0] == "manager")
        self.assertIn("operation.edit", manager[2])
        self.assertIn("op_live", manager[3])
        for key, _label, _perms, pages in TEMPLATES:
            if key != "manager":
                self.assertFalse(set(pages) & set(OPERATION_PAGES))

    def test_edit_needs_vessel_data_page(self):
        user = make_user("editor", "alexandria", permissions=["operation.edit", "operation.delete"], pages=["op_live"])
        profile = Profile.objects.get(user=user)
        self.assertFalse(profile.can("operation.edit"))
        self.assertFalse(profile.can("operation.delete"))
        admin = self.login("admin")
        status, body = self.call(admin, "put", f"/api/accounts/{user.id}/",
                                 {"permissions": ["operation.edit"], "pages": ["op_live"]})
        self.assertEqual(status, 400)
        self.assertEqual(body["error"], "Add / edit and Delete vessel data need the Vessel Data page.")
        status, _ = self.call(admin, "put", f"/api/accounts/{user.id}/",
                              {"permissions": ["operation.edit"], "pages": ["op_vessels"]})
        self.assertEqual(status, 200)
        self.assertTrue(Profile.objects.get(user=user).can("operation.edit"))

    def test_accounts_list_counts_18(self):
        admin = self.login("admin")
        status, body = self.call(admin, "get", "/api/accounts/")
        self.assertEqual(status, 200)
        self.assertEqual(len(body["permissions"]), 18)
        alex = next(a for a in body["accounts"] if a["username"] == "alex")
        self.assertEqual(len(alex["permissions"]), 18)  # make_user gives every permission
