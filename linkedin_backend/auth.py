"""Session state for the persistent-browser approach.

We no longer export cookies to an HTTP client (LinkedIn's PerimeterX blocks
non-browser fingerprints). Instead a single Playwright Chromium *persistent
profile* holds the logged-in session on disk; everything runs inside that
browser. This module just tracks where that profile lives and whether it looks
logged in.
"""
from __future__ import annotations

import glob
import os

# Where the persistent Chromium profile (cookies, storage) is kept.
DEFAULT_PROFILE_DIR = os.getenv("PROFILE_DIR", os.path.abspath(".pw-profile"))

# Cookies that must be present for a usable LinkedIn session.
REQUIRED_COOKIES = ("li_at", "JSESSIONID")

# In-memory cookie store (set via POST /session or env vars at startup).
_runtime_cookies: dict[str, str] = {}


class AuthError(RuntimeError):
    """Raised when there is no usable logged-in browser session."""


def set_cookies(li_at: str, jsessionid: str) -> None:
    _runtime_cookies["li_at"] = li_at
    _runtime_cookies["JSESSIONID"] = jsessionid


def get_cookies() -> dict[str, str] | None:
    """Return external cookies from memory or env vars, or None if not set."""
    li_at = _runtime_cookies.get("li_at") or os.getenv("LI_AT")
    jsessionid = _runtime_cookies.get("JSESSIONID") or os.getenv("LI_JSESSIONID")
    if li_at and jsessionid:
        return {"li_at": li_at, "JSESSIONID": jsessionid}
    return None


def has_session(profile_dir: str = DEFAULT_PROFILE_DIR) -> bool:
    """True if a session is available via external cookies or a saved profile."""
    return get_cookies() is not None or profile_exists(profile_dir)


def profile_exists(profile_dir: str = DEFAULT_PROFILE_DIR) -> bool:
    """True if a persistent browser profile has been created at all."""
    return os.path.isdir(profile_dir) and bool(
        glob.glob(os.path.join(profile_dir, "**", "Cookies"), recursive=True)
        or glob.glob(os.path.join(profile_dir, "Default", "Cookies"))
        or os.listdir(profile_dir)
    )
