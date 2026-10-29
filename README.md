# Basketball Data Pipeline

Pulls basketball games from the Highlightly API, stores every raw response,
validates and cleans the games, and loads them into Postgres. The backend
(a separate project) reads the clean table to compute picks. This repo is
**only the data pipeline**: ingestion, raw storage, schema, validation,
scheduling, checks. It does no statistics.

Last updated: 2026-10-26.

---

## 1. How the data flows

```
Highlightly API
      |  fetch_daily.py (daily) / backfill.py (old days)
      v
raw/matches/YYYY-MM-DD.json      one file per UTC day, exactly what the API sent
      |  load_games.py
      v
basketball.fact_games            clean, validated games (one row per match_id)
basketball.quarantine_games      games that failed validation, with the reason
      |
      v
run_checks.py                    sanity checks over the whole table
      |
      v
backend (outside this repo)      computes picks from fact_games
```

Airflow runs the daily part (fetch, load, checks) at 06:00 UTC
(07:00 Lagos). Everything can also be run by hand from the terminal.

**Two different Postgres databases exist. Do not mix them up:**

| Name | Where | What it holds |
|---|---|---|
| Basketball DB `sports_intelligence_db` | Windows Postgres (port 5432) | `fact_games`, `quarantine_games`, lookup tables |
| Airflow metadata DB `airflow` | `postgres` container inside Docker | Airflow's own run history, users, state |

The Airflow containers reach the Windows database through
`host.docker.internal`. The compose file sets `DB_HOST` to that, overriding
`localhost` from `.env`.

---

## 2. Folder layout

| Path | What it is |
|---|---|
| `highlightly_client.py` | Shared code: API calls, quota tracking, raw file writing, change detection |
| `fetch_daily.py` | Daily extract: one day plus the day before |
| `backfill.py` | Fetches old days, newest first, resumable |
| `load_games.py` | Raw files to `fact_games` / `quarantine_games` |
| `run_checks.py` | Checks over the whole table; exit code 1 if a check fails |
| `dags/basketball_daily.py` | The Airflow DAG |
| `sql/01_schema.sql` | Creates the schema, tables, indexes |
| `sql/02_seed_lookups.sql` | Rows for the three lookup tables (keep in sync with production) |
| `docker-compose.yml`, `Dockerfile`, `requirements-airflow.txt` | Airflow stack |
| `.env` | Settings and secrets. **Never committed.** |
| `.env.example` | Placeholders only (committed) |
| `raw/matches/` | Raw day files (not in Git) |
| `raw/changes/` | Change reports when a day is re-fetched (not in Git) |
| `logs/` | Airflow logs (not in Git) |

---

## 3. The scripts

Run all of these from the project folder with the venv active.

### fetch_daily.py: the daily extract
- Fetches the target day (default: yesterday UTC) **and the day before**.
  Reason: games that finish late or get corrected by the API are picked up
  on the next run.
- Replaces an existing day file, so re-running is safe. An incomplete fetch
  (fewer matches than the API's total) is **not** saved, so it never
  replaces a good file.
- Before replacing a file it compares old and new, game by game, and writes
  a change report to `raw/changes/` (see section 8). Change detection never
  fails the run.
- Exits 1 on any fetch/quota/incomplete failure, so Airflow marks the task failed.
- `python fetch_daily.py` fetches yesterday and the day before.
- `python fetch_daily.py 2026-10-23` fetches 2026-10-23 and 2026-10-22.

### backfill.py: old days
- Goes backwards from yesterday to `BACKFILL_STOP_DATE`.
- The files on disk are the bookmark: a day that has a file is skipped, so
  each run continues where the last one stopped and also fills gaps.
- Stops when the quota is down to `QUOTA_RESERVE`.
- Run it in the terminal, **not** in Airflow. It is a one-off catch-up tool.

### load_games.py: raw to database
- Keeps finished games only (`Finished`, `Finished after over time`).
  Everything else counts as "not finished" and is skipped.
- Validates each game (section 5). Clean games are upserted into
  `fact_games` (`ON CONFLICT (match_id) DO UPDATE`). Bad games go to
  `quarantine_games` with a reason.
- One transaction per file. Safe to re-run.
- If a quarantined game later loads cleanly, its open quarantine rows are
  marked `fixed`.
- `python load_games.py` loads every file (about 2m15s for 731 files).
- `python load_games.py 2026-10-23` loads one day.

### run_checks.py: checks over the whole table
1. **Shared team ids:** the same API team id appearing under different
   countries (ignores leagues in `international_leagues`).
2. **Period sums:** quarters/halves must add up to the totals.
3. **Open quarantine:** warns about each open quarantine row (a warning,
   not a failure).
- Exit 1 if check 1 or 2 fails. Takes about 80 seconds on the full table.
- **Read the numbers, not just PASSED.** A shared id whose games are
  sitting in quarantine does not fail check 1. It only shows up in the
  quarantine count.

---

## 4. The database (schema `basketball`)

| Table | Purpose |
|---|---|
| `fact_games` | One row per finished, valid game. Primary key `match_id`. Has `home_club_id` / `away_club_id` (see below), quarter and half scores, totals, finals |
| `quarantine_games` | One row per (game, reason). `status`: `open`, `fixed` or `ignored`. Unique on `(match_id, reason)` |
| `club_id_overrides` | `(api_team_id, league_id)` to our own `club_id` |
| `half_style_leagues` | Leagues that report two halves, not four quarters |
| `international_leagues` | Leagues with invited clubs from other countries |

**Quarter columns are null for half-style leagues. `*_total` columns are
regulation time only (overtime subtracted); `*_final` include overtime.**

### club_id: why it exists
The API's team id is not always unique to one club. The same id can belong
to two different clubs in different countries (for example Atenas in
Argentina and Uruguay). `club_id` is the id we trust:
- normally `club_id` = the API team id
- if `(api_team_id, league_id)` is in `club_id_overrides`, `club_id` = the
  override. Override ids start at `9000001` so they can never collide with
  an API id.

---

## 5. Validation rules and quarantine

A finished game is quarantined (not dropped) when:

| Reason text | Meaning |
|---|---|
| `ambiguous club: api team id X in league Y has no row in club_id_overrides` | X is a shared id and league Y has no override row (see section 6) |
| `half-style league game: q1 and q2 should hold exactly one score` | A half-style league sent quarter-style data |
| `final score (current) missing` | The API has no final score |
| `zero quarter: qN is 0 - 0` | A quarter shows 0 - 0 |
| `home/away quarters sum to A, final minus overtime is B` | Quarter scores incomplete or wrong |
| `schema: <field>: ...` | A field is missing or the wrong type |

Quarantine rows are kept with the full raw record, so nothing is lost. Check
them with:

```sql
SELECT reason, COUNT(*) AS games
FROM basketball.quarantine_games
WHERE status = 'open'
GROUP BY reason
ORDER BY games DESC;
```
(`WHERE status = 'open'` keeps unresolved rows; `GROUP BY reason` + `COUNT(*)`
count games per reason; `ORDER BY games DESC` puts the biggest first.)

**Known limitation:** a stricter rule does not remove games already loaded.
To rebuild from scratch: `TRUNCATE TABLE basketball.fact_games RESTART IDENTITY;`
then `python load_games.py`.

---

## 6. Runbook: a shared team id is flagged

This is the main recurring job. `run_checks.py` prints
`possible shared team id ...`, or `load_games.py` quarantines games as
`ambiguous club`.

**The key rule: once an API id has ANY row in `club_id_overrides`, EVERY
league where that id plays needs its own row.** A league with no row means
the loader cannot tell which club it is, so those games are quarantined.
(We learned this on 2026-10-26: adding override rows for only one side of a
shared id quarantined 172 games of the other clubs until their leagues were
added.)

Steps:
1. **See where the id appears.** Run in pgAdmin on `sports_intelligence_db`:
   ```sql
   SELECT team_id, team, country, league_id, league, COUNT(*) AS games
   FROM (
       SELECT home_team_id AS team_id, home_team AS team, country, league_id, league
       FROM basketball.fact_games
       UNION ALL
       SELECT away_team_id, away_team, country, league_id, league
       FROM basketball.fact_games
   ) AS appearances
   WHERE team_id IN (123456)      -- put the flagged ids here
   GROUP BY team_id, team, country, league_id, league
   ORDER BY team_id, games DESC;
   ```
   (`UNION ALL` stacks home and away appearances; `WHERE team_id IN` keeps
   the flagged ids; `GROUP BY` + `COUNT(*)` counts games per league.)
2. **Look at the odd games** (the league with only a few games): opponent,
   date, score. Confirm against a real source (a club or league website, ESPN).
   Do not decide from the team name alone. On 2026-10-26 "York",
   "Concordia" and "USC Heidelberg" turned out to be US colleges that
   share ids with a Canadian and a German club.
3. **Decide which case it is:**
   - **Two different clubs share one id** -> add override rows
     (`club_id_overrides`), one per league, for **both** clubs. Give each
     club one new `club_id` (next free number above `9000000`), reused
     across that club's leagues.
   - **One club visiting a league abroad** (for example a Kazakh club in a
     Russian-hosted league) -> add the league to `international_leagues`.
     Cost: the check stops watching that whole league for shared ids.
4. **Insert the rows** in pgAdmin, then **add the same statement to
   `sql/02_seed_lookups.sql`** and commit it, so a rebuilt database matches
   production.
5. **Reload and check:** `python load_games.py`, then `python run_checks.py`.
   The reload corrects the club ids by upsert and marks the quarantine rows
   `fixed` (look for `marked fixed` in the final `done:` line).
6. If new leagues show up later with the same ambiguous reason (more backfill
   days), repeat from step 4 with the new league ids.

Override row template (one row per league per club):
```sql
INSERT INTO basketball.club_id_overrides
    (api_team_id, league_id, club_id, club_name, note)
VALUES
    (321611, 8443,  9000011, 'Laval (France)', 'Coupe de France'),
    (321611, 25463, 9000016, 'Laval (Canada)', 'U SPORTS')
ON CONFLICT (api_team_id, league_id) DO NOTHING;
```
(`ON CONFLICT ... DO NOTHING` skips existing keys, so re-running does nothing.)

**Open items:** WASL (league 331823) and league 307144 still have 27
ambiguous-club games (ids 888377, 816893, 109712). Not yet worked through.

---

## 7. The daily run (Airflow)

DAG `basketball_daily`, schedule `0 6 * * *` (06:00 UTC, 07:00 Lagos),
`catchup=True`, `max_active_runs=1`. Three tasks in order:

| Task | What it runs | Retries |
|---|---|---|
| `fetch_daily` | `python fetch_daily.py <target date>` | 2, 10 min apart |
| `load_games` | `python load_games.py <day before target>` then `<target>` | 0 |
| `run_checks` | `python run_checks.py` | 0 |

`fetch_daily >> load_games >> run_checks`. The target date is derived from
`dag_run.run_after` minus one day, i.e. the day that just finished in UTC.
If a run fails, later tasks do not run. Look at the red task's log first.

**Docker stack** (`docker-compose.yml`, image `basketball-airflow:3.3.2`):
`api-server` (UI), `scheduler`, `dag-processor`, the `postgres` metadata
database, and a one-off `airflow-init` that runs on every `up` (safe to
repeat). LocalExecutor.

- UI: http://127.0.0.1:8080 (user and password in `.env`)
- The PC must be on with Docker Desktop running at 06:00 UTC. A missed run
  is caught up later (`catchup=True`).

**When do I need to rebuild or recreate?**

| You changed | Do this |
|---|---|
| A `.py` file (DAG or scripts) | Nothing. Code is mounted live |
| `.env` or `docker-compose.yml` | `docker compose up -d --force-recreate` |
| `Dockerfile` or `requirements-airflow.txt` | `docker compose build`, then `docker compose up -d` |

(`up -d` starts the stack in the background; `--force-recreate` rebuilds the
containers so they re-read `.env`; `build` rebuilds the image.)

**Triggering manually:** use the CLI (from the project folder):
`docker compose exec airflow-scheduler airflow dags trigger basketball_daily`.
A run started from the UI "Trigger" button can finish in about 0.2 s with no
task instances. Cause: the DAG's `start_date` (2026-10-26 06:00 UTC) is
later than the manual run's logical date, so no tasks are created. This is
expected, not a bug. We left the start date as it is.

---

## 8. Change detection

When `fetch_daily.py` re-fetches a day that already has a file, it compares
the old and new file by `match_id` and writes
`raw/changes/YYYY-MM-DD_<fetched_at>.json`, with:
- counts: identical, changed, new, removed
- every changed field with its old and new value
- fields that appeared in or disappeared from the API data (a sign the API
  changed shape)

`state.clock` is ignored: a finished game shows clock 10 at first and `None`
later, which is noise. This is snapshot comparison, not real CDC. It is how we
found that scores get revised (for example games turning into overtime).

---

## 9. Quota facts (Highlightly)

- About 100 requests per day per key; resets at midnight UTC (1 AM Lagos).
- Remaining quota comes from the `x-ratelimit-requests-remaining` header;
  HTTP 429 means exhausted.
- `backfill.py` leaves `QUOTA_RESERVE` requests unused. `fetch_daily.py`
  ignores the reserve and may use everything.
- A full day is usually several pages of 100 games, so one day costs
  several requests.

---

## 10. Settings (`.env`)

Keys only. **Values are never written here or committed.**

`HIGHLIGHTLY_API_KEY`, `DB_HOST`, `DB_PORT`, `DB_NAME`, `DB_USER`,
`DB_PASSWORD`, `BACKFILL_STOP_DATE`, `QUOTA_RESERVE`, `FERNET_KEY`,
`AIRFLOW_JWT_SECRET`, `AIRFLOW_DB_PASSWORD`, `AIRFLOW_ADMIN_USERNAME`,
`AIRFLOW_ADMIN_PASSWORD`, `AIRFLOW_UID`. A `SLACK_WEBHOOK_URL` will be
added for alerts.

- `.env`, `logs/`, `raw/`, `venv/` are in `.gitignore`. Check `git status`
  before every commit.
- A value already in the environment wins over the same name loaded later by
  `python-dotenv`, so containers need recreating after a `.env` change.
- Before restricting access on any real database, confirm a recovery path
  that does not depend on that access.

---

## 11. Typical sessions

**Catch up on old days (terminal):**
```
python backfill.py        # fetch old days until the quota reserve is reached
python load_games.py      # load the new files
python run_checks.py      # check the whole table
```

**Check on a failed daily run:**
1. Open the Airflow UI and find the red task.
2. Read its log from the bottom up.
3. Fetch failed: quota or network. Load failed: read the traceback.
   Checks failed: read the `ERROR` lines.
4. Fix, then re-run that task or the whole run.

---

## 12. Known limitations and to-do

- Failure alerts to Slack are not set up yet.
- The backend run is not yet triggered by this pipeline (idea: a fourth task,
  so it only runs when the pipeline succeeded).
- 62 games are in open quarantine (27 ambiguous club, the rest score
  problems). They are not lost, only waiting for review.
- A stricter rule does not delete already-loaded rows (see section 5).
- The shared-id check only compares countries. A shared id inside one
  country would not be caught.
- One game per id/league can only map to one club, so a shared id inside
  one league cannot be split.
- Planned: dbt metrics layer, S3 backup of `raw/`, unit tests for the
  validation rules, GitHub Actions, Alembic migrations.
- Quarantine rows do not reopen. The insert uses ON CONFLICT (match_id, reason)
  DO NOTHING, so if a game that was marked 'fixed' comes back with the same
  reason, the row stays 'fixed' and the game is hidden from the open count.
  Fix: reopen 'fixed' rows (not 'ignored' ones) when the same game and reason
  recur.

---

## 13. Conventions

- No secrets in code or in Git.
- Every script does one thing and exits non-zero on failure.
- Lookup changes go in `sql/02_seed_lookups.sql` and are committed.
- Reloading is always safe (upserts).