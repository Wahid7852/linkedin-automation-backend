"""LinkedIn source: URL -> normalized profile dict (via the browser)."""
from __future__ import annotations

from .. import fetcher, normalize


def fetch(url: str, include_raw: bool = False, headless: bool = False) -> dict:
    """Fetch and normalize a LinkedIn profile from its URL."""
    public_id = fetcher.extract_public_id(url)
    raw = fetcher.fetch_raw(public_id, headless=headless)
    return normalize.normalize(raw, url=url, include_raw=include_raw)
