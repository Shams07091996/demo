"""The look: theme tokens for dark / light mode, the system font, no Google Fonts, the theme cookie."""

import re
from pathlib import Path

from django.conf import settings
from django.test import SimpleTestCase

from .tests import FAST_HASHER, ApiTestCase

BASE = Path(settings.BASE_DIR)
CSS = (BASE / "sheet" / "static" / "sheet" / "app.css").read_text(encoding="utf-8")
JS_FILES = sorted((BASE / "sheet" / "static" / "sheet" / "js").rglob("*.js"))
TEMPLATES = sorted((BASE / "sheet" / "templates").rglob("*.html"))

LIGHT = {"--bg": "#f6f7f8", "--surface": "#fff", "--line": "#e1e3e6", "--text": "#1b1d20", "--muted": "#646a73",
         "--accent": "#2563eb"}
DARK = {"--bg": "#141517", "--surface": "#1c1e21", "--surface2": "#232529", "--line": "#2c2f34", "--text": "#e8e9eb",
        "--muted": "#9a9ea6", "--accent": "#4c8dff"}
TOKENS = ["--bg", "--surface", "--surface2", "--line", "--text", "--muted", "--accent", "--accent-text", "--danger",
          "--warning", "--success", *(f"--c{i}" for i in range(1, 9))]

# A token block: a rule whose selector mentions :root and whose body only declares custom properties.
TOKEN_BLOCK = re.compile(r"(:root[^{}]*)\{((?:\s*--[a-z0-9-]+\s*:[^;{}]+;?)+\s*)\}")


def token_blocks():
    """{selector: {name: value}} of every token block in app.css."""
    return {
        sel.strip(): dict(re.findall(r"(--[a-z0-9-]+)\s*:\s*([^;]+)", body))
        for sel, body in TOKEN_BLOCK.findall(CSS)
    }


def light_tokens():
    return token_blocks()[":root"]


def dark_tokens():
    return next(v for k, v in token_blocks().items() if k == ':root[data-theme="dark"]')


class TokenTests(SimpleTestCase):
    def test_tokens_present_for_both_modes(self):
        light, dark = light_tokens(), dark_tokens()
        for name in TOKENS:
            self.assertIn(name, light, name)
            self.assertIn(name, dark, name)
        for name, value in LIGHT.items():
            self.assertEqual(light[name].strip(), value, name)
        for name, value in DARK.items():
            self.assertEqual(dark[name].strip(), value, name)

    def test_dark_follows_the_system_unless_light_was_chosen(self):
        self.assertRegex(CSS, r'@media\s*\(prefers-color-scheme:\s*dark\)\s*\{\s*:root:not\(\[data-theme="light"\]\)\{')

    def test_css_colours_only_in_token_blocks(self):
        rest = TOKEN_BLOCK.sub("", CSS)
        self.assertEqual(re.findall(r"#[0-9a-fA-F]{3,8}\b", rest), [])
        self.assertEqual(re.findall(r"\b(?:rgba?|hsla?)\(", rest), [])

    def test_js_has_no_hex_colours(self):
        offenders = [f"{p.name}: {m}" for p in JS_FILES
                     for m in re.findall(r"""['"`]#[0-9a-fA-F]{3,8}['"`]""", p.read_text(encoding="utf-8"))]
        self.assertEqual(offenders, [])

    def test_js_uses_only_declared_tokens(self):
        declared = set(light_tokens()) | {n for block in token_blocks().values() for n in block}
        used = {m for p in JS_FILES for m in re.findall(r"var\((--[a-z0-9-]+)\)", p.read_text(encoding="utf-8"))}
        self.assertEqual(used - declared, set())

    def test_css_uses_only_declared_tokens(self):
        declared = {n for block in token_blocks().values() for n in block}
        used = set(re.findall(r"var\((--[a-z0-9-]+)\)", CSS))
        self.assertEqual(used - declared, set())

    def test_system_font_and_no_bebas(self):
        self.assertNotIn("Bebas", CSS)
        self.assertNotIn("DM Sans", CSS)
        self.assertIn('"Segoe UI", system-ui, -apple-system, Roboto, sans-serif', CSS)


class NoGoogleTests(SimpleTestCase):
    def test_templates_load_no_google_fonts(self):
        self.assertEqual([p.name for p in TEMPLATES if "fonts.googleapis" in p.read_text(encoding="utf-8")], [])


@FAST_HASHER
class ThemeCookieTests(ApiTestCase):
    def test_csp_has_no_google_hosts(self):
        for response in (self.login("admin").get("/"), self.client.get("/login/")):
            csp = response["Content-Security-Policy"]
            self.assertNotIn("googleapis", csp)
            self.assertNotIn("gstatic", csp)
            self.assertIn("font-src 'none'", csp)

    def html_tag(self, client, url):
        return re.search(r"<html[^>]*>", client.get(url).content.decode()).group(0)

    def test_theme_cookie_renders_data_theme(self):
        client = self.login("admin")
        for value in ("dark", "light"):
            client.cookies["theme"] = value
            self.client.cookies["theme"] = value
            self.assertEqual(self.html_tag(client, "/"), f'<html lang="en" data-theme="{value}">')
            self.assertEqual(self.html_tag(self.client, "/login/"), f'<html lang="en" data-theme="{value}">')

    def test_bad_theme_cookie_is_ignored(self):
        client = self.login("admin")
        for value in ("red", "<b>x</b>", "d" * 500, "Dark"):
            client.cookies["theme"] = value
            self.assertEqual(self.html_tag(client, "/"), '<html lang="en">')
