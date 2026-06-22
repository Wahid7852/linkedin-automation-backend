"""Persistent Playwright browser session — the data engine.

LinkedIn's PerimeterX blocks non-browser fingerprints, so all fetching happens
inside a real Chromium with a persistent on-disk profile. We don't call internal
APIs with hand-built (rotating) query IDs; instead we navigate to the profile
page like a human and capture the Voyager / GraphQL XHR responses the page itself
fires. That keeps us future-proof against LinkedIn's query-id churn.

Concurrency: a persistent profile dir can only be driven by one Chromium at a
time, so a process-wide lock serialises fetches (fine for the low volume this is
meant for).
"""
from __future__ import annotations

import random
import threading
import time

from . import auth

_LAUNCH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--disable-dev-shm-usage",  # use /tmp instead of /dev/shm (critical in containers)
    "--no-sandbox",
    "--disable-gpu",
    "--disable-extensions",
    "--disable-background-networking",
    "--disable-sync",
    "--no-first-run",
    "--mute-audio",
]
_VIEWPORT = {"width": 1280, "height": 900}
_PROFILE_URL = "https://www.linkedin.com/in/{public_id}/"
_FEED_URL = "https://www.linkedin.com/feed/"

# Marks a not-logged-in landing page (URL or guest-wall page title).
_LOGGED_OUT_MARKERS = ("/login", "/uas/login", "/authwall", "/checkpoint", "/signup")
_GUEST_TITLE_MARKERS = ("sign up", "sign in", "login", "join linkedin")

_lock = threading.Lock()


def _is_logged_out(page) -> bool:
    if any(m in page.url for m in _LOGGED_OUT_MARKERS):
        return True
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001
        return False
    return any(m in title for m in _GUEST_TITLE_MARKERS)


def login(profile_dir: str = auth.DEFAULT_PROFILE_DIR, timeout_s: int = 300) -> None:
    """Open a visible browser and wait for the user to log in.

    The session is saved into the persistent profile automatically, so later
    fetches reuse it without a fresh login.
    """
    from playwright.sync_api import sync_playwright

    print("Opening a browser. Log in to LinkedIn (including any 2FA)...")
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile_dir, headless=False, args=_LAUNCH_ARGS, viewport=_VIEWPORT
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(_FEED_URL)

        deadline = time.time() + timeout_s
        ok = False
        while time.time() < deadline:
            names = {c["name"] for c in ctx.cookies("https://www.linkedin.com")}
            if all(req in names for req in auth.REQUIRED_COOKIES) and not _is_logged_out(page):
                ok = True
                break
            time.sleep(1.0)

        time.sleep(2.0)  # let the session settle / persist
        ctx.close()

    if not ok:
        raise auth.AuthError(f"Timed out after {timeout_s}s waiting for login.")
    print(f"Logged in. Session saved to {profile_dir}")


def seed_from_firefox(profile_dir: str = auth.DEFAULT_PROFILE_DIR, headless: bool = False) -> None:
    """Seed the persistent profile from an existing Firefox session (no login)."""
    from playwright.sync_api import sync_playwright

    from . import firefox

    cookies = firefox.find_linkedin_cookies()
    with sync_playwright() as p:
        ctx = p.chromium.launch_persistent_context(
            profile_dir, headless=headless, args=_LAUNCH_ARGS, viewport=_VIEWPORT
        )
        ctx.add_cookies(cookies)
        page = ctx.pages[0] if ctx.pages else ctx.new_page()

        # PerimeterX can bounce the first hit; warm up on the homepage, then
        # retry the feed a few times so its JS can mint browser-valid cookies.
        logged_in = False
        for attempt in range(4):
            try:
                page.goto("https://www.linkedin.com", wait_until="domcontentloaded", timeout=30000)
                time.sleep(2.0)
                page.goto(_FEED_URL, wait_until="domcontentloaded", timeout=30000)
            except Exception:  # noqa: BLE001 - transient nav aborts, retry
                time.sleep(3.0)
                continue
            time.sleep(5.0)
            if not _is_logged_out(page):
                logged_in = True
                break
            time.sleep(3.0)
        ctx.close()

    if not logged_in:
        raise auth.AuthError(
            "Seeded Firefox cookies but LinkedIn didn't accept the session "
            "(possibly a temporary bot-check). Wait a few minutes and retry, or "
            "use `login` to sign in directly."
        )
    print(f"Seeded {len(cookies)} cookies from Firefox -> {profile_dir}")


def fetch_profile_xhr(
    public_id: str,
    profile_dir: str = auth.DEFAULT_PROFILE_DIR,
    headless: bool = True,
    scroll_passes: int = 18,
) -> dict:
    """Navigate to a profile and capture the Voyager XHR responses + DOM fallback.

    Returns {"captured": [{"url","json"}...], "dom": {...}}.
    """
    from playwright.sync_api import sync_playwright

    with _lock:
        captured: list[dict] = []

        def on_response(resp):
            url = resp.url
            if "/voyager/api/" not in url:
                return
            ctype = resp.headers.get("content-type", "")
            if "json" not in ctype:
                return
            try:
                captured.append({"url": url, "json": resp.json()})
            except Exception:  # noqa: BLE001 - redirects / non-json bodies
                pass

        with sync_playwright() as p:
            ctx = p.chromium.launch_persistent_context(
                profile_dir, headless=headless, args=_LAUNCH_ARGS, viewport=_VIEWPORT
            )
            ext = auth.get_cookies()
            if ext:
                ctx.add_cookies([
                    {"name": "li_at", "value": ext["li_at"], "domain": ".linkedin.com", "path": "/"},
                    {"name": "JSESSIONID", "value": ext["JSESSIONID"], "domain": ".linkedin.com", "path": "/"},
                ])
            page = ctx.pages[0] if ctx.pages else ctx.new_page()

            # Warm up on the feed first: a cold launch navigating straight to a
            # profile doesn't establish the session and serves the guest wall.
            page.goto(_FEED_URL, wait_until="domcontentloaded")
            time.sleep(3.0)
            if _is_logged_out(page):
                ctx.close()
                raise auth.AuthError(
                    "Not logged in (hit the auth wall). Run "
                    "`python -m linkedin_backend.cli login` or `import-firefox`."
                )

            page.on("response", on_response)
            page.goto(_PROFILE_URL.format(public_id=public_id), wait_until="domcontentloaded")
            time.sleep(3.0)

            # Sections lazy-load on scroll-into-view; step slowly so the
            # IntersectionObservers fire and content renders.
            _scroll_through(page, steps=scroll_passes)

            dom = _extract_sections(page)
            ctx.close()

    return {"captured": captured, "dom": dom}


def _scroll_through(page, steps: int = 18) -> None:
    """Scroll top-to-bottom slowly to trigger lazy section rendering, then back up."""
    try:
        height = page.evaluate("document.body.scrollHeight") or 9000
    except Exception:  # noqa: BLE001
        height = 9000
    step = max(400, int(height / max(steps, 1)))
    for y in range(0, height + step, step):
        page.evaluate(f"window.scrollTo(0, {y})")
        time.sleep(random.uniform(0.6, 1.0))
    page.evaluate("window.scrollTo(0, 0)")
    time.sleep(1.0)


# LinkedIn's profile DOM uses obfuscated, rotating class names, so we key off the
# stable <h2> section headers and extract each section's rendered text. The text
# is parsed downstream in normalize.py.
_EXTRACT_JS = r"""
() => {
  const norm = (s) => (s || "").replace(/[ \t]+/g, " ").trim();
  const sections = [...document.querySelectorAll('section')];
  const findSec = (name) => sections.find((s) => {
    const h = s.querySelector('h2');
    return h && norm(h.innerText).toLowerCase().startsWith(name.toLowerCase());
  });
  const secText = (name) => { const s = findSec(name); return s ? s.innerText : null; };

  const main = document.querySelector('main') || document.body;
  const h1 = main.querySelector('h1');
  // The top card isn't a <section>; take the start of the main column's text
  // (name / headline / location / connections all live here).
  const intro = (main.innerText || "").split("\n").slice(0, 25).join("\n");

  return {
    name: h1 ? norm(h1.innerText) : null,
    intro: intro,
    sections: {
      about: secText('About'),
      experience: secText('Experience'),
      education: secText('Education'),
      skills: secText('Skills'),
      licenses: secText('Licenses'),
    },
  };
}
"""


def _extract_sections(page) -> dict:
    try:
        return page.evaluate(_EXTRACT_JS)
    except Exception:  # noqa: BLE001
        return {}
