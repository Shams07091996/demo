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


def page_contents(pdf):
    """Each page's content stream, in page order (image streams carry more keys, so they are not matched)."""
    return re.findall(rb"<< /Length \d+ >>\nstream\n(.*?)\nendstream", pdf, re.S)


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

    def stamp_and_visa_y(self, pdf):
        stamp_y = float(re.search(rb" ([\d.]+) cm /Im2 Do", pdf).group(1))
        visa_y = float(re.search(rb"([\d.]+) Td \(VISA UPON ARRIVAL IN EGYPT\)", pdf).group(1))
        return stamp_y, visa_y

    def test_stamp_beside_the_personal_details(self):
        # The stamp sits right of the (short) personal lines, on their page, above the closing lines.
        logo = tiny_jpeg(20, 10)
        flight = "\n".join(["FLIGHT     EK 337 - EMIRATES" + " " * 40 + "TUE 17 NOVEMBER 2026"] * 18)
        personal = "\n".join(f"Line {i}: SHORT" for i in range(12))
        pdf = self.build(images={"logo": logo, "stamp": tiny_jpeg(409, 369), "footer": tiny_jpeg(724, 106)},
                         flight=flight, personal=personal)
        self.assertEqual(page_count(pdf), 2)
        self.assertIn(b"/Im2 Do", page_contents(pdf)[1])
        stamp_y, visa_y = self.stamp_and_visa_y(pdf)
        self.assertGreater(stamp_y, visa_y)  # above the closing lines, not after them

    def test_bold_labels_and_personal_details_on_page_two(self):
        # User's request (2026-11-20): "Flight:" and "Personal details:" in bold, the personal details and the
        # stamp on a page of their own.
        pdf = self.build(images={"logo": tiny_jpeg(), "stamp": tiny_jpeg(409, 369)}, flight="EK 337",
                         personal="RANK: 2/E")
        first, second = page_contents(pdf)
        self.assertRegex(first, rb"/F2 [\d.]+ Tf [\d. ]+ Td \(Flight:\) Tj")
        self.assertIn(b"(EK 337)", first)
        self.assertNotIn(b"(RANK: 2/E)", first)
        self.assertRegex(second, rb"/F2 [\d.]+ Tf [\d. ]+ Td \(Personal details:\) Tj")
        self.assertIn(b"(RANK: 2/E)", second)
        self.assertIn(b"/Im2 Do", second)
        self.assertNotIn(b"/Im2 Do", first)
        self.assertIn(b"/Im1 Do", second)  # the logo on the new page too
        self.assertLess(second.index(b"(Personal details:)"), second.index(b"(RANK: 2/E)"))

    def test_stamp_after_the_text_when_personal_lines_are_wide(self):
        pdf = self.build(images={"stamp": tiny_jpeg(409, 369)}, personal="X" * 90)
        stamp_y, visa_y = self.stamp_and_visa_y(pdf)
        self.assertLess(stamp_y, visa_y)

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


RECEIPT = {"port": "Alexandria", "date": "20/11/2026", "vessel": "MSC AURORA",
           "services": "Arrange 5 shore pass with cost $50\nLanding with cost $120"}


class ReceiptPdfTests(SimpleTestCase):
    def test_receipt_text(self):
        pdf = logpdf.build_receipt(RECEIPT, {})
        for text in (b"(Alexandria: 20/11/2026)", b"(MV/ MSC AURORA)", b"(WHOM IT MAY CONCERN)",
                     b"(Arrange 5 shore pass with cost $50)", b"(Landing with cost $120)", b"(Master)",
                     b"(Ship's stamp)"):
            self.assertIn(text, pdf)
        self.assertIn(b"master of m/v MSC AURORA", pdf)
        self.assertIn(b"ARKAS EGYPT SAE", pdf)
        self.assertNotIn(b"{{", pdf)

    def test_receipt_has_logo_and_footer_but_no_stamp(self):
        jpeg = tiny_jpeg()
        pdf = logpdf.build_receipt(RECEIPT, {"logo": jpeg, "stamp": jpeg, "footer": jpeg})
        self.assertIn(b"/Im1 Do", pdf)
        self.assertIn(b"/Im3 Do", pdf)
        self.assertNotIn(b"/Im2", pdf)  # neither drawn nor embedded
        self.assertEqual(pdf.count(b"/Filter /DCTDecode"), 2)

    def test_receipt_long_services_add_page_signature_after_text(self):
        services = "\n".join(f"Service line {i} with cost $10" for i in range(120))
        pdf = logpdf.build_receipt({**RECEIPT, "services": services}, {"logo": tiny_jpeg()})
        self.assertGreaterEqual(page_count(pdf), 2)
        pages = page_contents(pdf)
        self.assertIn(b"(Ship's stamp)", pages[-1])
        self.assertIn(b"/Im1 Do", pages[-1])  # the logo on every page
        everything = b"\n".join(pages)  # in reading order; "Master" may start a page when there is no room to sign
        self.assertLess(everything.index(b"(Service line 119 with cost $10)"), everything.index(b"(Master)"))
        self.assertLess(everything.index(b"(Master)"), everything.index(b"(Ship's stamp)"))

    def test_receipt_room_to_stamp_whatever_the_length(self):
        # Review finding: near the page foot only ~18 mm stayed under "Ship's stamp"; a ship's stamp needs ~40 mm.
        bottom = 30 + 20  # no footer picture: the layout's bottom margin
        for count in range(1, 60):
            services = "\n".join(f"Line {i}" for i in range(count))
            pdf = logpdf.build_receipt({**RECEIPT, "services": services}, {})
            stamp_y = float(re.search(rb"([\d.]+) Td \(Ship's stamp\)", pdf).group(1))
            self.assertGreaterEqual(stamp_y - bottom, 110, count)

    def test_receipt_text_escaped(self):
        pdf = logpdf.build_receipt({**RECEIPT, "services": "a(b)c\\d {{x}} عربي"}, {})
        self.assertIn(b"(a\\(b\\)c\\\\d {{x}} ????)", pdf)


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

    def test_date_after_the_airline_is_left_out(self):
        # Crew saved before the parser fix: "EMIRATES   TUE 17 NOVEMBER 2026" was stored as the airline.
        data = self.service.data
        data["onSigners"][0]["flightStructured"]["segments"][0]["airline"] = "EMIRATES        TUE 17 NOVEMBER 2026"
        Service.objects.filter(pk=self.service.pk).update(data=data)
        pdf = self.get("alex").content
        self.assertIn(b"(EMIRATES)", pdf)
        self.assertNotIn(b"TUE 17", pdf.split(b"(DATE:)")[0])

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
