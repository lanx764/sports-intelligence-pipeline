"""
fetch_daily.py

The daily extract: fetches one UTC day of matches (default: yesterday)
plus the day before it from the Highlightly API into raw/matches/.

Why the day before as well: a game that finished late, or had its score
corrected by the API, is picked up on the next run.

Unlike backfill.py, an existing day file is replaced, so re-running this
for the same date is safe (the newest complete fetch wins). Missed days are
not caught up here: Airflow runs this once per date, including dates it
missed; older gaps are filled by backfill.py.

Rules:
    - Only finished days: the date must be yesterday (UTC) or earlier.
    - QUOTA_RESERVE is ignored (that reserve exists for this job); the run
      stops only when the quota is used up.
    - An incomplete fetch (fewer matches returned than the API's total) is
      not saved, so it never replaces a good file.
    - Any failure exits with code 1, so Airflow marks the task failed.

Settings (.env):
    HIGHLIGHTLY_API_KEY   API key

Usage (run from the project folder, with the venv active):
    python fetch_daily.py               # yesterday (UTC) and the day before
    python fetch_daily.py 2026-10-23    # 2026-10-23 and 2026-10-22

Then load the files with:
    python load_games.py
"""

import logging
import sys
from datetime import date, datetime, timedelta, timezone

import requests
from dotenv import load_dotenv

from highlightly_client import (
    PROJECT_DIR,
    QuotaExhausted,
    fetch_day,
    get_api_key,
    log_day_result,
    make_session,
    new_quota,
    save_day,
)

DAILY_RESERVE = 0          # use the whole remaining quota if needed
DAYS_TO_FETCH = 2          # the target day and the day before it

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("fetch_daily")


def target_date(args):
    """The date to fetch: the argument if given, otherwise yesterday (UTC)."""
    yesterday = datetime.now(timezone.utc).date() - timedelta(days=1)

    if len(args) > 1:
        log.error("usage: python fetch_daily.py [YYYY-MM-DD]")
        sys.exit(1)
    if not args:
        return yesterday

    try:
        chosen = date.fromisoformat(args[0])
    except ValueError:
        log.error("date must be YYYY-MM-DD, got %r", args[0])
        sys.exit(1)

    if chosen > yesterday:
        log.error("%s is not finished yet in UTC - the latest day allowed is %s", chosen, yesterday)
        sys.exit(1)
    return chosen


def main():
    load_dotenv(PROJECT_DIR / ".env")
    target = target_date(sys.argv[1:])
    api_key = get_api_key()

    dates = [target - timedelta(days=n) for n in range(DAYS_TO_FETCH)]
    log.info("fetching %s", ", ".join(d.isoformat() for d in dates))

    session = make_session(api_key)
    quota = new_quota()
    saved = 0
    failed = False

    for match_date in dates:
        try:
            payload = fetch_day(session, match_date, quota, DAILY_RESERVE)
        except QuotaExhausted as error:
            log.error("%s: stopped - %s; nothing saved for this day", match_date, error)
            failed = True
            break
        except requests.RequestException:
            log.exception("%s: request failed - stopping, nothing saved for this day", match_date)
            failed = True
            break

        log_day_result(log, match_date, payload, quota)
        if not payload["complete"]:
            log.error("%s: incomplete fetch not saved - the existing file (if any) is kept", match_date)
            failed = True
            continue

        save_day(payload)
        saved += 1

    log.info(
        "done: %d of %d days saved, %d requests used, quota left %s",
        saved, len(dates), quota["requests_used"], quota["remaining"],
    )
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())