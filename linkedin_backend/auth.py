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


class AuthError(RuntimeError):
    """Raised when there is no usable logged-in browser session."""


def profile_exists(profile_dir: str = DEFAULT_PROFILE_DIR) -> bool:
    """True if a persistent browser profile has been created at all."""
    return os.path.isdir(profile_dir) and bool(
        glob.glob(os.path.join(profile_dir, "**", "Cookies"), recursive=True)
        or glob.glob(os.path.join(profile_dir, "Default", "Cookies"))
        or os.listdir(profile_dir)
    )
