"""Source dispatch: pick the right extractor for a given profile URL.

Every source exposes the same `fetch(url) -> normalized dict` interface, so the
CLI / REST / (future) summarizer code never changes when a new source is added.
"""
from __future__ import annotations

from urllib.parse import urlparse

from . import linkedin, x


def resolve(url: str):
    """Return the source module that handles `url`."""
    host = (urlparse(url).hostname or "").lower()
    if host.endswith("linkedin.com") or "/in/" in url and not host:
        return linkedin
    if host.endswith("x.com") or host.endswith("twitter.com"):
        return x
    # Default to LinkedIn for bare public ids (e.g. "wahidkhan7852").
    if "." not in url:
        return linkedin
    raise ValueError(f"No source registered for URL: {url!r}")


def fetch(url: str, **kwargs) -> dict:
    """Resolve the source for `url` and fetch a normalized profile."""
    return resolve(url).fetch(url, **kwargs)
