"""Terminal pictures: files in <letterhead folder>/terminals/<CODE>.png|.jpg on the server, never uploaded through the
app. Served only to people who see that terminal; PNG / JPEG checked by their first bytes, 1 MB at most."""

import tempfile
from pathlib import Path

from django.test import override_settings

from sheet.tests import ApiTestCase, make_user

from .tests_models import terminal

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 32
JPEG = b"\xff\xd8\xff\xe0" + b"\x00" * 32


class PictureTests(ApiTestCase):
    @classmethod
    def setUpTestData(cls):
        super().setUpTestData()
        cls.aict = terminal("AICT - ALX", "alexandria", code="EGAIT")
        cls.acchco = terminal("ACCHCO - ALX", "alexandria", code="EGALY")
        cls.psd = terminal("PSD EAST", "portsaid", code="PSDE")
        cls.odd = terminal("ODD - ALX", "alexandria", code="../X")
        make_user("novessels", "alexandria", permissions=[], pages=["vessels"])

    def setUp(self):
        super().setUp()
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        pictures = Path(self.folder.name, "terminals")
        pictures.mkdir()
        (pictures / "EGAIT.png").write_bytes(PNG)
        (pictures / "EGALY.jpg").write_bytes(JPEG)
        (pictures / "PSDE.png").write_bytes(PNG)
        override = override_settings(LETTERHEAD_DIR=self.folder.name)
        override.enable()
        self.addCleanup(override.disable)

    def url(self, term):
        return f"/api/operation/terminals/{term.id}/picture/"

    def test_png_and_jpeg_served(self):
        alex = self.login("alex")
        response = alex.get(self.url(self.aict))
        self.assertEqual((response.status_code, response["Content-Type"], response.content), (200, "image/png", PNG))
        self.assertIn("private", response["Cache-Control"])
        response = alex.get(self.url(self.acchco))
        self.assertEqual((response.status_code, response["Content-Type"]), (200, "image/jpeg"))

    def test_terminal_list_says_which_have_one(self):
        _, body = self.call(self.login("alex"), "get", "/api/operation/terminals/")
        self.assertEqual({t["name"]: t["picture"] for t in body["terminals"]},
                         {"AICT - ALX": True, "ACCHCO - ALX": True, "ODD - ALX": False})

    def test_other_ports_terminal_is_404(self):
        self.assertEqual(self.login("alex").get(self.url(self.psd)).status_code, 404)

    def test_needs_an_operation_page(self):
        self.assertEqual(self.login("novessels").get(self.url(self.aict)).status_code, 403)

    def test_missing_wrong_type_too_big_or_odd_code_is_404(self):
        alex = self.login("alex")
        pictures = Path(self.folder.name, "terminals")
        (pictures / "EGAIT.png").write_bytes(b"<svg>not a picture</svg>")
        self.assertEqual(alex.get(self.url(self.aict)).status_code, 404)
        (pictures / "EGAIT.png").write_bytes(PNG + b"\x00" * 1_000_001)
        self.assertEqual(alex.get(self.url(self.aict)).status_code, 404)
        (pictures / "EGAIT.png").unlink()
        self.assertEqual(alex.get(self.url(self.aict)).status_code, 404)
        Path(self.folder.name, "X.png").write_bytes(PNG)  # "../X" must never reach outside terminals/
        self.assertEqual(alex.get(self.url(self.odd)).status_code, 404)

    def test_no_letterhead_folder_is_404(self):
        with override_settings(LETTERHEAD_DIR=""):
            self.assertEqual(self.login("alex").get(self.url(self.aict)).status_code, 404)
