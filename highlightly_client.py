"""
highlightly_client.py

Shared code for every script that talks to the Highlightly basketball API.
It knows how to fetch one UTC day of matches (all pages), track the daily
quota from the response headers, write the raw day file safely, and compare
a re-fetched day with the file it replaces.

It does not decide WHICH days to fetch - that is the job of the scripts
that import it:
    backfill.py      past days, newest first, skipping days already on disk
    fetch_daily.py   one given day (default yesterday) plus the day before

Raw file format (raw/matches/YYYY-MM-DD.json):
    match_date, timezone, fetched_at, total_count, returned_count,
    complete, pages, plan, matches

Change report format (raw/changes/YYYY-MM-DD_<fetched_at>.json), written
when a day that already has a file is fetched again:
    match_date, previous_fetched_at, fetched_at, summary, ignored_fields,
    fields_appeared, fields_disappeared, changed_games,
    new_match_ids, removed_match_ids
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
CHANGES_DIR = PROJECT_DIR / "raw" / "changes"

# Fields that change between fetches without meaning anything for our data.
# They are left out of the "changed" decision in change reports, but the
# report still says how many games had one of them differ.
#   state.clock: a finished game shows clock 10 at first, later None
#                (seen on 138 of 152 changed games on 2026-10-24).
IGNORED_FIELDS = ("state.clock",)

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


def load_day(match_date):
    """The raw file already on disk for one day, or None if there is none."""
    path = day_file(match_date)
    if not path.exists():
        return None
    with open(path, encoding="utf-8") as file:
        return json.load(file)


def write_json_atomically(path, data):
    """
    Write to a temporary file first, then rename it into place.
    A crash mid-write never leaves a half-written file under the real name,
    and an existing file is only replaced once the new one is fully written.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_suffix(".json.tmp")
    with open(temp_path, "w", encoding="utf-8") as file:
        json.dump(data, file, indent=2, ensure_ascii=False)
    os.replace(temp_path, path)


def save_day(payload):
    """Write (or replace) the raw file for one day."""
    write_json_atomically(RAW_DIR / f"{payload['match_date']}.json", payload)


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


# ---------------------------------------------------------------------------
# Change detection (re-fetched day vs the file it replaces)
# ---------------------------------------------------------------------------
def flatten(value, prefix=""):
    """
    Turn a nested record into {"path.to.field": value}, so two records can be
    compared field by field, e.g. {"state": {"score": {"current": "80 - 75"}}}
    becomes {"state.score.current": "80 - 75"}. Lists are kept whole as one
    value.
    """
    if isinstance(value, dict):
        flat = {}
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else key
            flat.update(flatten(child, path))
        return flat
    return {prefix: value}


def index_matches(matches):
    """
    {match_id: flattened record} for one day's matches.
    Records without an id cannot be matched up, so they are counted instead.
    If an id appears twice, the last record wins and it is counted.
    """
    indexed = {}
    missing_id = 0
    duplicates = 0
    for record in matches:
        match_id = record.get("id") if isinstance(record, dict) else None
        if match_id is None:
            missing_id += 1
            continue
        if match_id in indexed:
            duplicates += 1
        indexed[match_id] = flatten(record)
    return indexed, missing_id, duplicates


def compare_days(previous_payload, new_payload):
    """
    Compare the previous file of a day with a new fetch of the same day,
    game by game by match id. Returns the change report (a dict).

    Field names are compared across the whole day: a field path that exists
    in the new fetch but in no game of the previous file is "appeared", and
    the reverse is "disappeared". This flags changes in the API's structure.

    Fields in IGNORED_FIELDS are not counted as changes: a game whose only
    differences are ignored fields is "identical", and a game with real
    changes lists only the real ones. How many games had an ignored field
    differ is reported in the summary.
    """
    old, old_missing, old_duplicates = index_matches(previous_payload.get("matches", []))
    new, new_missing, new_duplicates = index_matches(new_payload.get("matches", []))

    old_fields = set().union(*old.values()) if old else set()
    new_fields = set().union(*new.values()) if new else set()

    changed_games = []
    identical = 0
    games_with_ignored_changes = 0
    for match_id in sorted(old.keys() & new.keys()):
        before, after = old[match_id], new[match_id]
        differing = [
            path
            for path in sorted(before.keys() | after.keys())
            if before.get(path) != after.get(path) or (path in before) != (path in after)
        ]
        if any(path in IGNORED_FIELDS for path in differing):
            games_with_ignored_changes += 1
        changes = {
            path: {"old": before.get(path), "new": after.get(path)}
            for path in differing
            if path not in IGNORED_FIELDS
        }
        if changes:
            changed_games.append({
                "match_id": match_id,
                "home_team": after.get("homeTeam.name"),
                "away_team": after.get("awayTeam.name"),
                "changes": changes,
            })
        else:
            identical += 1

    new_ids = sorted(new.keys() - old.keys())
    removed_ids = sorted(old.keys() - new.keys())

    return {
        "match_date": new_payload["match_date"],
        "previous_fetched_at": previous_payload.get("fetched_at"),
        "fetched_at": new_payload["fetched_at"],
        "summary": {
            "games_before": len(old),
            "games_now": len(new),
            "identical": identical,
            "changed": len(changed_games),
            "new": len(new_ids),
            "removed": len(removed_ids),
            "games_with_ignored_changes": games_with_ignored_changes,
            "records_without_id": old_missing + new_missing,
            "duplicate_ids": old_duplicates + new_duplicates,
        },
        "ignored_fields": list(IGNORED_FIELDS),
        "fields_appeared": sorted(new_fields - old_fields),
        "fields_disappeared": sorted(old_fields - new_fields),
        "changed_games": changed_games,
        "new_match_ids": new_ids,
        "removed_match_ids": removed_ids,
    }


def save_change_report(report):
    """
    Write the report to raw/changes/YYYY-MM-DD_<fetched_at>.json.
    Every re-fetch gets its own file, so the history of changes is kept.
    The time uses no colons because Windows does not allow them in file names.
    """
    stamp = datetime.fromisoformat(report["fetched_at"]).strftime("%Y%m%dT%H%M%SZ")
    path = CHANGES_DIR / f"{report['match_date']}_{stamp}.json"
    write_json_atomically(path, report)
    return path


def log_change_report(script_log, report, path):
    """The summary line and warnings for one change report."""
    match_date = report["match_date"]
    summary = report["summary"]
    script_log.info(
        "%s: compared with the previous fetch (%s): %d games before, %d now | "
        "identical=%d changed=%d new=%d removed=%d | "
        "ignored-field differences (%s) in %d games | report %s",
        match_date, report["previous_fetched_at"], summary["games_before"], summary["games_now"],
        summary["identical"], summary["changed"], summary["new"], summary["removed"],
        ", ".join(report["ignored_fields"]), summary["games_with_ignored_changes"],
        path.relative_to(PROJECT_DIR).as_posix(),
    )
    if report["fields_appeared"]:
        script_log.warning(
            "%s: fields that were not in the previous fetch: %s",
            match_date, ", ".join(report["fields_appeared"]),
        )
    if report["fields_disappeared"]:
        script_log.warning(
            "%s: fields that are no longer in the API data: %s",
            match_date, ", ".join(report["fields_disappeared"]),
        )
    if summary["removed"]:
        script_log.warning(
            "%s: %d games in the previous file are missing from this fetch: %s",
            match_date, summary["removed"], ", ".join(str(i) for i in report["removed_match_ids"]),
        )
    if summary["records_without_id"] or summary["duplicate_ids"]:
        script_log.warning(
            "%s: %d records without an id and %d duplicate ids were not compared",
            match_date, summary["records_without_id"], summary["duplicate_ids"],
        )