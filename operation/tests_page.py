"""The page: the Operation folder and its items follow the ticks; Terminals is for Admins and the Edit terminals
tick."""

from sheet.constants import PERMISSION_KEYS
from sheet.tests import ApiTestCase, make_user


class PageTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        make_user("plain", "alexandria", pages=["vessels"])
        make_user("liveuser", "alexandria", permissions=[], pages=["op_live"])
        make_user("nomaster", "alexandria", permissions=[k for k in PERMISSION_KEYS if k != "operation.master"])

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

    def test_reports_in_the_reports_folder(self):
        import re
        html = self.page("alex")
        reports = html[html.index('data-group="reports"'):html.index('data-group="master"')]
        self.assertEqual(re.findall(r'data-page="(op_\w+)"', reports), ["op_analysis", "op_charts"])
        operation = html[html.index('data-group="operation"'):html.index('data-group="reports"')]
        self.assertNotIn('data-page="op_analysis"', operation)

    def test_reports_folder_for_a_report_page_alone(self):
        from sheet.tests import make_user
        make_user("chartsonly", "alexandria", permissions=[], pages=["op_charts"])
        html = self.page("chartsonly")
        self.assertIn('data-group="reports"', html)
        self.assertNotIn('data-group="operation"', html)

    def test_live_excel_button_with_exports(self):
        self.assertIn('data-act="live-export"', self.page("alex"))
        self.assertNotIn('data-act="live-export"', self.page("liveuser"))

    def test_folder_right_below_marine(self):
        html = self.page("alex")
        self.assertLess(html.index('data-group="marine"'), html.index('data-group="operation"'))
        self.assertLess(html.index('data-group="operation"'), html.index('data-group="reports"'))
        self.assertIn('data-act="opv-new"', html)

    def test_admin_has_terminals(self):
        html = self.page("admin")
        self.assertIn('data-page="terminals"', html)
        self.assertIn('id="page-terminals"', html)

    def test_vessel_list_comes_with_vessel_data(self):
        self.assertIn('data-page="op_list"', self.page("alex"))
        self.assertNotIn('data-page="op_list"', self.page("liveuser"))
        self.assertNotIn('id="page-op_list"', self.page("liveuser"))

    def test_terminals_for_the_tick(self):
        html = self.page("alex")  # make_user gives every tick
        self.assertIn('data-page="terminals"', html)
        self.assertIn('data-act="terminal-new"', html)
        html = self.page("nomaster")
        self.assertNotIn('data-page="terminals"', html)
        self.assertNotIn('id="page-terminals"', html)
        self.assertNotIn('data-act="vl-new"', html)
