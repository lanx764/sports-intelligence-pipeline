# Basketball Data Pipeline

Pulls basketball games from the Highlightly API, stores every raw response,
validates and cleans the games, and loads them into Postgres. The backend
(a separate project) reads the clean table to compute picks. This repo is
**only the data pipeline**: ingestion, raw storage, schema, validation,
scheduling, checks. It does no statistics.

Last updated: 2026-10-29.

---

## 1. How the data flows

```
Highlightly API
      |  fetch_daily.py (daily) / backfill.py (old days)
      v
raw/matches/YYYY-MM-DD.json      one file per UTC day, exactly what the API sent
      |  load_games.py  (+ lookup tables: corrections, club overrides, half-style)
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
| `sql/02_seed_lookups.sql` | Rows for the four lookup tables (keep in sync with production) |
| `docker-compose.yml`, `Dockerfile`, `requirements-airflow.txt` | Airflow stack |
| `.env` | Settings and secrets. **Never committed.** |
| `.env.example` | Placeholders only (committed) |
| `raw/matches/` | Raw day files (not in Git). **Never edited by hand** |
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
- **It shares the API key with the daily DAG.** A backfill late at night
  can use up the quota before the 07:00 run. Keep `QUOTA_RESERVE` high enough
  to leave the daily run what it needs (section 9).

### load_games.py: raw to database
- Keeps finished games only (`Finished`, `Finished after over time`).
  Everything else counts as "not finished" and is skipped.
- Reads three lookup tables once at startup: `league_corrections`,
  `club_id_overrides`, `half_style_leagues`.
- For a game listed in `league_corrections`, the true league and country
  replace what the API sent **before any rule runs**, so every later rule
  (half-style check, club lookup) sees the true league.
- Validates each game (section 5). Clean games are upserted into
  `fact_games` (`ON CONFLICT (match_id) DO UPDATE`). Bad games go to
  `quarantine_games` with a reason.
- One transaction per file. Safe to re-run.
- If a quarantined game later loads cleanly, its open quarantine rows are
  marked `fixed`.
- After a full load it warns about any league correction whose `match_id`
  matched no game in `raw/matches` (most likely a mistyped id).
- `python load_games.py` loads every file (about 3.5 minutes for 1,298 files).
- `python load_games.py 2026-10-23` loads one day.
- Short view of the result:
  `python load_games.py 2>&1 | tail -n 5`
  (on Git Bash, add `grep -a` when filtering, because some names contain
  non-ASCII letters like š and plain `grep` would say "Binary file matches").

### run_checks.py: checks over the whole table
1. **Shared team ids:** the same API team id appearing under different
   countries (ignores leagues in `international_leagues`).
2. **Period sums:** quarters/halves must add up to the totals.
3. **Open quarantine:** warns about each open quarantine row (a warning,
   not a failure).
- Exit 1 if check 1 or 2 fails. Takes about 80 seconds on the full table.
- Short view of the result:
  `python run_checks.py 2>&1 | grep -a -E "ERROR|checks done|PASSED|FAILED"`
- **Read the numbers, not just PASSED.** A shared id whose games are
  sitting in quarantine does not fail check 1. It only shows up in the
  quarantine count.
- `load_games.py` is the gatekeeper for one game at a time and only knows the
  ids listed in the lookup tables. `run_checks.py` audits the whole table and
  is how **new** problems are discovered. Treat `run_checks.py` as the main
  source of truth.

---

## 4. The database (schema `basketball`)

| Table | Purpose |
|---|---|
| `fact_games` | One row per finished, valid game. Primary key `match_id`. Has `home_club_id` / `away_club_id` (see below), quarter and half scores, totals, finals |
| `quarantine_games` | One row per (game, reason). `status`: `open`, `fixed` or `ignored`. Unique on `(match_id, reason)` |
| `club_id_overrides` | `(api_team_id, league_id)` to our own `club_id` |
| `half_style_leagues` | Leagues that report two halves, not four quarters |
| `international_leagues` | Leagues with invited clubs from other countries |
| `league_corrections` | Games the API filed under the wrong league: `match_id` to the true league |

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

### league_corrections: why it exists
Sometimes the API files a game under the wrong league. Example: 23 UK WBBL
games were filed under Spain "Liga Femenina Women" (80778). Editing
`fact_games` by hand does not last, because the next reload overwrites it from
the raw file. Editing the raw file breaks the rule that raw is never changed.
So the fix is a lookup table the loader applies every time.

| Column | Meaning |
|---|---|
| `match_id` | The API match id (primary key) |
| `league_id` | The true league id |
| `league` | The true league name |
| `country` | The true country |
| `reason` | Why we believe the API is wrong (how it was verified) |
| `created_at` | When the row was added |

---

## 5. Validation rules and quarantine

A finished game is quarantined (not dropped) when:

| Reason text | Meaning |
|---|---|
| `ambiguous club: api team id X in league Y has no row in club_id_overrides` | X is a shared id and league Y has no override row (see section 6) |
| `home and away team ids are the same` | Both sides carry one team id (usually a generic or mislabelled team) |
| `half-style league game: q1 and q2 should hold exactly one score` | A half-style league sent quarter-style data |
| `final score (current) missing` | The API has no final score |
| `finished after over time but overTime score missing` | Marked overtime, but no overtime score |
| `overtime score is larger than final score` | Impossible overtime value |
| `zero quarter: qN is 0 - 0` | A quarter shows 0 - 0 |
| `home/away quarters sum to A, final minus overtime is B` | Quarter scores incomplete or wrong |
| `unparseable <period> score` | A score is not in the `105 - 104` shape |
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

`fixed` rows are kept on purpose: they are the history of what was wrong.
`run_checks.py` counts only `open` rows.

**Known limitations:**
- A stricter rule does not remove games already loaded.
  To rebuild from scratch: `TRUNCATE TABLE basketball.fact_games RESTART IDENTITY;`
  then `python load_games.py`.
- Quarantine inserts use `ON CONFLICT (match_id, reason) DO NOTHING`. If a
  game was marked `fixed` and later fails for the **same** reason again, the
  row stays `fixed` and hidden. Planned fix: reopen `fixed` rows (not
  `ignored` ones) when the same reason returns.
- Do not hand-`UPDATE` `fact_games`. A reload overwrites it from raw. Durable
  fixes are lookup-table rows applied by the loader.

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
   - **The API filed a few games under the wrong league** (a club shows up
     in a league of another country, a handful of games, dates that fit its
     real league) -> this is **not** a shared id. Research the true league
     and country of each game and add one row per game to
     `league_corrections`. Do **not** add the league to
     `international_leagues`: both leagues are real, and that would stop
     watching the whole league.
4. **Insert the rows** in pgAdmin, then **add the same statement to
   `sql/02_seed_lookups.sql`** and commit it, so a rebuilt database matches
   production.
5. **Reload and check:** `python load_games.py`, then `python run_checks.py`.
   The reload corrects the club ids and leagues by upsert and marks the
   quarantine rows `fixed` (look for `marked fixed` in the final `done:` line).
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

League correction template (one row per game):
```sql
INSERT INTO basketball.league_corrections
    (match_id, league_id, league, country, reason)
VALUES
    (123456789, 93543, 'WBBL Women', 'United Kingdom',
     'API filed this game under Spain Liga Femenina Women (80778); true league confirmed by manual research')
ON CONFLICT (match_id) DO NOTHING;
```
(`match_id` is the API id of the one game; `league_id`, `league`, `country`
are the **true** values; `reason` records how it was verified;
`ON CONFLICT ... DO NOTHING` makes a re-run harmless.)

**Open items (ambiguous-club games still in quarantine, 70 of them):**
- ids 888377 and 816893 in WASL (league 331823)
- id 109712 in leagues 307144, 306293, 335227, 307995
- id 352247 in league 26314
- id 610951 in league 165878

Not yet worked through. Same process as above.

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
If a run fails, later tasks do not run (they show `upstream_failed`). Look at
the red task's log first.

**Docker stack** (`docker-compose.yml`, image `basketball-airflow:3.3.2`):
`api-server` (UI), `scheduler`, `dag-processor`, the `postgres` metadata
database, and a one-off `airflow-init` that runs on every `up` (safe to
repeat). LocalExecutor.

- UI: http://127.0.0.1:8080 (user and password in `.env`)
- The PC must be on with Docker Desktop running at 06:00 UTC. A missed run
  is caught up later (`catchup=True`): when the laptop comes back, Airflow
  runs the missed 07:00 run. A sleeping laptop is the weakest link until the
  pipeline moves to an always-on Linux server.

**When do I need to rebuild or recreate?**

| You changed | Do this |
|---|---|
| A `.py` file (DAG or scripts) | Nothing. Code is mounted live |
| `.env` or `docker-compose.yml` | `docker compose up -d --force-recreate` |
| `Dockerfile` or `requirements-airflow.txt` | `docker compose build`, then `docker compose up -d` |

(`up -d` starts the stack in the background; `--force-recreate` rebuilds the
containers so they re-read `.env`; `build` rebuilds the image.)

### Task states and retries

| State | Meaning | What to do |
|---|---|---|
| `up_for_retry` | An attempt failed and retries are left | Nothing. Airflow retries by itself after the delay |
| `failed` | All attempts used up | Read the log, fix the cause, then clear the task |
| `upstream_failed` | A task before it failed | Nothing. It runs again after the failed task is cleared with downstream |

- **Retries fix temporary problems** (network down, DNS error like
  `socket.gaierror -2`). **They do not fix an exhausted API quota**, which only
  resets at midnight UTC. If the key is exhausted, put a new key in `.env`,
  run `docker compose up -d --force-recreate`, then clear the failed task.

### Re-running a failed run (Airflow UI)
1. Open the failed run, select the failed task (`fetch_daily`).
2. **Clear** it with **Downstream** ticked, so `load_games` and `run_checks`
   run again too.
3. The tasks re-run on their own and the same run turns green.

### Triggering a brand-new run
The UI **Trigger** button can finish in about 0.2 s with no task instances.
Cause: the DAG's `start_date` (2026-10-26 06:00 UTC) is later than the manual
run's logical date, so no tasks are created. This is expected, not a bug. Use
**Clear** on an existing failed run (above), or the CLI from the project folder:
`docker compose exec airflow-scheduler airflow dags trigger basketball_daily`.

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
found that scores get revised (for example games turning into overtime) and
that late games appear on re-fetch (2026-10-25: 249 -> 252 games, 3 new).

The files stay the source of truth. A table for them is possible later (a
separate load step), after about two weeks of reports. The question to answer
first: how long after the first fetch do late games appear, and is the
two-day window enough?

---

## 9. Quota facts (Highlightly)

- About 100 requests per day per key; resets at midnight UTC (1 AM Lagos).
- Remaining quota comes from the `x-ratelimit-requests-remaining` header;
  HTTP 429 means exhausted.
- `backfill.py` leaves `QUOTA_RESERVE` requests unused. `fetch_daily.py`
  ignores the reserve and may use everything.
- A full day is usually several pages of 100 games, so one day costs
  several requests.
- `backfill.py` and the DAG share one key. A backfill after 1 AM Lagos can
  exhaust the quota before the 07:00 run. Set `QUOTA_RESERVE` accordingly.

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
4. Fix, then clear the failed task with Downstream ticked (section 7).

---

## 12. Known limitations and to-do

- Failure alerts to Slack are not set up yet. Plan: an Airflow connection and
  an `on_failure_callback`, firing only after `fetch_daily`'s retries run out.
- The backend run is not yet triggered by this pipeline (idea: a fourth task,
  so it only runs when the pipeline succeeded).
- 149 games are in open quarantine (70 ambiguous club; the rest are score
  problems, same-team ids and one missing overtime score). They are not lost,
  only waiting for review.
- A stricter rule does not delete already-loaded rows (see section 5).
- A `fixed` quarantine row hides a repeat of the same reason (section 5).
- League corrections are added by hand after research. Nothing detects a
  misfiled game except the shared-id check in `run_checks.py`.
- The shared-id check only compares countries. A shared id inside one
  country would not be caught.
- One game per id/league can only map to one club, so a shared id inside
  one league cannot be split.
- A full load reprocesses every file (about 3.5 minutes). A "skip unchanged
  files" step is possible later.
- The pipeline connects as the main database user. A limited pipeline role
  is planned.
- Planned: dbt metrics layer, S3 backup of `raw/`, unit tests for the
  validation rules, GitHub Actions, Alembic migrations, moving to a Linux server.

### Known data issues in the API
- The same team id can belong to different clubs (shared ids, section 6).
- 24 games were filed under the wrong league: 23 UK WBBL games under Spain
  "Liga Femenina Women" (80778) and 1 Lithuanian game under Greece
  "Basket League" (39079). They are fixed through `league_corrections` (the
  match ids are in `sql/02_seed_lookups.sql`). Both leagues are real, so
  neither is in `international_leagues`.
- Generic all-star teams "East" and "West" share ids across NBA and the
  Czech NBL; they are handled with override rows.
- Scores are sometimes revised after the game (for example into overtime), and
  late games can appear on re-fetch.

---

## 13. Conventions

- No secrets in code or in Git.
- Every script does one thing and exits non-zero on failure.
- Lookup changes go in `sql/02_seed_lookups.sql` (and the table definition in
  `sql/01_schema.sql`) and are committed.
- Raw files are never edited. Fixes are lookup rows applied by the loader.
- Reloading is always safe (upserts).
- Use `TRUNCATE ... RESTART IDENTITY` (not `DELETE`) when clearing a table.
- Commit messages end with the Co-Authored-By and Claude-Session trailers.