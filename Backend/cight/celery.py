"""Celery application configuration for CIGHT-BROWSER.

CON-01: Celery runs all long browser/AI work (never inside HTTP views or Channels consumers).
"""
import os

from celery import Celery
from celery.signals import worker_ready

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "cight.settings")

app = Celery("cight")
app.config_from_object("django.conf:settings", namespace="CELERY")
app.autodiscover_tasks()


@app.on_after_configure.connect
def setup_periodic_tasks(sender, **kwargs):
    pass


@worker_ready.connect
def on_worker_ready(sender, **kwargs):
    """Reap abandoned or interrupted tasks upon worker startup (NFR-REL-02)."""
    try:
        from core.services.recovery import reap_stale_tasks
        reap_stale_tasks()
    except Exception as e:
        import structlog
        structlog.get_logger(__name__).warning("Failed to reap stale tasks on worker ready", error=str(e))

