"""Page speed: the page names every script file up front, so the browser fetches them all at once."""

import re
from pathlib import Path

from django.conf import settings
from django.templatetags.static import static

from .tests import ApiTestCase

JS_DIR = Path(settings.BASE_DIR) / "sheet" / "static" / "sheet" / "js"
PRELOAD = re.compile(r'<link rel="modulepreload" href="([^"]+)">')


def all_scripts():
    return sorted(static("sheet/" + p.relative_to(JS_DIR.parent).as_posix()) for p in JS_DIR.rglob("*.js"))


class ModulePreloadTests(ApiTestCase):
    def test_page_preloads_every_script_file(self):
        html = self.login("alex").get("/").content.decode()
        self.assertEqual(sorted(PRELOAD.findall(html)), all_scripts())

    def test_preload_list_includes_nested_folders_and_main(self):
        urls = all_scripts()
        self.assertIn(static("sheet/js/main.js"), urls)
        self.assertIn(static("sheet/js/pages/history.js"), urls)
        self.assertGreater(len(urls), 20)

    def test_preloads_come_before_the_main_script(self):
        html = self.login("admin").get("/").content.decode()
        main_at = html.index('<script type="module" src="' + static("sheet/js/main.js"))
        self.assertLess(html.index('rel="modulepreload"'), main_at)

    def test_sign_in_page_preloads_nothing(self):
        self.assertNotIn("modulepreload", self.client.get("/login/").content.decode())
