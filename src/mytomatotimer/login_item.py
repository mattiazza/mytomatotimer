"""Launch at login via SMAppService (macOS 13+). The OS stores the choice, not our DB.

Only meaningful from the packaged .app: from a plain `python`, macOS would register
the interpreter instead, so callers check `available()` first.
"""

import sys

from ServiceManagement import SMAppService, SMAppServiceStatusEnabled


def available() -> bool:
    return bool(getattr(sys, "frozen", False))  # py2app sets sys.frozen in the bundle


def is_enabled() -> bool:
    return SMAppService.mainAppService().status() == SMAppServiceStatusEnabled


def set_enabled(enabled: bool) -> None:
    """Register or unregister the app. Raises RuntimeError if macOS refuses."""
    service = SMAppService.mainAppService()
    if enabled:
        ok, error = service.registerAndReturnError_(None)
    else:
        ok, error = service.unregisterAndReturnError_(None)
    if not ok:
        raise RuntimeError(str(error))
