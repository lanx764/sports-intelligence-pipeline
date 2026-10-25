"""
backfill.py

Fetches past days of matches from the Highlightly API into raw/matches/,
one file per day, going backwards from yesterday (UTC) to BACKFILL_STOP_DATE.

The files on disk are the bookmark: a day that already has a file is
skipped, so each run continues where the last one stopped and also fills
any gap in the middle. A run stops when the API quota is down to
QUOTA_RESERVE, which is left for fetch_daily.py and the backend.

The API calls and file writing live in highlightly_client.py, shared with
fetch_daily.py.

Settings (.env):
    HIGHLIGHTLY_API_KEY   API key
    BACKFILL_STOP_DATE    oldest day to fetch, YYYY-MM-DD
    QUOTA_RESERVE         requests to leave unused each day

Usage (run from the project folder, with the venv active):
    python backfill.py

Then load the new files with:
    python load_games.py
"""

import logging
import os
import sys
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from highlightly_client import (
    PROJECT_DIR,
    RAW_DIR,
    QuotaExhausted,
    day_file,
    fetch_day,
    get_api_key,
    log_day_result,
    make_session,
    new_quota,
    save_day,
)

REQUIRED_ENV = ("BACKFILL_STOP_DATE", "QUOTA_RESERVE")

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("backfill")


# ---------------------------------------------------------------------------
# Settings from .env
# ---------------------------------------------------------------------------
def read_settings():
    api_key = get_api_key()

    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        log.error("missing in .env: %s", ", ".join(missing))
        sys.exit(1)

    try:
        stop_date = date.fromisoformat(os.getenv("BACKFILL_STOP_DATE"))
    except ValueError:
        log.error("BACKFILL_STOP_DATE must be YYYY-MM-DD, got %r", os.getenv("BACKFILL_STOP_DATE"))
        sys.exit(1)

    try:
        reserve = int(os.getenv("QUOTA_RESERVE"))
        if reserve < 0:
            raise ValueError
    except ValueError:
        log.error("QUOTA_RESERVE must be a whole number 0 or above, got %r", os.getenv("QUOTA_RESERVE"))
        sys.exit(1)

    return api_key, stop_date, reserve


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def main():
    load_dotenv(PROJECT_DIR / ".env")
    api_key, stop_date, reserve = read_settings()
    RAW_DIR.mkdir(parents=True, exist_ok=True)

    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)
    if stop_date > yesterday:
        log.error("BACKFILL_STOP_DATE %s is after yesterday (%s)", stop_date, yesterday)
        return 1

    all_dates = [yesterday - timedelta(days=n) for n in range((yesterday - stop_date).days + 1)]
    to_fetch = [d for d in all_dates if not day_file(d).exists()]

    log.info(
        "range %s to %s: %d days, %d already on disk, %d to fetch (newest first, reserve %d)",
        stop_date, yesterday, len(all_dates), len(all_dates) - len(to_fetch), len(to_fetch), reserve,
    )
    if not to_fetch:
        log.info("nothing to fetch - backfill complete down to %s", stop_date)
        return 0

    session = make_session(api_key)
    quota = new_quota()
    fetched = 0
    stopped_reason = None
    failed = False

    for match_date in to_fetch:
        try:
            payload = fetch_day(session, match_date, quota, reserve)
        except QuotaExhausted as error:
            stopped_reason = str(error)
            break
        except requests.RequestException:
            log.exception("%s: request failed - stopping, nothing saved for this day", match_date)
            failed = True
            break

        save_day(payload)
        fetched += 1
        log_day_result(log, match_date, payload, quota)

    on_disk = sorted(RAW_DIR.glob("*.json"))
    oldest_on_disk = on_disk[0].stem if on_disk else "none"

    log.info(
        "done: %d days fetched, %d still to fetch, %d requests used, quota left %s, "
        "oldest day on disk %s, stopped early: %s",
        fetched, len(to_fetch) - fetched, quota["requests_used"], quota["remaining"],
        oldest_on_disk, stopped_reason or "no",
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())