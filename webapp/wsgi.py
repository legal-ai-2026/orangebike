"""
WSGI entry point for production (gunicorn).

Cloudflare Tunnel passes the full request path to the origin. When the
tunnel maps crowdsaasing.com/orangebike/* to this service, the app
receives requests at /orangebike/... — so we mount the Flask app
under that prefix using DispatcherMiddleware.

For local dev (URL_PREFIX unset or empty), the app mounts at root.
"""

import os
from werkzeug.middleware.dispatcher import DispatcherMiddleware
from werkzeug.wrappers import Response as WzResponse

from .app import app as flask_app


URL_PREFIX = os.environ.get("URL_PREFIX", "").rstrip("/")


def _not_found(environ, start_response):
    return WzResponse("Not Found", status=404, mimetype="text/plain")(environ, start_response)


if URL_PREFIX:
    application = DispatcherMiddleware(_not_found, {URL_PREFIX: flask_app})
else:
    application = flask_app
