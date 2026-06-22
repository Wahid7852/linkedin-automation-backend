"""Read an existing LinkedIn session out of Firefox.

Firefox stores cookies in plaintext, so if you're already logged into LinkedIn
there we can lift the session to seed our Playwright profile -- skipping the
manual login. Cookie *flags* (httpOnly/secure/sameSite) must be preserved
faithfully or LinkedIn rejects the transplanted session, so we read them all.

Handles profile-sync-daemon setups where the live profile is symlinked into
tmpfs, and picks whichever Firefox profile actually holds a valid session.
"""
from __future__ import annotations

import glob
import os
import shutil
import sqlite3
import tempfile
import time

from . import auth

# Force a future expiry on session cookies so they persist into the on-disk
# Chromium profile (cookies without an expiry are dropped when the profile saves).
_FALLBACK_TTL_S = 365 * 24 * 3600

_PROFILE_BASES = (
    "~/.config/mozilla/firefox",
    "~/.mozilla/firefox",
    "~/snap/firefox/common/.mozilla/firefox",
    "~/.var/app/org.mozilla.firefox/.mozilla/firefox",
    "~/.librewolf",
    "~/.config/librewolf",
    "~/.zen",
    "~/.config/zen",
)

# Firefox sameSite int -> Playwright/Chromium string.
_SAMESITE = {0: "None", 1: "Lax", 2: "Strict"}


def _candidate_cookie_dbs() -> list[str]:
    """All cookies.sqlite across known Firefox-family profiles, newest first."""
    seen: dict[str, float] = {}
    for base in _PROFILE_BASES:
        base = os.path.expanduser(base)
        if not os.path.isdir(base):
            continue
        for db in glob.glob(os.path.join(base, "*", "cookies.sqlite")):
            real = os.path.realpath(db)  # follow psd symlink into tmpfs
            try:
                seen[real] = os.path.getmtime(real)
            except OSError:
                continue
    return sorted(seen, key=seen.get, reverse=True)


def _read_linkedin_cookies(db_path: str) -> list[dict]:
    """Copy the (possibly locked) DB and read LinkedIn cookies as Playwright dicts."""
    with tempfile.TemporaryDirectory() as tmp:
        dst = os.path.join(tmp, "cookies.sqlite")
        shutil.copy2(db_path, dst)
        for ext in ("-wal", "-shm"):
            if os.path.exists(db_path + ext):
                shutil.copy2(db_path + ext, dst + ext)

        con = sqlite3.connect(dst)
        try:
            rows = con.execute(
                "SELECT name, value, host, path, isSecure, isHttpOnly, sameSite, expiry "
                "FROM moz_cookies WHERE host LIKE '%linkedin.com%'"
            ).fetchall()
        finally:
            con.close()

    default_exp = int(time.time()) + _FALLBACK_TTL_S
    cookies = []
    for (name, value, host, path, is_secure, is_http_only, same_site, expiry) in rows:
        # Use the real expiry only if it's sane; otherwise force a future one so
        # the cookie persists (Playwright rejects odd/huge/0 expiry values).
        exp = expiry if isinstance(expiry, (int, float)) and 0 < expiry <= default_exp else default_exp
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": host,
                "path": path or "/",
                "secure": bool(is_secure),
                "httpOnly": bool(is_http_only),
                "sameSite": _SAMESITE.get(same_site, "None"),
                "expires": float(exp),
            }
        )
    return cookies


def find_linkedin_cookies() -> list[dict]:
    """Return faithful Playwright cookies for a logged-in Firefox LinkedIn session."""
    dbs = _candidate_cookie_dbs()
    if not dbs:
        raise auth.AuthError(
            "No Firefox cookies.sqlite found. Use `login` instead."
        )
    for db in dbs:
        cookies = _read_linkedin_cookies(db)
        names = {c["name"] for c in cookies}
        if all(req in names for req in auth.REQUIRED_COOKIES):
            return cookies
    raise auth.AuthError(
        "Found Firefox profiles but none had a logged-in LinkedIn session "
        f"(need {list(auth.REQUIRED_COOKIES)}). Log into LinkedIn in Firefox first."
    )
