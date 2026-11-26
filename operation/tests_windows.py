"""Berthing windows: weekly slots of a line at a terminal (Mon = 0), kept like terminals, and the window nearest a
visit's ETA."""

from django.test import TestCase

from sheet.constants import PERMISSION_KEYS
from sheet.models import ChangeRecord
from sheet.tests import ApiTestCase, allow, make_user

from .models import BerthingWindow
from .tests_models import cairo, terminal
from .windows import nearest

URL = "/api/operation/windows/"
TUE_WED = {"line": "MAERSK", "start_day": 1, "start_time": "06:00", "end_day": 2, "end_time": "18:00"}


def window(term, line="MAERSK", start=(1, "06:00"), end=(2, "18:00")):
    from datetime import time
    h1, m1 = map(int, start[1].split(":"))
    h2, m2 = map(int, end[1].split(":"))
    return BerthingWindow.objects.create(terminal=term, line=line, start_day=start[0], start_time=time(h1, m1),
                                         end_day=end[0], end_time=time(h2, m2))


class WindowApiTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.aict = terminal("AICT - ALX", "alexandria")
        cls.psd = terminal("PSD EAST", "portsaid", berths=("1",))
        allow("line", "MAERSK", "ARKAS")
        make_user("nomaster", "alexandria", permissions=[k for k in PERMISSION_KEYS if k != "operation.master"])

    def post(self, user="alex", **changes):
        return self.call(self.login(user), "post", URL, {"terminal": self.aict.id, **TUE_WED, **changes})

    def test_create_and_list(self):
        status, body = self.post()
        self.assertEqual(status, 201, body)
        self.assertEqual((body["line"], body["start_day"], body["start_time"], body["end_day"], body["end_time"],
                          body["hours"], body["port"]), ("MAERSK", 1, "06:00", 2, "18:00", 36.0, "alexandria"))
        status, body = self.call(self.login("alex"), "get", URL)
        self.assertEqual([w["line"] for w in body["windows"]], ["MAERSK"])
        self.assertTrue(ChangeRecord.objects.filter(object_type="berthingwindow").exists())

    def test_wrap_over_week_end(self):
        status, body = self.post(start_day=5, start_time="20:00", end_day=0, end_time="06:00")
        self.assertEqual((status, body["hours"]), (201, 34.0))

    def test_end_equal_start_refused(self):
        status, body = self.post(end_day=1, end_time="06:00")
        self.assertEqual((status, body["error"]), (400, "The window must end at another time than it starts."))

    def test_bad_values_refused(self):
        for changes in ({"start_day": 7}, {"start_day": "x"}, {"start_time": "25:00"}, {"end_time": ""}):
            self.assertEqual(self.post(**changes)[0], 400, changes)
        self.assertEqual(self.post(line="")[1]["error"], "Choose a shipping line.")

    def test_overlap_same_terminal_line_refused(self):
        self.assertEqual(self.post()[0], 201)
        status, body = self.post(start_day=2, start_time="12:00", end_day=3, end_time="00:00")
        self.assertEqual((status, body["error"]), (400, "This window overlaps another window of MAERSK here."))

    def test_overlap_across_week_end_refused(self):
        self.assertEqual(self.post(start_day=5, start_time="20:00", end_day=0, end_time="06:00")[0], 201)
        self.assertEqual(self.post(start_day=6, start_time="10:00", end_day=6, end_time="12:00")[0], 400)

    def test_other_line_may_overlap(self):
        self.assertEqual(self.post()[0], 201)
        self.assertEqual(self.post(line="ARKAS")[0], 201)

    def test_edit_does_not_overlap_itself(self):
        _, body = self.post()
        status, body = self.call(self.login("alex"), "put", f"{URL}{body['id']}/",
                                 {"terminal": self.aict.id, **TUE_WED, "end_time": "20:00"})
        self.assertEqual((status, body["hours"]), (200, 38.0))

    def test_line_must_be_terminal_line(self):
        self.aict.lines = ["ARKAS"]
        self.aict.save()
        status, body = self.post()
        self.assertEqual((status, body["error"]), (400, "Shipping line: choose one of this terminal's lines."))

    def test_port_user_other_port(self):
        theirs = window(self.psd)
        status, body = self.call(self.login("alex"), "get", URL)
        self.assertNotIn(theirs.id, [w["id"] for w in body["windows"]])
        alex = self.login("alex")
        self.assertEqual(self.call(alex, "put", f"{URL}{theirs.id}/", {"terminal": self.psd.id, **TUE_WED})[0], 404)
        self.assertEqual(self.call(alex, "delete", f"{URL}{theirs.id}/")[0], 404)
        self.assertEqual(self.post(terminal=self.psd.id)[0], 403)

    def test_needs_master_tick_to_write(self):
        self.assertEqual(self.post("nomaster")[0], 403)
        self.assertEqual(self.call(self.login("nomaster"), "get", URL)[0], 200)

    def test_delete(self):
        _, body = self.post()
        self.assertEqual(self.call(self.login("alex"), "delete", f"{URL}{body['id']}/")[0], 200)
        self.assertFalse(BerthingWindow.objects.exists())

    def test_nearest_route(self):
        window(self.aict)
        alex = self.login("nomaster")
        status, body = self.call(alex, "get", f"{URL}nearest/?terminal={self.aict.id}&line=MAERSK&eta=2026-11-26T08:00")
        self.assertEqual(status, 200, body)
        self.assertEqual((body["nearest"]["start"], body["nearest"]["position"]), ("2026-11-24T06:00", "after"))
        _, body = self.call(alex, "get", f"{URL}nearest/?terminal={self.aict.id}&line=ARKAS&eta=2026-11-26T08:00")
        self.assertIsNone(body["nearest"])
        theirs = f"{URL}nearest/?terminal={self.psd.id}&line=MAERSK&eta=2026-11-26T08:00"
        self.assertEqual(self.call(alex, "get", theirs)[0], 404)


class NearestTests(TestCase):
    """2026-11-23 is a Monday."""

    @classmethod
    def setUpTestData(cls):
        cls.aict = terminal()
        cls.tue = window(cls.aict)  # Tue 06:00 → Wed 18:00
        cls.fri = window(cls.aict, start=(4, "22:00"), end=(5, "20:00"))  # Fri 22:00 → Sat 20:00

    def near(self, eta, windows=None):
        return nearest(windows or [self.tue, self.fri], cairo(eta))

    def test_before_the_next_window(self):
        found = self.near("2026-11-26T08:00")  # Thursday
        self.assertEqual((found["window"]["id"], found["start"], found["end"], found["position"], found["hours"]),
                         (self.fri.id, "2026-11-27T22:00", "2026-11-28T20:00", "before", 38.0))

    def test_inside(self):
        found = self.near("2026-11-25T10:00")
        self.assertEqual((found["window"]["id"], found["position"]), (self.tue.id, "inside"))

    def test_end_is_outside(self):
        found = self.near("2026-11-25T18:00")
        self.assertNotEqual(found["position"], "inside")
        self.assertEqual(found["window"]["id"], self.tue.id)  # its start (36 h before) is nearer than Friday's (52 h)

    def test_window_over_week_end(self):
        weekend = window(self.aict, line="X", start=(5, "20:00"), end=(0, "06:00"))
        found = self.near("2026-11-29T12:00", [weekend])  # Sunday
        self.assertEqual((found["position"], found["start"]), ("inside", "2026-11-28T20:00"))
        found = self.near("2026-11-23T03:00", [weekend])  # Monday early: last week's occurrence
        self.assertEqual((found["position"], found["start"]), ("inside", "2026-11-21T20:00"))

    def test_tie_goes_to_later(self):
        a = window(self.aict, line="Y", start=(0, "00:00"), end=(0, "01:00"))
        b = window(self.aict, line="Y", start=(2, "00:00"), end=(2, "01:00"))
        found = self.near("2026-11-24T00:00", [a, b])  # Tuesday 00:00: 24 h after Monday's, 24 h before Wednesday's
        self.assertEqual((found["window"]["id"], found["position"]), (b.id, "before"))

    def test_no_windows(self):
        self.assertIsNone(nearest([], cairo("2026-11-26T08:00")))
