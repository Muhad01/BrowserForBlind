"""WSGI config for CIGHT-BROWSER."""
import os

from django.core.wsgi import get_wsgi_application

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cight.settings")

application = get_wsgi_application()

