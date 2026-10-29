"""
load_games.py

Reads the raw daily match files in raw/matches/, keeps finished games,
parses and validates the scores, and loads them into basketball.fact_games.
Games that fail validation go to basketball.quarantine_games with a reason.
When a game that was quarantined earlier now loads cleanly (for example
after a rule or a lookup table was fixed), its open quarantine rows are
marked 'fixed'.

Three small lookup tables in the database drive special cases:
  - basketball.league_corrections: games the API filed under the wrong
    league (match_id -> true league_id, league, country). The correction is
    applied first, so every rule below sees the true league. The raw files
    are never changed.
  - basketball.club_id_overrides: API team ids shared by different clubs
    (api_team_id + league_id -> club_id). A game involving a shared id in a
    league that is not listed is quarantined.
  - basketball.half_style_leagues: leagues that report two halves instead of
    four quarters. The league may put a half in either of its two slots
    (first half in q1 or q2, second half in q3 or q4), so each half is read
    from whichever slot has a score. For these games all four quarters are
    stored as null and only the halves are kept. If the API sent no period
    scores for a half, that half is stored as null and the game still loads.

Usage (run from the project folder, with the venv active):
    python load_games.py               # load every file in raw/matches
    python load_games.py 2026-10-23    # load one day only

Safe to re-run: fact_games is upserted on match_id, and quarantine
rows are de-duplicated on (match_id, reason).

After a full load, a league correction whose match_id was not found in any
raw file is reported as a warning (most likely a mistyped id).
"""

import json
import logging
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import psycopg
from dotenv import load_dotenv
from psycopg.types.json import Jsonb
from pydantic import BaseModel, ValidationError

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------
PROJECT_DIR = Path(__file__).resolve().parent
RAW_DIR = PROJECT_DIR / "raw" / "matches"

FINISHED_STATES = {"Finished", "Finished after over time"}
OVERTIME_STATE = "Finished after over time"
SCORE_PATTERN = re.compile(r"^\s*(\d+)\s*-\s*(\d+)\s*$")
QUARTERS = ("q1", "q2", "q3", "q4")
NO_SCORE = ((0, 0), (None, None))
REQUIRED_ENV = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")

FACT_COLUMNS = (
    "match_id", "match_date", "match_time", "country",
    "league_id", "league", "season",
    "home_team_id", "away_team_id", "home_team", "away_team",
    "home_club_id", "away_club_id",
    "home_q1", "home_q2", "home_q3", "home_q4",
    "away_q1", "away_q2", "away_q3", "away_q4",
    "home_h1", "home_h2", "away_h1", "away_h2",
    "home_total", "away_total",
    "total_q1", "total_q2", "total_q3", "total_q4",
    "total_h1", "total_h2", "total_points",
    "home_final", "away_final",
)

STAT_KEYS = ("rows", "loaded", "quarantined", "filtered", "resolved", "corrected")

columns_sql = ", ".join(FACT_COLUMNS)
values_sql = ", ".join(f"%({column})s" for column in FACT_COLUMNS)
updates_sql = ",\n    ".join(
    f"{column} = EXCLUDED.{column}" for column in FACT_COLUMNS if column != "match_id"
)

UPSERT_SQL = f"""
INSERT INTO basketball.fact_games ({columns_sql})
VALUES ({values_sql})
ON CONFLICT (match_id) DO UPDATE SET
    {updates_sql},
    loaded_at = now()
"""

QUARANTINE_SQL = """
INSERT INTO basketball.quarantine_games (match_id, raw_record, reason, source_file)
VALUES (%s, %s, %s, %s)
ON CONFLICT (match_id, reason) DO NOTHING
"""

RESOLVE_QUARANTINE_SQL = """
UPDATE basketball.quarantine_games
SET status = 'fixed'
WHERE match_id = %s
  AND status = 'open'
"""

OVERRIDES_SQL = """
SELECT api_team_id, league_id, club_id
FROM basketball.club_id_overrides
"""

HALF_STYLE_SQL = """
SELECT league_id
FROM basketball.half_style_leagues
"""

CORRECTIONS_SQL = """
SELECT match_id, league_id, league, country
FROM basketball.league_corrections
"""

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("load_games")


# ---------------------------------------------------------------------------
# Expected shape of one match record (Pydantic)
# ---------------------------------------------------------------------------
class Team(BaseModel):
    id: int
    name: str


class League(BaseModel):
    id: int
    name: str
    season: Optional[int] = None


class Country(BaseModel):
    name: Optional[str] = None


class Score(BaseModel):
    current: Optional[str] = None
    q1: Optional[str] = None
    q2: Optional[str] = None
    q3: Optional[str] = None
    q4: Optional[str] = None
    overTime: Optional[str] = None


class State(BaseModel):
    description: str
    score: Score


class Match(BaseModel):
    id: int
    date: datetime
    country: Optional[Country] = None
    homeTeam: Team
    awayTeam: Team
    league: League
    state: State


class QuarantineError(Exception):
    """A finished game that cannot be loaded cleanly. The message is the reason."""


# ---------------------------------------------------------------------------
# Club identity
# ---------------------------------------------------------------------------
class ClubResolver:
    """
    Turns (API team id, league id) into our club_id.

    Most API ids belong to one club, so club_id = the API id.
    A few API ids are shared by different clubs (same name, different
    country). Those ids are listed in club_id_overrides, one row per league.
    For such an id, the league decides the club; a league that is not
    listed cannot be decided, so the game is quarantined.
    """

    def __init__(self, override_rows):
        self.overrides = {
            (api_team_id, league_id): club_id
            for api_team_id, league_id, club_id in override_rows
        }
        self.shared_ids = {api_team_id for api_team_id, _ in self.overrides}

    def resolve(self, api_team_id, league_id):
        if api_team_id not in self.shared_ids:
            return api_team_id
        club_id = self.overrides.get((api_team_id, league_id))
        if club_id is None:
            raise QuarantineError(
                f"ambiguous club: api team id {api_team_id} in league {league_id} "
                f"has no row in club_id_overrides"
            )
        return club_id


# ---------------------------------------------------------------------------
# Transform
# ---------------------------------------------------------------------------
def parse_score(label, value):
    """Turn '105 - 104' into (105, 104). None gives (None, None)."""
    if value is None:
        return None, None
    found = SCORE_PATTERN.match(value)
    if not found:
        raise QuarantineError(f"unparseable {label} score: {value!r}")
    return int(found.group(1)), int(found.group(2))


def add(a, b):
    """Add two numbers, but stay None if either is missing (never a partial sum)."""
    if a is None or b is None:
        return None
    return a + b


def read_half(score, quarters, first, second):
    """
    For a half-style league: read one half from its two slots (for example
    q1 and q2).
      - Both slots missing (null and null): the API sent no period score for
        this half, so the half is stored as null. The game still loads with
        its final score, the same as a four-quarter game with no quarters.
      - Otherwise exactly one slot must hold a score and the other must be
        empty (null or 0 - 0). Anything else cannot be read safely.
    """
    if quarters[first] == (None, None) and quarters[second] == (None, None):
        return None, None

    present = [quarters[slot] for slot in (first, second) if quarters[slot] not in NO_SCORE]
    if len(present) != 1:
        raise QuarantineError(
            f"half-style league game: {first} and {second} should hold exactly one "
            f"score, got {first}={getattr(score, first)!r}, {second}={getattr(score, second)!r}"
        )
    return present[0]


def league_of(match, correction):
    """
    The league and country to use for a game: the correction if there is
    one (league_id, league, country), otherwise what the API sent.
    """
    if correction is not None:
        return correction
    country = match.country.name if match.country else None
    return match.league.id, match.league.name, country


def build_row(match, resolver, half_style_ids, correction=None):
    """Turn one validated finished match into one fact_games row."""
    league_id, league_name, country = league_of(match, correction)
    score = match.state.score

    home_final, away_final = parse_score("current", score.current)
    if home_final is None:
        raise QuarantineError("final score (current) missing")

    quarters = {q: parse_score(q, getattr(score, q)) for q in QUARTERS}

    home_ot, away_ot = parse_score("overTime", score.overTime)
    if match.state.description == OVERTIME_STATE and home_ot is None:
        raise QuarantineError("finished after over time but overTime score missing")

    if league_id in half_style_ids:
        # Two halves, not four quarters: keep only the halves.
        home_h1, away_h1 = read_half(score, quarters, "q1", "q2")
        home_h2, away_h2 = read_half(score, quarters, "q3", "q4")
        quarters = {q: (None, None) for q in QUARTERS}
    else:
        # Both teams scoring 0 in a quarter does not happen in a real game: the
        # points were put in another quarter, so every quarter and half is suspect.
        for q in QUARTERS:
            if quarters[q] == (0, 0):
                raise QuarantineError(f"zero quarter: {q} is 0 - 0")
        home_h1 = add(quarters["q1"][0], quarters["q2"][0])
        away_h1 = add(quarters["q1"][1], quarters["q2"][1])
        home_h2 = add(quarters["q3"][0], quarters["q4"][0])
        away_h2 = add(quarters["q3"][1], quarters["q4"][1])

    home_q = {q: quarters[q][0] for q in QUARTERS}
    away_q = {q: quarters[q][1] for q in QUARTERS}

    home_total = home_final - (home_ot or 0)
    away_total = away_final - (away_ot or 0)
    if home_total < 0 or away_total < 0:
        raise QuarantineError("overtime score is larger than final score")

    for side, h1, h2, total in (
        ("home", home_h1, home_h2, home_total),
        ("away", away_h1, away_h2, away_total),
    ):
        if h1 is not None and h2 is not None and h1 + h2 != total:
            raise QuarantineError(
                f"{side} quarters sum to {h1 + h2}, final minus overtime is {total}"
            )

    if match.homeTeam.id == match.awayTeam.id:
        raise QuarantineError("home and away team ids are the same")

    home_club_id = resolver.resolve(match.homeTeam.id, league_id)
    away_club_id = resolver.resolve(match.awayTeam.id, league_id)

    kickoff = match.date
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    kickoff = kickoff.astimezone(timezone.utc)

    return {
        "match_id": match.id,
        "match_date": kickoff.date(),
        "match_time": kickoff.time(),
        "country": country,
        "league_id": league_id,
        "league": league_name,
        "season": match.league.season,
        "home_team_id": match.homeTeam.id,
        "away_team_id": match.awayTeam.id,
        "home_team": match.homeTeam.name,
        "away_team": match.awayTeam.name,
        "home_club_id": home_club_id,
        "away_club_id": away_club_id,
        "home_q1": home_q["q1"], "home_q2": home_q["q2"],
        "home_q3": home_q["q3"], "home_q4": home_q["q4"],
        "away_q1": away_q["q1"], "away_q2": away_q["q2"],
        "away_q3": away_q["q3"], "away_q4": away_q["q4"],
        "home_h1": home_h1, "home_h2": home_h2,
        "away_h1": away_h1, "away_h2": away_h2,
        "home_total": home_total,
        "away_total": away_total,
        "total_q1": add(home_q["q1"], away_q["q1"]),
        "total_q2": add(home_q["q2"], away_q["q2"]),
        "total_q3": add(home_q["q3"], away_q["q3"]),
        "total_q4": add(home_q["q4"], away_q["q4"]),
        "total_h1": add(home_h1, away_h1),
        "total_h2": add(home_h2, away_h2),
        "total_points": home_total + away_total,
        "home_final": home_final,
        "away_final": away_final,
    }


# ---------------------------------------------------------------------------
# Load
# ---------------------------------------------------------------------------
def process_file(conn, path, resolver, half_style_ids, corrections, seen_corrections):
    """
    Load one raw day file in one transaction. Returns row counts.
    Every match id in the file that has a league correction is added to
    seen_corrections, so main() can report corrections that matched nothing.
    """
    payload = json.loads(path.read_text(encoding="utf-8"))
    matches = payload.get("matches")
    if not isinstance(matches, list):
        raise ValueError(f"{path.name}: no 'matches' list in file")

    total_count = payload.get("total_count")
    returned_count = payload.get("returned_count")
    if not payload.get("complete") or total_count != returned_count:
        log.warning(
            "%s: incomplete raw file (returned %s of %s) - this day should be re-fetched",
            path.name, returned_count, total_count,
        )

    stats = dict.fromkeys(STAT_KEYS, 0)
    stats["rows"] = len(matches)

    with conn.transaction(), conn.cursor() as cur:
        for raw in matches:
            correction = corrections.get(raw.get("id"))
            if correction is not None:
                seen_corrections.add(raw.get("id"))

            state = (raw.get("state") or {}).get("description")
            if state not in FINISHED_STATES:
                stats["filtered"] += 1
                continue

            try:
                row = build_row(Match.model_validate(raw), resolver, half_style_ids, correction)
            except ValidationError as err:
                first = err.errors()[0]
                field = ".".join(str(part) for part in first["loc"])
                reason = f"schema: {field}: {first['msg']}"
            except QuarantineError as err:
                reason = str(err)
            else:
                cur.execute(UPSERT_SQL, row)
                stats["loaded"] += 1
                if correction is not None:
                    stats["corrected"] += 1

                cur.execute(RESOLVE_QUARANTINE_SQL, (row["match_id"],))
                if cur.rowcount:
                    stats["resolved"] += cur.rowcount
                    log.info(
                        "%s: match %s now loads cleanly - %d quarantine row(s) marked fixed",
                        path.name, row["match_id"], cur.rowcount,
                    )
                continue

            cur.execute(QUARANTINE_SQL, (raw.get("id"), Jsonb(raw), reason, path.name))
            stats["quarantined"] += 1
            log.warning("%s: match %s quarantined: %s", path.name, raw.get("id"), reason)

    accounted = stats["loaded"] + stats["quarantined"] + stats["filtered"]
    if accounted != stats["rows"]:
        raise RuntimeError(f"{path.name}: {accounted} rows accounted for, file has {stats['rows']}")

    return stats


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
def get_db_settings():
    missing = [name for name in REQUIRED_ENV if not os.getenv(name)]
    if missing:
        log.error("missing in .env: %s", ", ".join(missing))
        sys.exit(1)
    return {
        "host": os.getenv("DB_HOST"),
        "port": int(os.getenv("DB_PORT")),
        "dbname": os.getenv("DB_NAME"),
        "user": os.getenv("DB_USER"),
        "password": os.getenv("DB_PASSWORD"),
    }


def files_to_load(args):
    if len(args) > 1:
        log.error("usage: python load_games.py [YYYY-MM-DD]")
        sys.exit(1)

    if args:
        try:
            date.fromisoformat(args[0])
        except ValueError:
            log.error("date must be YYYY-MM-DD, got %r", args[0])
            sys.exit(1)
        path = RAW_DIR / f"{args[0]}.json"
        if not path.exists():
            log.error("no raw file for %s at %s", args[0], path)
            sys.exit(1)
        return [path]

    files = sorted(RAW_DIR.glob("*.json"))
    if not files:
        log.error("no raw files found in %s", RAW_DIR)
        sys.exit(1)
    return files


def read_lookups(conn):
    """Read the three lookup tables once, before any file is loaded."""
    with conn.cursor() as cur:
        cur.execute(OVERRIDES_SQL)
        resolver = ClubResolver(cur.fetchall())
        cur.execute(HALF_STYLE_SQL)
        half_style_ids = frozenset(league_id for (league_id,) in cur.fetchall())
        cur.execute(CORRECTIONS_SQL)
        corrections = {
            match_id: (league_id, league, country)
            for match_id, league_id, league, country in cur.fetchall()
        }

    log.info(
        "club_id_overrides: %d rows, %d shared api ids; half_style_leagues: %d leagues; "
        "league_corrections: %d rows",
        len(resolver.overrides), len(resolver.shared_ids), len(half_style_ids), len(corrections),
    )
    return resolver, half_style_ids, corrections


def main():
    load_dotenv(PROJECT_DIR / ".env")
    args = sys.argv[1:]
    files = files_to_load(args)
    settings = get_db_settings()

    totals = dict.fromkeys(STAT_KEYS, 0)
    failed = []
    seen_corrections = set()

    with psycopg.connect(**settings, autocommit=True) as conn:
        resolver, half_style_ids, corrections = read_lookups(conn)

        for path in files:
            try:
                stats = process_file(
                    conn, path, resolver, half_style_ids, corrections, seen_corrections
                )
            except Exception:
                log.exception("%s: failed - nothing from this file was loaded", path.name)
                failed.append(path.name)
                continue

            log.info(
                "%s: %d rows -> %d loaded, %d quarantined, %d not finished, "
                "%d league corrections",
                path.name, stats["rows"], stats["loaded"], stats["quarantined"],
                stats["filtered"], stats["corrected"],
            )
            for key in totals:
                totals[key] += stats[key]

    log.info(
        "done: %d files, %d rows -> %d loaded, %d quarantined, %d not finished, "
        "%d quarantine rows marked fixed, %d league corrections applied",
        len(files) - len(failed), totals["rows"], totals["loaded"],
        totals["quarantined"], totals["filtered"], totals["resolved"], totals["corrected"],
    )

    # Only a full load sees every raw file, so only then can an unused
    # correction be reported. A failed file may hold the missing match.
    if not args and not failed:
        unused = sorted(set(corrections) - seen_corrections)
        if unused:
            log.warning(
                "%d league corrections matched no game in raw/matches (mistyped match_id?): %s",
                len(unused), ", ".join(str(match_id) for match_id in unused),
            )

    if failed:
        log.error("failed files: %s", ", ".join(failed))
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())