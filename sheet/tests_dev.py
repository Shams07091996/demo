"""Development server: static files must be re-checked by the browser, so an update never mixes old and new modules."""

from django.core.handlers.wsgi import WSGIHandler
from django.test import RequestFactory, SimpleTestCase, override_settings


@override_settings(DEBUG=True)
class DevStaticCachingTests(SimpleTestCase):
    def test_runserver_serves_static_files_with_no_cache(self):
        from sheet.management.commands.runserver import Command

        handler = Command().get_handler(use_static_handler=True, insecure_serving=True)
        request = RequestFactory().get("/static/sheet/js/crewParsing.js")
        response = handler.get_response(request)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response["Cache-Control"], "no-cache")

    def test_manage_py_runserver_uses_this_command(self):
        from django.core.management import get_commands

        self.assertEqual(get_commands()["runserver"], "sheet")

    def test_without_static_handling_the_app_handler_is_unchanged(self):
        from sheet.management.commands.runserver import Command

        handler = Command().get_handler(use_static_handler=False, insecure_serving=False)
        self.assertIsInstance(handler, WSGIHandler)
