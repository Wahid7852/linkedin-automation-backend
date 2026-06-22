"""X / Twitter source -- stub.

Reserved so the dispatcher and the rest of the app already speak to a uniform
`fetch(url) -> normalized dict` interface. Implement X extraction here later
(separate auth/scraping path) without touching the CLI, server, or summarizer.
"""
from __future__ import annotations


def fetch(url: str, **kwargs) -> dict:
    raise NotImplementedError(
        "X/Twitter extraction is not implemented yet. Only LinkedIn is supported."
    )
