"""The page: the Operation folder and its items follow the page ticks; Terminals is for Admins."""

from sheet.tests import ApiTestCase, make_user


class PageTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_user("plain", "alexandria", pages=["vessels"])
        make_user("liveuser", "alexandria", permissions=[], pages=["op_live"])

    def page(self, user):
        response = self.login(user).get("/")
        self.assertEqual(response.status_code, 200)
        return response.content.decode()

    def test_no_operation_page_no_folder(self):
        html = self.page("plain")
        self.assertNotIn('data-group="operation"', html)
        self.assertNotIn('id="page-op_live"', html)

    def test_one_page_one_item(self):
        html = self.page("liveuser")
        self.assertIn('data-group="operation"', html)
        self.assertIn('data-page="op_live"', html)
        self.assertNotIn('data-page="op_vessels"', html)
        self.assertIn('id="page-op_live"', html)
        self.assertNotIn('id="page-op_vessels"', html)
        self.assertNotIn('data-page="terminals"', html)

    def test_folder_right_below_marine(self):
        html = self.page("alex")
        self.assertLess(html.index('data-group="marine"'), html.index('data-group="operation"'))
        self.assertLess(html.index('data-group="operation"'), html.index('data-group="reports"'))
        self.assertIn('data-act="opv-new"', html)

    def test_admin_has_terminals(self):
        html = self.page("admin")
        self.assertIn('data-page="terminals"', html)
        self.assertIn('id="page-terminals"', html)
