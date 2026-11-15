"""`manage.py runserver`, with static files sent as `Cache-Control: no-cache`.

The front end is plain ES modules that import each other by relative URL. Django's development server sends them
without any caching header, so a browser may keep an old module after an update and combine it with a new one
("does not provide an export named ..."). `no-cache` makes the browser re-check every file on each load (an
unchanged file costs a short "304 Not Modified"). Development only: in production a web server serves static files.
"""

from django.contrib.staticfiles.handlers import StaticFilesHandler
from django.contrib.staticfiles.management.commands.runserver import Command as StaticRunserver


class NoCacheStaticFilesHandler(StaticFilesHandler):
    def serve(self, request):
        response = super().serve(request)
        response["Cache-Control"] = "no-cache"
        return response


class Command(StaticRunserver):
    def get_handler(self, *args, **options):
        handler = super().get_handler(*args, **options)
        if isinstance(handler, StaticFilesHandler):
            return NoCacheStaticFilesHandler(handler.application)
        return handler
