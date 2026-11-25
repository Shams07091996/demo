"""Visit figures, checked against the user's workbook (Vessel Data columns O, P, Q, T, U, AH)."""

from datetime import date, timedelta

from django.test import SimpleTestCase

from .figures import average, figures, live_rate, report_date, status
from .models import Visit
from .tests_models import cairo


def allegri(**changes):
    values = {"vessel_name": "ALLEGRI", "shipping_line": "ARKAS", "eta": cairo("2026-11-20T06:00"),
              "ata": cairo("2026-11-20T07:00"), "atb": cairo("2026-11-20T11:00"), "atd": cairo("2026-11-21T22:00"),
              "discharge": 700, "loading": 800}
    return Visit(**{**values, **changes})


class FigureTests(SimpleTestCase):
    def test_the_workbooks_allegri(self):
        self.assertEqual(figures(allegri()), {"status": "Completed", "waiting": 4.0, "operation": 35.0,
                                              "port_stay": 39.0, "total_moves": 1500, "productivity": 42.9})

    def test_status(self):
        self.assertEqual(status(allegri(atb=None, atd=None)), "Planned")
        self.assertEqual(status(allegri(atd=None)), "Working")
        self.assertEqual(status(allegri()), "Completed")

    def test_blanks(self):
        result = figures(allegri(ata=None, atd=None, discharge=None))
        self.assertEqual((result["waiting"], result["operation"], result["port_stay"]), (None, None, None))
        self.assertEqual(result["total_moves"], 800)
        self.assertIsNone(result["productivity"])
        self.assertIsNone(figures(allegri(discharge=None, loading=None))["total_moves"])

    def test_zero_operation_hours_has_no_productivity(self):
        self.assertIsNone(figures(allegri(atd=cairo("2026-11-20T11:00")))["productivity"])

    def test_live_rate(self):
        working = allegri(atb=cairo("2026-11-20T10:00"), atd=None, discharge=150, loading=250)
        self.assertEqual(live_rate(working, cairo("2026-11-20T14:00")), 100.0)
        self.assertIsNone(live_rate(allegri(atd=None, discharge=None, loading=None), cairo("2026-11-20T14:00")))
        self.assertIsNone(live_rate(working, cairo("2026-11-20T10:00") + timedelta(minutes=5)))
        self.assertIsNone(live_rate(allegri(atb=None, atd=None), cairo("2026-11-20T14:00")))

    def test_report_date_is_ata_else_eta(self):
        self.assertEqual(report_date(allegri(eta=cairo("2026-11-19T23:00"))), date(2026, 11, 20))
        self.assertEqual(report_date(allegri(ata=None, eta=cairo("2026-11-19T23:00"))), date(2026, 11, 19))

    def test_average(self):
        self.assertEqual(average([None, 2, 3]), 2.5)
        self.assertEqual(average([1, 2, 2]), 1.7)
        self.assertIsNone(average([]))
        self.assertIsNone(average([None]))
