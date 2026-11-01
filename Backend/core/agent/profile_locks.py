"""Stale Chromium profile lock cleanup (NFR-REL-02). Never kills processes."""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import structlog

logger = structlog.get_logger(__name__)

LOCK_NAMES = ("SingletonLock", "SingletonSocket", "SingletonCookie")
_CHROME_NAMES = {"chrome", "chrome.exe", "chromium", "chromium.exe", "google-chrome", "msedge", "msedge.exe"}


def profile_has_chrome_process(profile_dir: Path) -> bool:
    """True when a Chrome/Chromium process is using this user-data-dir."""
    needle = str(Path(profile_dir).resolve()).lower()
    try:
        import psutil
    except ImportError:
        logger.warning("profile_lock_psutil_missing")
        return True
    for proc in psutil.process_iter(["name", "cmdline"]):
        try:
            name = (proc.info.get("name") or "").lower()
            if name not in _CHROME_NAMES and "chrome" not in name and "chromium" not in name:
                continue
            cmd = " ".join(proc.info.get("cmdline") or []).lower()
            if needle in cmd.replace("\\", "/") and "user-data-dir" in cmd:
                return True
        except (psutil.Error, TypeError, ValueError):
            continue
    return False


def clear_stale_profile_locks(
    profile_dir: Path,
    *,
    process_check: Callable[[Path], bool] | None = None,
) -> list[str]:
    """Delete Chromium singleton files if no process owns the profile."""
    root = Path(profile_dir)
    present = [name for name in LOCK_NAMES if (root / name).exists()]
    if not present:
        return []
    owned = (process_check or profile_has_chrome_process)(root)
    if owned:
        logger.info("profile_lock_in_use", profile=str(root))
        return []
    removed: list[str] = []
    for name in LOCK_NAMES:
        path = root / name
        if not path.exists() and not path.is_symlink():
            continue
        try:
            path.unlink()
            removed.append(name)
        except OSError as err:
            logger.warning("profile_lock_delete_failed", path=str(path), error=str(err))
    if removed:
        logger.warning("stale_profile_lock_removed", profile=str(root), files=removed)
    return removed
