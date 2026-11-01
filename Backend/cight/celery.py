"""Celery application configuration for CIGHT-BROWSER.

CON-01: Celery runs all long browser/AI work (never inside HTTP views or Channels consumers).
"""
import os

from celery import Celery
from celery.signals import worker_ready, worker_shutdown

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
        from core.agent.worker_lock import try_acquire_browser_worker
        try_acquire_browser_worker()
    except Exception as e:
        import structlog
        structlog.get_logger(__name__).error("Failed to acquire browser worker lock", error=str(e))
    try:
        from core.services.recovery import reap_stale_tasks
        reap_stale_tasks()
    except Exception as e:
        import structlog
        structlog.get_logger(__name__).warning("Failed to reap stale tasks on worker ready", error=str(e))
    try:
        from core.services.screenshots import reap_old_screenshots
        reap_old_screenshots()
    except Exception as e:
        import structlog
        structlog.get_logger(__name__).warning("Failed to reap old screenshots on worker ready", error=str(e))


@worker_shutdown.connect
def on_worker_shutdown(sender, **kwargs):
    """Close every hosted Chromium instance when the worker process exits."""
    try:
        from core.agent.browser_host import reset_browser_host
        reset_browser_host()
    except Exception as e:
        import structlog
        structlog.get_logger(__name__).warning("Failed to close hosted browsers on shutdown", error=str(e))
    try:
        from core.agent.worker_lock import release_browser_worker_lock
        release_browser_worker_lock()
    except Exception as e:
        import structlog
        structlog.get_logger(__name__).warning("Failed to release browser worker lock", error=str(e))

