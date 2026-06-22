"""Fetch orchestration: URL -> captured Voyager data (via the browser)."""
from __future__ import annotations

import re

from . import auth, browser

_PUBLIC_ID_RE = re.compile(r"/in/([^/?#]+)", re.IGNORECASE)


def extract_public_id(url: str) -> str:
    """Pull the vanity slug out of a LinkedIn profile URL.

    https://www.linkedin.com/in/wahidkhan7852/ -> 'wahidkhan7852'
    Also accepts a bare public id.
    """
    match = _PUBLIC_ID_RE.search(url)
    if match:
        return match.group(1).strip()
    bare = url.strip().strip("/")
    if bare and "/" not in bare and " " not in bare:
        return bare
    raise ValueError(f"Could not extract a LinkedIn public id from: {url!r}")


def fetch_raw(public_id: str, headless: bool = False) -> dict:
    """Drive the browser to the profile page and capture its Voyager responses."""
    result = browser.fetch_profile_xhr(public_id, headless=headless)
    result["public_id"] = public_id
    if not result.get("captured") and not (result.get("dom") or {}).get("name"):
        raise auth.AuthError(
            "Loaded the profile but captured no data. The session may be stale "
            "or challenged — try `login` again."
        )
    return result
