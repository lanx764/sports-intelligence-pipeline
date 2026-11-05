# Roadmap

The plan for the data platform behind this repo. Each stage says what "done" means, so progress can be checked rather than claimed.

Last updated: 2026-11-05.

---

## Where it stands

| Stage | Status |
|---|---|
| 1. Pipeline foundation | Done, with a few named loose ends |
| 2. dbt layer | In progress |
| 3. Reliability and engineering hygiene | Next |
| 4. Downstream consumer | Planned |
| 5. Honest evaluation of statistical methods | Planned |
| 6. Always-on server | Planned |
| 7. More sports | Planned |

Basketball comes first. Once it works end to end, the same pattern is repeated for each new sport.

---

## Stage 1: Pipeline foundation (done)

Built and running:
- Daily fetch from the Highlightly API, with raw responses kept as files
- Validation with a quarantine table, and a separate table for forfeits and walkovers
- Handling for team ids that the API shares between different clubs
- Loading into Postgres with safe re-runs
- Data-quality checks (`run_checks.py`)
- Airflow schedule at 06:00 UTC, Slack failure and success messages, and a dead man's switch

**Loose ends, tracked rather than hidden:**
- 118 games still in quarantine (zero-quarter scores, missing final scores, a few unresolved shared team ids)
- Backfill depth (how far back to fetch history) is not decided yet
- The red failure message has only been tested with a simulated failure

**Done when:** several days of green scheduled runs, and a quarantine that is fully understood.

---

## Stage 2: dbt layer (in progress)

Goal: turn the clean games into tables that statistics can be built on, without ever using information from the future.

Done:
- dbt project, connection through environment variables, and the source declaration
- `stg_basketball__games`: a cleaned view with a UTC kickoff time
- `team_games`: one row per team per game
- Seven written definitions for form and head-to-head (the "before kickoff only" rule, which games count, how overtime is treated, what happens with fewer than 5 games, and so on)

Remaining:
- `team_form`: for every team and game, the stats from the 5 games before it, with columns showing how many games were used and how old the oldest one is
- Head-to-head per pair of clubs, with the same rules
- A "current form" model for games not yet played

**Done when:** form and head-to-head for any team or pair come out of dbt and are rebuilt daily.

---

## Stage 3: Reliability and engineering hygiene (next)

Goal: make what exists safe to depend on.

- Back up the raw files to cloud storage (AWS S3). They cannot be refetched quickly, because the API allows about 100 requests a day
- dbt tests (not-null, unique, relationship and row-count checks), then `dbt run` and `dbt test` as Airflow tasks after the checks
- Continuous integration with GitHub Actions: run the validation rules' unit tests and dbt checks on every push
- A limited database user for dbt (write access to its own schema only) instead of a superuser
- Clear the remaining quarantine and decide the backfill depth

**Done when:** a broken change fails a test before it reaches the data, and losing the machine would not lose the raw history.

---

## Stage 4: Downstream consumer

Goal: show that the tables are usable.

- A small backend service that reads the dbt tables, joins them to upcoming fixtures, and produces a report
- It runs only after a successful pipeline run

**Done when:** one real report is produced automatically from the dbt tables.

---

## Stage 5: Honest evaluation of statistical methods

Goal: judge methods on evidence, not intuition.

- Backtest on past games using only information available before each game
- Compare methods by how often they were right, and keep the results in a table
- Keep whichever method does better; replace it if it is weak

**Done when:** the quality of the current method is known as a number, and it can be swapped without changing the pipeline.

---

## Stage 6: Always-on server

Goal: stop depending on a laptop.

- Run the same Docker stack on an always-on Linux server
- Proper secrets handling, automatic restarts, and monitoring

**Done when:** closing the laptop does not stop a run.

---

## Stage 7: More sports

Each new sport follows the same checklist: its API and quota, raw files, validation rules, dbt models, and its own schema. Football is next, then tennis.

---

## Design decisions made

- **Raw files are the system of record.** The database can be rebuilt from them.
- **dbt builds the stable numbers, and consumers make the decisions.** The pipeline reports facts; it does not recommend anything.
- **Strictly "before kickoff".** A game never counts toward its own form, and no statistic may use a game that came after.
- **Team identity is `club_id`**, not the API's team id, because the API reuses ids across clubs.
- **Bad data is quarantined with a reason**, never silently dropped.
- **Staging models are views; real calculations are tables.** Cheap and always fresh, or expensive and stored.

## Open decisions

- How far back to backfill
- Hosting provider and budget for the server
- Which statistics to precompute in dbt beyond averages (to be decided by the evaluation in Stage 5)

## Parked ideas

- **Load raw API data into a Postgres landing table and validate in SQL or dbt (ELT)**, instead of validating in Python before loading. Benefits: raw data is queryable and rules can be re-run without re-reading files. Costs: a redesign, and storing raw data twice. To be revisited after Stage 3.