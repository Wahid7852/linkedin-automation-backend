"""Flatten captured data into the clean, summary-ready schema.

Two data sources are combined:
  - XHR: the `voyagerIdentityDashProfiles` response gives a clean Profile entity
    (name, headline, profile picture) — matched to the target by publicIdentifier.
  - DOM text: LinkedIn's profile sections use obfuscated, rotating class names, so
    we extract each section's rendered *text* (keyed off stable <h2> headers) and
    parse it. Entries are date-anchored: every experience/education row has a
    "Mon YYYY" line, with the title/org on the two lines just above it.

Output shape (generalized satyanadella example):
    url, username, name, headline, location, summary, current_company,
    current_title, education[], skills[], experience[], profile_pic_url,
    sections_text, fetched_at
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone

_MONTH = r"(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)"
_YEAR = r"(?:19|20)\d{2}"
_EMPLOYMENT_TYPES = ("Full-time", "Part-time", "Internship", "Freelance",
                     "Self-employed", "Contract", "Apprenticeship", "Seasonal")
_NOISE_RE = re.compile(
    r"(…\s*more|…see more|see more|^more$|Show all|Show more|Endorsed by|\.png|\.jpg|skills?$)",
    re.IGNORECASE,
)
_NOT_LOCATION = ("connection", "follower", "contact info", "·", "mutual")


# --------------------------------------------------------------------------- #
# XHR profile entity
# --------------------------------------------------------------------------- #
def _type(entity: dict) -> str:
    return entity.get("$type") or ""


def _profile_entity(captured: list[dict], public_id: str | None) -> dict:
    """Find the target's Profile entity (matched by publicIdentifier)."""
    candidates = []
    for cap in captured:
        body = cap.get("json")
        if not isinstance(body, dict):
            continue
        for e in body.get("included", []) or []:
            if isinstance(e, dict) and _type(e).endswith(".profile.Profile"):
                candidates.append(e)
    for e in candidates:
        if public_id and e.get("publicIdentifier") == public_id:
            return e
    # Fallback: the first profile entity that has a name.
    for e in candidates:
        if e.get("firstName") or e.get("lastName"):
            return e
    return {}


def _find_vector_image(obj, _depth: int = 0):
    """Recursively locate a Voyager VectorImage (rootUrl + artifacts) and build a URL."""
    if _depth > 6 or not isinstance(obj, (dict, list)):
        return None
    if isinstance(obj, dict):
        if obj.get("rootUrl") and obj.get("artifacts"):
            seg = obj["artifacts"][-1].get("fileIdentifyingUrlPathSegment")
            if seg:
                return obj["rootUrl"] + seg
        for v in obj.values():
            found = _find_vector_image(v, _depth + 1)
            if found:
                return found
    else:
        for v in obj:
            found = _find_vector_image(v, _depth + 1)
            if found:
                return found
    return None


# --------------------------------------------------------------------------- #
# DOM text parsing
# --------------------------------------------------------------------------- #
def _clean_lines(text: str | None, header: str | None = None) -> list[str]:
    if not text:
        return []
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.splitlines()]
    lines = [ln for ln in lines if ln]
    if header and lines and lines[0].lower().startswith(header.lower()):
        lines = lines[1:]
    # Drop consecutive duplicates (LinkedIn repeats text for accessibility).
    out: list[str] = []
    for ln in lines:
        if not out or out[-1] != ln:
            out.append(ln)
    return out


def _is_date_line(s: str) -> bool:
    if len(s) > 90:
        return False
    if re.search(rf"\b{_MONTH}\b.*\b{_YEAR}\b", s):
        return True
    if re.search(rf"\b{_YEAR}\b\s*[-–—]\s*(Present|\b{_YEAR}\b)", s):
        return True
    return False


def _looks_like_location(s: str) -> bool:
    return "," in s and len(s) < 70 and not _is_date_line(s)


def _date_anchored(lines: list[str]) -> list[dict]:
    """Yield {title, org, date_line, after} anchored on each date line."""
    entries = []
    for i, ln in enumerate(lines):
        if _is_date_line(ln) and i >= 2:
            entries.append(
                {
                    "title": lines[i - 2],
                    "org": lines[i - 1],
                    "date_line": ln,
                    "after": lines[i + 1] if i + 1 < len(lines) else None,
                }
            )
    return entries


def _split_duration(date_line: str) -> str:
    # "Jan 2025 - Present · 1 yr 6 mos" -> "Jan 2025 - Present"
    return date_line.split("·")[0].strip()


def _strip_employment(org: str) -> tuple[str, str | None]:
    parts = [p.strip() for p in org.split("·")]
    company = parts[0]
    emp = next((p for p in parts[1:] if p in _EMPLOYMENT_TYPES), None)
    return company, emp


def _parse_experience(text: str | None) -> list[dict]:
    out = []
    for e in _date_anchored(_clean_lines(text, "Experience")):
        company, _emp = _strip_employment(e["org"])
        loc = None
        if e["after"] and _looks_like_location(e["after"]):
            loc = e["after"].split("·")[0].strip()
        out.append(
            {
                "title": e["title"],
                "company": company,
                "duration": _split_duration(e["date_line"]),
                "location": loc,
            }
        )
    return out


def _parse_education(text: str | None) -> list[dict]:
    out = []
    for e in _date_anchored(_clean_lines(text, "Education")):
        out.append(
            {
                "school": e["title"],
                "degree": e["org"],
                "duration": _split_duration(e["date_line"]),
            }
        )
    return out


def _parse_skills(text: str | None) -> list[str]:
    out = []
    for ln in _clean_lines(text, "Skills"):
        if _NOISE_RE.search(ln) or _is_date_line(ln) or len(ln) > 60:
            continue
        out.append(ln)
    # Dedupe, keep order.
    seen, uniq = set(), []
    for s in out:
        if s not in seen:
            seen.add(s)
            uniq.append(s)
    return uniq


def _bullet_skills(text: str | None) -> list[str]:
    """Skills from the '•'-separated 'Top skills' footer LinkedIn shows in About."""
    for ln in _clean_lines(text, "About"):
        if " • " in ln and not ln.endswith((".", "!", "?")):
            return [s.strip() for s in ln.split("•") if s.strip()]
    return []


def _parse_about(text: str | None) -> str | None:
    lines = _clean_lines(text, "About")
    # Drop UI noise and the trailing "Top skills" bullet line.
    lines = [ln for ln in lines if not _NOISE_RE.search(ln) and not (" • " in ln and not ln.endswith((".", "!", "?")))]
    return "\n".join(lines).strip() or None


def _parse_location(intro: str | None, headline: str | None) -> str | None:
    lines = _clean_lines(intro)
    # The location is the first comma-bearing line near the top that isn't the
    # headline, a connection/follower count, or a "·"-joined headline fragment.
    for ln in lines[1:]:
        low = ln.lower()
        if headline and ln == headline:
            continue
        if any(tok in low for tok in _NOT_LOCATION):
            continue
        if _looks_like_location(ln):
            return ln
    return None


# --------------------------------------------------------------------------- #
# Assembly
# --------------------------------------------------------------------------- #
def normalize(raw: dict, url: str, include_raw: bool = False) -> dict:
    captured = raw.get("captured") or []
    dom = raw.get("dom") or {}
    sections = dom.get("sections") or {}
    public_id = raw.get("public_id")

    profile = _profile_entity(captured, public_id)
    name = (" ".join(p for p in [profile.get("firstName"), profile.get("lastName")] if p).strip()
            or dom.get("name"))
    headline = profile.get("headline")
    pic = _find_vector_image(profile.get("profilePicture")) if profile else None

    experience = _parse_experience(sections.get("experience"))
    current_company, current_title = None, None
    for exp in experience:
        if "present" in (exp.get("duration") or "").lower():
            current_company, current_title = exp["company"], exp["title"]
            break
    if current_company is None and experience:
        current_company, current_title = experience[0]["company"], experience[0]["title"]

    return {
        "url": url,
        "username": public_id,
        "name": name,
        "headline": headline,
        "location": _parse_location(dom.get("intro"), headline),
        "summary": _parse_about(sections.get("about")),
        "current_company": current_company,
        "current_title": current_title,
        "education": _parse_education(sections.get("education")),
        "skills": _parse_skills(sections.get("skills")) or _bullet_skills(sections.get("about")),
        "experience": experience,
        "profile_pic_url": pic,
        "sections_text": {k: v for k, v in sections.items() if v},
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "_meta": {"captured_responses": len(captured)},
        **({"raw": raw} if include_raw else {}),
    }


def download_image(url: str | None, dest_base: str) -> str | None:
    """Download a profile photo to dest_base + extension. Returns the path or None.

    LinkedIn's signed photo URLs expire, so saving a local copy gives a permanent
    image. Failures are swallowed so a missing photo never breaks a fetch.
    """
    import urllib.request

    if not url:
        return None
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            ext = ".png" if "png" in resp.headers.get("Content-Type", "").lower() else ".jpg"
            data = resp.read()
        path = dest_base + ext
        with open(path, "wb") as fh:
            fh.write(data)
        return path
    except Exception:  # noqa: BLE001 - photo is best-effort
        return None


def save_json(data: dict, out_path: str | None = None) -> str:
    """Write the normalized profile to disk; default filename is <username>.json."""
    if out_path is None:
        out_path = f"{data.get('username') or 'profile'}.json"
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
    return out_path
