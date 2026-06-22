"""FastAPI REST server -- HTTP parity with the gst-automation-backend repo.

    POST /profile  {"url": "..."}  -> normalized profile JSON
    GET  /health                   -> {"status": "ok", "session": bool}

Fetches drive a persistent browser, so requests are serialised by browser.py's
lock. Intended for low-volume, single-operator use.
"""
from __future__ import annotations

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel

from . import auth, sources

load_dotenv()

app = FastAPI(title="LinkedIn Profile Fetcher", version="0.2.0")


class ProfileRequest(BaseModel):
    url: str
    raw: bool = False
    headless: bool = True


class SessionRequest(BaseModel):
    li_at: str
    jsessionid: str


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "session": auth.has_session()}


@app.post("/session")
def set_session(req: SessionRequest) -> dict:
    auth.set_cookies(req.li_at, req.jsessionid)
    return {"status": "ok"}


@app.post("/profile")
def profile(req: ProfileRequest) -> dict:
    try:
        return sources.fetch(req.url, include_raw=req.raw, headless=req.headless)
    except auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc))
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
