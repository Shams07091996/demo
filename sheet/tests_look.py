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


# Emoji, pictographs, dingbats, arrows (but the plain → of "old → new" / routes is text) and variation selectors.
EMOJI = re.compile("[←↑↓-⇿⌀-⏿①-➿⬀-⯿\U0001f000-\U0001ffff️]")
SPRITE_PATH = BASE / "sheet" / "templates" / "sheet" / "icons.svg"
DOM_JS = BASE / "sheet" / "static" / "sheet" / "js" / "dom.js"


def sprite():
    return SPRITE_PATH.read_text(encoding="utf-8") if SPRITE_PATH.exists() else ""


def icons_list():
    found = re.search(r"export const ICONS = Object\.freeze\(\[([^\]]*)\]\)", DOM_JS.read_text(encoding="utf-8"))
    return re.findall(r"'([a-z0-9-]+)'", found.group(1)) if found else []


class IconTests(SimpleTestCase):
    def test_no_emoji_in_templates_or_js(self):
        offenders = [f"{p.relative_to(BASE)}:{i}" for p in [*TEMPLATES, *JS_FILES]
                     for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1) if EMOJI.search(line)]
        self.assertEqual(offenders, [])

    def test_sprite_matches_icons_list(self):
        ids = re.findall(r'<symbol id="i-([a-z0-9-]+)"', sprite())
        self.assertTrue(ids)
        self.assertEqual(len(ids), len(set(ids)))
        self.assertEqual(sorted(ids), sorted(icons_list()))

    def test_every_used_icon_exists(self):
        known = set(re.findall(r'<symbol id="i-([a-z0-9-]+)"', sprite()))
        used = {m for p in JS_FILES for m in re.findall(r"\bicon\('([^']*)'", p.read_text(encoding="utf-8"))}
        used |= {m for p in TEMPLATES for m in re.findall(r'href="#i-([^"]*)"', p.read_text(encoding="utf-8"))}
        self.assertTrue(used)
        self.assertEqual(used - known, set())

    def test_sprite_is_plain(self):
        text = sprite()
        self.assertTrue(text.startswith("<svg "))
        for bad in ("<script", "href", "<use", "<image", "<foreignObject", "style", "{%", "{{"):
            self.assertNotIn(bad, text, bad)
        self.assertNotRegex(text, r"\son[a-z]+\s*=")

    def test_pages_with_icons_include_the_sprite(self):
        for page in TEMPLATES:
            text = page.read_text(encoding="utf-8")
            if 'href="#i-' in text:
                self.assertIn('{% include "sheet/icons.svg" %}', text, page.name)


def luminance(hex_colour):
    h = hex_colour.strip().lstrip("#")
    if len(h) == 3:
        h = "".join(c * 2 for c in h)
    channels = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    r, g, b = (c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in channels)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a, b):
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


class TidyTests(SimpleTestCase):
    def test_css_has_no_gradients_or_glow(self):
        self.assertNotIn("gradient(", CSS)
        self.assertNotIn("text-transform:uppercase", CSS.replace(" ", ""))
        self.assertNotRegex(CSS, r"letter-spacing:\s*[1-9]")
        self.assertNotIn("max-width:1500px", CSS)
        blurs = [int(b) for b in re.findall(r"box-shadow:[^;}]*?\d+px\s+\d+px\s+(\d+)px", CSS)]
        self.assertTrue(all(b <= 12 for b in blurs), blurs)

    def test_pages_use_the_full_width(self):
        page = re.search(r"\.page\{([^}]*)\}", CSS).group(1)
        self.assertNotIn("max-width", page)
        self.assertIn("padding:18px", page)

    def test_print_uses_light_tokens(self):
        block = re.search(r"@media print\{(.*?)\n\}", CSS, re.S).group(1)
        tokens = dict(re.findall(r"(--[a-z0-9-]+):([^;}]+)", block))
        self.assertGreater(contrast(tokens["--text"], tokens["--bg"]), 7)
        self.assertGreater(luminance(tokens["--bg"]), 0.9)
        self.assertGreater(luminance(tokens["--surface"]), 0.9)

    def test_token_contrast(self):
        for mode, tokens in (("light", light_tokens()), ("dark", dark_tokens())):
            for fg in ("--text", "--muted"):
                for bg in ("--bg", "--surface", "--surface2"):
                    self.assertGreaterEqual(contrast(tokens[fg], tokens[bg]), 4.5, f"{mode} {fg} on {bg}")
            for fg in ("--danger", "--success", "--warning", "--accent"):
                self.assertGreaterEqual(contrast(tokens[fg], tokens["--surface"]), 4.5, f"{mode} {fg}")
            self.assertGreaterEqual(contrast(tokens["--accent-text"], tokens["--accent"]), 4.5, f"{mode} button text")
            for i in range(1, 9):
                self.assertGreaterEqual(contrast(tokens[f"--c{i}"], tokens["--surface"]), 3, f"{mode} --c{i}")
