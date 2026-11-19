"""The LOG letter: a hand-written PDF (standard library only) and the endpoint that serves it."""

import re
import shutil
import tempfile
from pathlib import Path

from django.test import SimpleTestCase, override_settings

from . import logpdf
from .models import ChangeRecord, Service
from .tests import ApiTestCase
from .validators import clean_service_data

FIELDS = {"to": "EGYPTAIR", "date": "19/11/2026", "vessel": "MSC AURORA",
          "flight": "MS 123 IST-ALY 13NOV 07:00 10:00", "personal": "JOHN SMITH\nRANK: 2/E\nNATIONALITY: BRITISH"}


def tiny_jpeg(width=20, height=10):
    """A JPEG header just good enough for jpeg_size: SOI, SOF0 (8-bit, 3 components), EOI."""
    sof = b"\xff\xc0\x00\x11\x08" + height.to_bytes(2, "big") + width.to_bytes(2, "big") + b"\x03" + b"\x01\x11\x00" * 3
    return b"\xff\xd8" + sof + b"\xff\xd9"


def page_count(pdf):
    return int(re.search(rb"/Type /Pages /Kids \[[^\]]*\] /Count (\d+)", pdf).group(1))


class LogPdfTests(SimpleTestCase):
    def build(self, images=None, **fields):
        return logpdf.build({**FIELDS, **fields}, images or {})

    def test_pdf_structure(self):
        pdf = self.build()
        self.assertTrue(pdf.startswith(b"%PDF-1.4"))
        self.assertTrue(pdf.endswith(b"%%EOF\n"))
        offset = int(re.search(rb"startxref\n(\d+)\n", pdf).group(1))
        self.assertEqual(pdf[offset:offset + 4], b"xref")
        for number, at in enumerate(re.findall(rb"(\d{10}) 00000 n", pdf), 1):
            self.assertTrue(pdf[int(at):].startswith(f"{number} 0 obj".encode()), number)

    def test_fields_present_no_braces(self):
        pdf = self.build()
        for text in (b"(TO:)", b"(EGYPTAIR)", b"(DATE:)", b"(19/11/2026)", b"(OUR REF.:)", b"(MSC AURORA)",
                     b"(XXXXXXXXXXXXXXXXX.)", b"(VISA UPON ARRIVAL IN EGYPT)", b"(RANK: 2/E)",
                     b"(A visa has been arranged before departure and will take care of him.)"):
            self.assertIn(text, pdf)
        for text in (b"{{", b"}}", b"PERSONAL DETAILS", b"FLIGHT DETAILS"):
            self.assertNotIn(text, pdf)

    def test_text_escaped(self):
        plain = self.build(flight="abc")
        tricky = self.build(flight="a(b)c\\d {{x}} %PDF")
        self.assertIn(b"(a\\(b\\)c\\\\d {{x}} %PDF)", tricky)
        self.assertEqual(plain.count(b" 0 obj\n"), tricky.count(b" 0 obj\n"))

    def test_winansi_fallback(self):
        self.assertEqual(logpdf.to_winansi("ŞĞİ Žž Иван"), b"SGI \x8e\x9e ????")
        self.assertEqual(logpdf.to_winansi("a\tb\x00\x07c"), b"a    bc")

    def test_long_text_adds_page(self):
        pdf = self.build(images={"logo": tiny_jpeg()}, flight="\n".join(f"LINE {i}" for i in range(200)))
        pages = page_count(pdf)
        self.assertGreaterEqual(pages, 2)
        self.assertEqual(pdf.count(b"/Im1 Do"), pages)  # the logo on every page

    def test_long_line_wrapped(self):
        pdf = self.build(flight="X" * 400)
        self.assertNotIn(b"X" * 200, pdf)

    def test_jpeg_size(self):
        self.assertEqual(logpdf.jpeg_size(tiny_jpeg(20, 10)), (20, 10))
        self.assertIsNone(logpdf.jpeg_size(b"\x89PNG\r\n\x1a\n...."))
        self.assertIsNone(logpdf.jpeg_size(b"\xff\xd8\xff"))

    def test_images_embedded_raw(self):
        logo = tiny_jpeg()
        pdf = self.build(images={"logo": logo, "stamp": logo, "footer": logo, "other": logo})
        self.assertEqual(pdf.count(b"/Filter /DCTDecode"), 3)
        self.assertIn(logo, pdf)
        self.assertNotIn(b"/DCTDecode", self.build())


@override_settings(RATE_LIMIT_EXPORTS_PER_USER=20)
class LogViewTests(ApiTestCase):
    def setUp(self):
        on = {"name": "J SMITH", "uid": "abcdef123456", "flightData": "MS 123 10:00", "personalData": "J SMITH",
              "flightStructured": {"segments": [{"airline": "EGYPTAIR", "flightNo": "MS 123"}]}}
        off = {"name": "A OFF", "uid": "0123456789ab"}
        data = clean_service_data("Crew Change", {"onSigners": [on], "offSigners": [off]})
        self.service = Service.objects.create(vessel=self.alex_vessel, service_type="Crew Change", data=data)

    def get(self, user, uid="abcdef123456", service=None):
        client = self.login(user)
        return client.get(f"/api/services/{(service or self.service).id}/log/{uid}/")

    def test_alex_gets_the_pdf(self):
        response = self.get("alex")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "application/pdf")
        self.assertEqual(response["Content-Disposition"], 'attachment; filename="LOG ALEX SHIP J SMITH.pdf"')
        self.assertEqual(response["X-Content-Type-Options"], "nosniff")
        self.assertIn(b"(EGYPTAIR)", response.content)
        record = ChangeRecord.objects.filter(object_type="service", action="letter").get()
        self.assertEqual((record.username, record.object_id, record.changes), ("alex", self.service.id,
                                                                            {"LOG letter": [None, "J SMITH"]}))

    def test_viewer_refused(self):
        self.assertEqual(self.get("viewer").status_code, 403)

    def test_other_port_not_found(self):
        self.assertEqual(self.get("suezuser").status_code, 404)

    def test_off_signer_or_unknown_uid_not_found(self):
        self.assertEqual(self.get("alex", uid="0123456789ab").status_code, 404)
        self.assertEqual(self.get("alex", uid="ffffffffffff").status_code, 404)

    def test_not_a_crew_change_not_found(self):
        self.assertEqual(self.get("admin", service=self.suez_service).status_code, 404)

    def test_anonymous_refused(self):
        from django.test import Client

        response = Client().get(f"/api/services/{self.service.id}/log/abcdef123456/")
        self.assertIn(response.status_code, (401, 302))

    def test_rate_limited(self):
        with override_settings(RATE_LIMIT_EXPORTS_PER_USER=2):
            client = self.login("alex")
            url = f"/api/services/{self.service.id}/log/abcdef123456/"
            codes = [client.get(url).status_code for _ in range(3)]
        self.assertEqual(codes, [200, 200, 429])

    def test_images_from_folder(self):
        folder = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, folder)
        Path(folder, "logo.jpg").write_bytes(tiny_jpeg())
        with override_settings(LETTERHEAD_DIR=folder):
            self.assertIn(b"/DCTDecode", self.get("alex").content)
        with override_settings(LETTERHEAD_DIR=""):
            self.assertNotIn(b"/DCTDecode", self.get("alex").content)
