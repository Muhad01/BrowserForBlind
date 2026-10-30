"""Celery application configuration for CIGHT-BROWSER.

CON-01: Celery runs all long browser/AI work (never inside HTTP views or Channels consumers).
"""
import os

from celery import Celery

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cight.settings")

app = Celery("cight")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()

