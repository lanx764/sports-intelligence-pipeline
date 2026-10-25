"""
highlightly_client.py

Shared code for every script that talks to the Highlightly basketball API.
It knows how to fetch one UTC day of matches (all pages), track the daily
quota from the response headers, and write the raw day file safely.

It does not decide WHICH days to fetch - that is the job of the scripts
that import it:
    backfill.py      past days, newest first, skipping days already on disk
    fetch_daily.py   one given day (default yesterday) plus the day before

Raw file format (raw/matches/YYYY-MM-DD.json):
    match_date, timezone, fetched_at, total_count, returned_count,
    complete, pages, plan, matches
"""

import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
RAW_DIR = PROJECT_DIR / "raw" / "matches"

BASE_URL = "https://basketball.highlightly.net"
TIMEZONE = "Etc/UTC"
PAGE_SIZE = 100
REQUEST_PAUSE_SECONDS = 0.5
REQUEST_TIMEOUT_SECONDS = 30
FULL_ACCESS_PREFIX = "All data available"
API_KEY_ENV = "HIGHLIGHTLY_API_KEY"

log = logging.getLogger("highlightly_client")


class QuotaExhausted(Exception):
    """The quota is down to the reserve, or the API answered 429."""


# ---------------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------------
def get_api_key():
    """Read the API key from the environment (.env must be loaded first)."""
    api_key = os.getenv(API_KEY_ENV)
    if not api_key:
        log.error("missing in .env: %s", API_KEY_ENV)
        sys.exit(1)
    return api_key


def make_session(api_key):
    """One HTTP session for a whole run, with the API key header set once."""
    session = requests.Session()
    session.headers.update({"x-rapidapi-key": api_key})
    return session


def new_quota():
    """Quota tracker shared across all days in one run."""
    return {"requests_used": 0, "remaining": None}


# ---------------------------------------------------------------------------
# Extract
# ---------------------------------------------------------------------------
def fetch_page(session, match_date, offset):
    """One API call: one page of up to PAGE_SIZE matches for one day."""
    response = session.get(
        f"{BASE_URL}/matches",
        params={
            "date": match_date.isoformat(),
            "timezone": TIMEZONE,
            "limit": PAGE_SIZE,
            "offset": offset,
        },
        timeout=REQUEST_TIMEOUT_SECONDS,
    )

    if response.status_code == 429:
        raise QuotaExhausted("API answered HTTP 429 (quota or rate limit hit)")

    response.raise_for_status()

    remaining_header = response.headers.get("x-ratelimit-requests-remaining")
    remaining = int(remaining_header) if remaining_header and remaining_header.isdigit() else None

    return response.json(), remaining


def fetch_day(session, match_date, quota, reserve):
    """
    All pages for one day, wrapped with metadata.

    Before every request after the first, stops if the quota is down to
    `reserve`. The quota is only known from a response header, so the first
    request of a run cannot be checked (known limitation: a run that starts
    at or below the reserve can use 1 request too many).
    """
    matches = []
    offset = 0
    total_count = None
    pages = 0
    plan = None

    while total_count is None or offset < total_count:
        if quota["remaining"] is not None and quota["remaining"] <= reserve:
            raise QuotaExhausted(
                f"only {quota['remaining']} requests left (reserve is {reserve})"
            )

        body, remaining = fetch_page(session, match_date, offset)
        quota["requests_used"] += 1
        quota["remaining"] = remaining
        pages += 1

        page_matches = body.get("data", [])
        matches.extend(page_matches)
        total_count = body["pagination"]["totalCount"]
        plan = body.get("plan")

        if not page_matches:
            break

        offset += PAGE_SIZE
        time.sleep(REQUEST_PAUSE_SECONDS)

    return {
        "match_date": match_date.isoformat(),
        "timezone": TIMEZONE,
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "total_count": total_count,
        "returned_count": len(matches),
        "complete": len(matches) == total_count,
        "pages": pages,
        "plan": plan,
        "matches": matches,
    }


# ---------------------------------------------------------------------------
# Raw files
# ---------------------------------------------------------------------------
def day_file(match_date):
    """Path of the raw file for one day."""
    return RAW_DIR / f"{match_date.isoformat()}.json"


def save_day(payload):
    """
    Write the day to a temporary file first, then rename it into place.
    A crash mid-write never leaves a half-written file under the real name,
    and an existing file is only replaced once the new one is fully written.
    """
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{payload['match_date']}.json"
    temp_path = path.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(payload, file, indent=2, ensure_ascii=False)
    os.replace(temp_path, path)


def log_day_result(script_log, match_date, payload, quota):
    """The per-day log line and warnings, the same for every script."""
    script_log.info(
        "%s: total=%s returned=%s pages=%s | quota left=%s",
        match_date, payload["total_count"], payload["returned_count"],
        payload["pages"], quota["remaining"],
    )
    if not payload["complete"]:
        script_log.warning("%s: returned_count != total_count - this day is incomplete", match_date)

    plan_message = (payload["plan"] or {}).get("message") or ""
    if plan_message and not plan_message.startswith(FULL_ACCESS_PREFIX):
        script_log.warning("%s: plan note: %s", match_date, plan_message)