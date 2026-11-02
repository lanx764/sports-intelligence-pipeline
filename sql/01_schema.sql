-- 01_schema.sql
-- Creates the basketball schema and its eight tables.
-- Safe to run more than once: everything uses IF NOT EXISTS.
--
--   fact_games            clean, validated finished games (one row per match)
--   quarantine_games      games that failed validation, with the reason
--   abnormal_results      finished games whose result is not a normal played
--                         result (a team scored 0, no quarters, no overtime)
--   club_id_overrides     lookup: API team ids shared by different clubs
--   club_corrections      lookup: one side of one game is a specific club
--   league_corrections    lookup: games the API filed under the wrong league
--   half_style_leagues    lookup: leagues that report two halves, not quarters
--   international_leagues lookup: leagues with invited clubs from other countries
--
-- Run 02_seed_lookups.sql after this file.

CREATE SCHEMA IF NOT EXISTS basketball;

-- ---------------------------------------------------------------------------
-- fact_games
-- Quarter columns are null for half-style leagues. *_total columns are
-- regulation time only (overtime subtracted); *_final include overtime.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS basketball.fact_games (
    match_id        BIGINT       PRIMARY KEY,
    match_date      DATE         NOT NULL,
    match_time      TIME         NOT NULL,
    country         TEXT,
    league_id       BIGINT       NOT NULL,
    league          TEXT,
    season          INTEGER,

    home_team_id    BIGINT       NOT NULL,
    away_team_id   BIGINT       NOT NULL,
    home_team       TEXT         NOT NULL,
    away_team       TEXT         NOT NULL,

    home_club_id    BIGINT       NOT NULL,
    away_club_id    BIGINT       NOT NULL,

    home_q1         SMALLINT CHECK (home_q1 >= 0),
    home_q2         SMALLINT CHECK (home_q2 >= 0),
    home_q3         SMALLINT CHECK (home_q3 >= 0),
    home_q4         SMALLINT CHECK (home_q4 >= 0),
    away_q1         SMALLINT CHECK (away_q1 >= 0),
    away_q2         SMALLINT CHECK (away_q2 >= 0),
    away_q3         SMALLINT CHECK (away_q3 >= 0),
    away_q4         SMALLINT CHECK (away_q4 >= 0),

    home_h1         SMALLINT,
    home_h2         SMALLINT,
    away_h1         SMALLINT,
    away_h2         SMALLINT,

    home_total      SMALLINT,
    away_total      SMALLINT,

    total_q1        SMALLINT,
    total_q2        SMALLINT,
    total_q3        SMALLINT,
    total_q4        SMALLINT,
    total_h1        SMALLINT,
    total_h2        SMALLINT,
    total_points    SMALLINT,

    home_final      SMALLINT     NOT NULL CHECK (home_final >= 0),
    away_final      SMALLINT     NOT NULL CHECK (away_final >= 0),

    loaded_at       TIMESTAMPTZ  NOT NULL DEFAULT now(),

    CONSTRAINT different_teams CHECK (home_team_id <> away_team_id)
);

CREATE INDEX IF NOT EXISTS idx_fact_games_home_club
    ON basketball.fact_games (home_club_id, match_date, match_time);

CREATE INDEX IF NOT EXISTS idx_fact_games_away_club
    ON basketball.fact_games (away_club_id, match_date, match_time);

CREATE INDEX IF NOT EXISTS idx_fact_games_match_date
    ON basketball.fact_games (match_date);

-- ---------------------------------------------------------------------------
-- quarantine_games
-- One row per (game, reason). status: open -> fixed (loaded cleanly later)
-- or ignored (reviewed and deliberately left out).
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS basketball.quarantine_games (
    quarantine_id   BIGSERIAL    PRIMARY KEY,
    match_id        BIGINT,
    raw_record      JSONB        NOT NULL,
    reason          TEXT         NOT NULL,
    source_file     TEXT         NOT NULL,
    detected_at     TIMESTAMPTZ  NOT NULL DEFAULT now(),
    status          TEXT         NOT NULL DEFAULT 'open'
                    CHECK (status IN ('open', 'fixed', 'ignored')),

    CONSTRAINT uq_quarantine_match_reason UNIQUE (match_id, reason)
);

-- ---------------------------------------------------------------------------
-- abnormal_results
-- Finished games that are not normal played results. A team cannot score 0
-- in a played game, so a finished game with a 0 final score, no quarter
-- scores and no overtime score is a walkover, forfeit, abandoned game or
-- similar. These games never go into fact_games (the loader also removes
-- them from it), so fact_games only holds normal played games. There are no
-- club columns: these games skip the club lookup.
-- `reason` says which rule put the game here.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS basketball.abnormal_results (
    match_id      BIGINT       PRIMARY KEY,
    match_date    DATE         NOT NULL,
    match_time    TIME,
    country       TEXT,
    league_id     BIGINT       NOT NULL,
    league        TEXT         NOT NULL,
    season        INTEGER,
    home_team_id  BIGINT       NOT NULL,
    away_team_id  BIGINT       NOT NULL,
    home_team     TEXT         NOT NULL,
    away_team     TEXT         NOT NULL,
    home_final    INTEGER      NOT NULL,
    away_final    INTEGER      NOT NULL,
    reason        TEXT         NOT NULL,
    raw_record    JSONB        NOT NULL,
    source_file   TEXT         NOT NULL,
    loaded_at     TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- ---------------------------------------------------------------------------
-- Lookup tables (rows are in 02_seed_lookups.sql)
-- ---------------------------------------------------------------------------

-- An API team id used by different clubs in different leagues:
-- (api_team_id, league_id) -> our own club_id (9,000,000 and above).
-- A club_id must belong to exactly one real club: check the highest id in
-- BOTH this table and club_corrections before handing out a new one.
CREATE TABLE IF NOT EXISTS basketball.club_id_overrides (
    api_team_id   BIGINT  NOT NULL,
    league_id     BIGINT  NOT NULL,
    club_id       BIGINT  NOT NULL,
    club_name     TEXT    NOT NULL,
    note          TEXT,
    PRIMARY KEY (api_team_id, league_id)
);

-- One side of one game is a specific club, for the case where an API team
-- id is used by two different clubs inside the SAME league, so
-- (api_team_id, league_id) cannot tell them apart. api_team_id is the id
-- the loader expects on that side; a mismatch quarantines the game.
CREATE TABLE IF NOT EXISTS basketball.club_corrections (
    match_id      BIGINT  NOT NULL,
    side          TEXT    NOT NULL CHECK (side IN ('home', 'away')),
    api_team_id   BIGINT  NOT NULL,
    club_id       BIGINT  NOT NULL,
    club_name     TEXT    NOT NULL,
    note          TEXT,
    PRIMARY KEY (match_id, side)
);

-- Games the API filed under the wrong league: match_id -> the true league.
CREATE TABLE IF NOT EXISTS basketball.league_corrections (
    match_id    BIGINT       PRIMARY KEY,
    league_id   BIGINT       NOT NULL,
    league      TEXT         NOT NULL,
    country     TEXT         NOT NULL,
    reason      TEXT         NOT NULL,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT now()
);

-- Leagues that report two halves (in q2 and q4, or q1 and q3) instead of
-- four quarters.
CREATE TABLE IF NOT EXISTS basketball.half_style_leagues (
    league_id    BIGINT  PRIMARY KEY,
    league_name  TEXT    NOT NULL,
    note         TEXT
);

-- Leagues hosting invited clubs from other countries, so the same team id
-- legitimately appears under more than one country. Ignored by the
-- shared-id check in run_checks.py.
CREATE TABLE IF NOT EXISTS basketball.international_leagues (
    league_id    BIGINT  PRIMARY KEY,
    league_name  TEXT    NOT NULL,
    note         TEXT
);