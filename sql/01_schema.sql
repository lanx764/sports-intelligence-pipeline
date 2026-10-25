-- 01_schema.sql
-- Creates the basketball schema and its five tables.
-- Safe to run more than once: everything uses IF NOT EXISTS.
--
--   fact_games            clean, validated finished games (one row per match)
--   quarantine_games      games that failed validation, with the reason
--   club_id_overrides     lookup: API team ids shared by different clubs
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
    away_team_id    BIGINT       NOT NULL,
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
-- Lookup tables (rows are in 02_seed_lookups.sql)
-- ---------------------------------------------------------------------------

-- An API team id used by different clubs in different leagues:
-- (api_team_id, league_id) -> our own club_id (9,000,000 and above).
CREATE TABLE IF NOT EXISTS basketball.club_id_overrides (
    api_team_id   BIGINT  NOT NULL,
    league_id     BIGINT  NOT NULL,
    club_id       BIGINT  NOT NULL,
    club_name     TEXT    NOT NULL,
    note          TEXT,
    PRIMARY KEY (api_team_id, league_id)
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