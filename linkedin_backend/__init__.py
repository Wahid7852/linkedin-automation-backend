"""LinkedIn profile fetcher backend.

Link in -> normalized profile JSON out. Built on the unofficial linkedin-api
(Voyager) client, with Playwright handling the one-time interactive login so the
session cookie can be captured once and reused (mirrors the gst-automation-backend
cookie-reuse pattern).
"""

__version__ = "0.1.0"
