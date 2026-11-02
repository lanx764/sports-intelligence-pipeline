"""
run_checks.py

Checks the data in basketball.fact_games, basketball.quarantine_games and
basketball.abnormal_results after a load. Run it after load_games.py.

Checks:
  1. Shared team ids: an API team id that appears under two or more real
     countries and is not yet in basketball.club_id_overrides. Games from
     leagues listed in basketball.international_leagues are ignored here,
     because those leagues take clubs from several countries and their
     country label is only where the competition is hosted.
     Needs action.
  2. Consistency: halves and quarters must add up to total_points.
     Needs action.
  3. Club ids: one club_id must belong to exactly one club name across
     basketball.club_id_overrides and basketball.club_corrections.
     Needs action.
  4. Abnormal overlap: a game must never be in both basketball.fact_games
     and basketball.abnormal_results.
     Needs action.
  5. Open quarantine rows: reported as a warning, never fails the run.

Exit code: 0 if checks 1 to 4 pass, 1 if any of them finds a problem.

Usage (run from the project folder, with the venv active):
    python run_checks.py
"""

import logging
import sys

import psycopg
from dotenv import load_dotenv

from load_games import PROJECT_DIR, get_db_settings

# The API's "country" for a game is the country or region of the competition.
# These labels are regions, not real countries, so they are ignored when
# looking for shared team ids. If a new region label shows up as a false
# alarm in check 1, add it here.
REGIONAL_LABELS = [
    "Europe", "World", "Asia", "Africa",
    "North America", "South America", "Oceania",
]

SHARED_ID_SQL = """
WITH sides AS (
    SELECT home_team_id AS api_team_id, home_team AS team, country, league_id
    FROM basketball.fact_games
    UNION ALL
    SELECT away_team_id, away_team, country, league_id
    FROM basketball.fact_games
)
SELECT
    api_team_id,
    MIN(team)                          AS team,
    STRING_AGG(DISTINCT country, ', ') AS countries
FROM sides
WHERE country IS NOT NULL
  AND country <> ALL(%s)
  AND league_id NOT IN (SELECT league_id FROM basketball.international_leagues)
  AND api_team_id NOT IN (SELECT api_team_id FROM basketball.club_id_overrides)
GROUP BY api_team_id
HAVING COUNT(DISTINCT country) > 1
ORDER BY api_team_id
"""

CONSISTENCY_SQL = """
SELECT match_id, match_date, home_team, away_team,
       total_q1, total_q2, total_q3, total_q4, total_h1, total_h2, total_points
FROM basketball.fact_games
WHERE (total_h1 IS NOT NULL AND total_h2 IS NOT NULL
       AND total_h1 + total_h2 <> total_points)
   OR (total_q1 IS NOT NULL AND total_q2 IS NOT NULL
       AND total_q3 IS NOT NULL AND total_q4 IS NOT NULL
       AND total_q1 + total_q2 + total_q3 + total_q4 <> total_points)
ORDER BY match_date, match_id
"""

CLUB_ID_NAMES_SQL = """
SELECT club_id,
       STRING_AGG(DISTINCT club_name, ' | ') AS clubs
FROM (
    SELECT club_id, club_name FROM basketball.club_id_overrides
    UNION ALL
    SELECT club_id, club_name FROM basketball.club_corrections
) AS all_clubs
GROUP BY club_id
HAVING COUNT(DISTINCT club_name) > 1
ORDER BY club_id
"""

ABNORMAL_OVERLAP_SQL = """
SELECT f.match_id, f.match_date, f.home_team, f.away_team
FROM basketball.fact_games AS f
JOIN basketball.abnormal_results AS a ON a.match_id = f.match_id
ORDER BY f.match_date, f.match_id
"""

OPEN_QUARANTINE_SQL = """
SELECT match_id, source_file, reason
FROM basketball.quarantine_games
WHERE status = 'open'
ORDER BY source_file, match_id
"""

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("run_checks")


def check_shared_ids(cur):
    cur.execute(SHARED_ID_SQL, (REGIONAL_LABELS,))
    rows = cur.fetchall()
    for api_team_id, team, countries in rows:
        log.error(
            "possible shared team id %s (%s) appears under: %s - check its games per league: "
            "a real shared id needs rows in club_id_overrides; a club visiting an "
            "international league needs that league in international_leagues",
            api_team_id, team, countries,
        )
    return len(rows)


def check_consistency(cur):
    cur.execute(CONSISTENCY_SQL)
    rows = cur.fetchall()
    for match_id, match_date, home, away, q1, q2, q3, q4, h1, h2, points in rows:
        log.error(
            "inconsistent totals in match %s (%s, %s vs %s): "
            "q=%s/%s/%s/%s h=%s/%s total_points=%s",
            match_id, match_date, home, away, q1, q2, q3, q4, h1, h2, points,
        )
    return len(rows)


def check_club_id_names(cur):
    cur.execute(CLUB_ID_NAMES_SQL)
    rows = cur.fetchall()
    for club_id, clubs in rows:
        log.error(
            "club_id %s carries more than one club name: %s - one club_id must "
            "belong to exactly one club; give the other club a new club_id "
            "(or fix the spelling if it is the same club)",
            club_id, clubs,
        )
    return len(rows)


def check_abnormal_overlap(cur):
    cur.execute(ABNORMAL_OVERLAP_SQL)
    rows = cur.fetchall()
    for match_id, match_date, home, away in rows:
        log.error(
            "match %s (%s, %s vs %s) is in both fact_games and abnormal_results - "
            "decide which is right, then remove it from the wrong table",
            match_id, match_date, home, away,
        )
    return len(rows)


def check_open_quarantine(cur):
    cur.execute(OPEN_QUARANTINE_SQL)
    rows = cur.fetchall()
    for match_id, source_file, reason in rows:
        log.warning("open quarantine: match %s (%s): %s", match_id, source_file, reason)
    return len(rows)


def main():
    load_dotenv(PROJECT_DIR / ".env")
    settings = get_db_settings()

    with psycopg.connect(**settings, autocommit=True) as conn, conn.cursor() as cur:
        shared_ids = check_shared_ids(cur)
        inconsistent = check_consistency(cur)
        club_id_clashes = check_club_id_names(cur)
        abnormal_overlap = check_abnormal_overlap(cur)
        open_quarantine = check_open_quarantine(cur)

    log.info(
        "checks done: %d possible shared ids, %d inconsistent games, "
        "%d club_ids with more than one name, %d games in both fact_games and "
        "abnormal_results, %d open quarantine rows",
        shared_ids, inconsistent, club_id_clashes, abnormal_overlap, open_quarantine,
    )

    if shared_ids or inconsistent or club_id_clashes or abnormal_overlap:
        log.error("FAILED: fix the problems above")
        return 1
    log.info("PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())