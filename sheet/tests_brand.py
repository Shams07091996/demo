"""The company logo (brand.png in the letterhead folder, never in git) and the ARKAS brand on the pages."""

import tempfile
from pathlib import Path

from django.test import TestCase, override_settings

from .tests import FAST_HASHER, PASSWORD, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"rest of a picture"


class LogoFolder:
    """A temporary letterhead folder holding `content` as brand.png (None: no file)."""

    def __init__(self, content=PNG):
        self.content = content

    def __enter__(self):
        self.tmp = tempfile.TemporaryDirectory()
        if self.content is not None:
            Path(self.tmp.name, "brand.png").write_bytes(self.content)
        self.settings = override_settings(LETTERHEAD_DIR=self.tmp.name)
        self.settings.enable()
        return self

    def __exit__(self, *exc):
        self.settings.disable()
        self.tmp.cleanup()


@FAST_HASHER
class LogoTests(TestCase):
    def test_logo_served(self):
        with LogoFolder():
            response = self.client.get("/brand/logo.png")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Content-Type"], "image/png")
        self.assertEqual(response.content, PNG)
        self.assertIn("max-age=3600", response["Cache-Control"])

    def test_missing_logo_is_404(self):
        with LogoFolder(content=None):
            self.assertEqual(self.client.get("/brand/logo.png").status_code, 404)
        with override_settings(LETTERHEAD_DIR=""):
            self.assertEqual(self.client.get("/brand/logo.png").status_code, 404)

    def test_not_png_is_404(self):
        for content in (b"<html>", b"\xff\xd8\xff\xe0 a jpeg"):
            with LogoFolder(content):
                self.assertEqual(self.client.get("/brand/logo.png").status_code, 404, content)

    def test_too_big_is_404(self):
        with LogoFolder(PNG + b"x" * 500_001):
            self.assertEqual(self.client.get("/brand/logo.png").status_code, 404)

    def test_logo_open_during_two_step(self):
        make_user("alex", "alexandria")
        self.assertTrue(self.client.login(username="alex", password=PASSWORD))  # code step not passed
        with LogoFolder():
            self.assertEqual(self.client.get("/brand/logo.png").status_code, 200)

    def test_context_true_when_present(self):
        with LogoFolder():
            self.assertIs(self.client.get("/login/").context["brand_logo"], True)

    def test_context_false_for_not_png(self):
        with LogoFolder(b"<html>"):
            self.assertIs(self.client.get("/login/").context["brand_logo"], False)


TEMPLATES = Path(__file__).resolve().parent / "templates"


@FAST_HASHER
class BrandPageTests(TestCase):
    def signed_in(self):
        from .tests import pass_two_step

        make_user("alex", "alexandria")
        self.assertTrue(self.client.login(username="alex", password=PASSWORD))
        pass_two_step(self.client, "alex")

    def test_sidebar_shows_logo_and_name(self):
        self.signed_in()
        with LogoFolder():
            html = self.client.get("/").content.decode()
        self.assertIn('class="brand-logo"', html)
        self.assertIn("ARKAS<span>EGYPT HUSBANDRY</span>", html)
        self.assertNotIn("SERVICE SHEET", html)

    def test_pages_fall_back_to_anchor(self):
        self.signed_in()
        with LogoFolder(content=None):
            page = self.client.get("/").content.decode()
            self.client.logout()
            login = self.client.get("/login/").content.decode()
        for html in (page, login):
            self.assertIn("#i-anchor", html)
            self.assertNotIn("brand-logo", html)
            self.assertNotIn("login-brand", html)
        self.assertIn("ARKAS <span>EGYPT HUSBANDRY</span>", login)

    def test_login_shows_logo(self):
        with LogoFolder():
            html = self.client.get("/login/").content.decode()
        self.assertIn('class="login-brand"', html)
        self.assertIn("EGYPT HUSBANDRY", html)

    def test_error_pages_show_logo(self):
        from django.test import RequestFactory

        from . import views

        for content, expected, absent in ((PNG, "login-brand", "#i-anchor"), (None, "#i-anchor", "login-brand")):
            with LogoFolder(content):
                not_found = self.client.get("/no-such-page/").content.decode()
                error = views.server_error(RequestFactory().get("/x/")).content.decode()
            for html in (not_found, error):
                self.assertIn(expected, html)
                self.assertNotIn(absent, html)

    def test_titles(self):
        for page in TEMPLATES.rglob("*.html"):
            self.assertNotIn("Marine Service Sheet", page.read_text(encoding="utf-8"), page.name)
        index = (TEMPLATES / "sheet" / "index.html").read_text(encoding="utf-8")
        self.assertIn("<title>ARKAS Egypt Husbandry</title>", index)
