"""Command-line interface.

    python -m linkedin_backend.cli login            # sign in (persistent browser)
    python -m linkedin_backend.cli import-firefox   # reuse an existing Firefox session
    python -m linkedin_backend.cli fetch <url> [-o out.json] [--raw] [--headless]
"""
from __future__ import annotations

import argparse
import sys

from dotenv import load_dotenv

from . import auth, browser, sources

load_dotenv()


def _cmd_login(args: argparse.Namespace) -> int:
    try:
        browser.login(timeout_s=args.timeout)
    except auth.AuthError as exc:
        print(f"Login failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_import_firefox(args: argparse.Namespace) -> int:
    try:
        browser.seed_from_firefox()
    except auth.AuthError as exc:
        print(f"Import failed: {exc}", file=sys.stderr)
        return 1
    return 0


def _cmd_fetch(args: argparse.Namespace) -> int:
    from . import normalize

    try:
        profile = sources.fetch(args.url, include_raw=args.raw, headless=not args.headed)
    except auth.AuthError as exc:
        print(f"{exc}", file=sys.stderr)
        return 1
    except (ValueError, NotImplementedError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    out_path = args.output or f"{profile.get('username') or 'profile'}.json"

    # Download the photo to a local file (the LinkedIn URL expires) unless opted out.
    if not args.no_photo:
        import os

        pic_path = normalize.download_image(
            profile.get("profile_pic_url"), os.path.splitext(out_path)[0]
        )
        if pic_path:
            profile["profile_pic_file"] = pic_path

    normalize.save_json(profile, out_path)
    name = profile.get("name") or profile.get("username")
    counts = (
        f"{len(profile.get('experience', []))} exp, "
        f"{len(profile.get('education', []))} edu, "
        f"{len(profile.get('skills', []))} skills"
    )
    pic = f", photo -> {profile['profile_pic_file']}" if profile.get("profile_pic_file") else ""
    print(f"Saved profile for {name!r} -> {out_path} ({counts}{pic})")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="linkedin_backend.cli",
        description="Fetch a LinkedIn profile to normalized JSON via a persistent browser.",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_login = sub.add_parser("login", help="Sign in to LinkedIn in a persistent browser.")
    p_login.add_argument("--timeout", type=int, default=300, help="Seconds to wait for login.")
    p_login.set_defaults(func=_cmd_login)

    p_ff = sub.add_parser(
        "import-firefox",
        help="Seed the session from your existing Firefox LinkedIn login (opens a window once).",
    )
    p_ff.set_defaults(func=_cmd_import_firefox)

    p_fetch = sub.add_parser("fetch", help="Fetch a profile by URL.")
    p_fetch.add_argument("url", help="LinkedIn profile URL (or bare public id).")
    p_fetch.add_argument("-o", "--output", help="Output JSON path (default <username>.json).")
    p_fetch.add_argument("--raw", action="store_true", help="Embed the raw captured payload too.")
    p_fetch.add_argument(
        "--no-photo", action="store_true",
        help="Don't download the profile photo to a local file.",
    )
    p_fetch.add_argument(
        "--headed", action="store_true",
        help="Show the browser window (default is hidden/headless).",
    )
    p_fetch.set_defaults(func=_cmd_fetch)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
