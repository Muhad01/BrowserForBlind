"""Perception screenshot storage and retention (TBD-04, NFR-SEC-07)."""
from datetime import timedelta
from pathlib import Path

import structlog
from django.conf import settings
from django.utils import timezone

logger = structlog.get_logger(__name__)


def screenshot_dir() -> Path:
    path = Path(getattr(settings, "SCREENSHOT_DIR", Path(settings.MEDIA_ROOT) / "screens"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def screenshot_path_for_task(task_id: str) -> Path:
    return screenshot_dir() / f"{task_id}.jpg"


def save_screenshot(task_id: str, jpeg_bytes: bytes | None) -> str:
    """Write a JPEG under MEDIA_ROOT/screens/<task_id>.jpg and return the relative ref."""
    if not jpeg_bytes:
        return ""
    path = screenshot_path_for_task(task_id)
    path.write_bytes(jpeg_bytes)
    return f"screens/{task_id}.jpg"


def reap_old_screenshots(older_than_days: int | None = None) -> int:
    """Delete screenshot files older than SCREENSHOT_RETENTION_DAYS (default 7)."""
    days = (
        older_than_days
        if older_than_days is not None
        else int(getattr(settings, "SCREENSHOT_RETENTION_DAYS", 7))
    )
    cutoff = timezone.now() - timedelta(days=days)
    cutoff_ts = cutoff.timestamp()
    removed = 0
    folder = screenshot_dir()
    for path in folder.glob("*.jpg"):
        try:
            if path.stat().st_mtime < cutoff_ts:
                path.unlink()
                removed += 1
        except OSError as err:
            logger.warning("screenshot_reap_failed", path=str(path), error=str(err))
    if removed:
        logger.info("screenshot_reap_complete", removed=removed)
    return removed
