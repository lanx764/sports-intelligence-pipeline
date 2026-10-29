"""
basketball_daily

Daily pipeline for the Basketball Intelligence System:

    fetch_daily  ->  load_games  ->  run_checks  ->  notify_success

Each of the first three tasks runs one of the project's scripts as a command
inside the Airflow container, from /opt/airflow/project (the mounted project
folder). A script's exit code decides the task's result: 0 = success,
anything else = failed.

Dates (all UTC):
    A run triggered at 06:00 UTC on day D fetches D-1 (the target day) and
    D-2 (the day before, re-fetched to pick up late API corrections), then
    loads both days and runs the checks.

    The date comes from dag_run.run_after, which every run has. logical_date
    (and so {{ ds }}) is not used, because a manually triggered run in
    Airflow 3 can have no logical date.

Slack (channel #pipeline-alerts, webhook URL in SLACK_WEBHOOK_URL):
    - A task that fails for good (after its retries) posts a red message.
      Tasks that did not run because an earlier task failed post nothing.
    - notify_success runs only when everything before it succeeded and posts
      a green message. No green message by about 08:00 Lagos time means the
      run needs a look.

Old gaps are filled by backfill.py, not by this DAG.
"""

import logging
import os
from datetime import date, timedelta, timezone

import pendulum
from slack_alert import SlackAlertError, send_slack

from airflow.providers.standard.operators.bash import BashOperator
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

log = logging.getLogger(__name__)

PROJECT_DIR = "/opt/airflow/project"

TARGET_DATE = "{{ macros.ds_add(dag_run.run_after | ds, -1) }}"
PREVIOUS_DATE = "{{ macros.ds_add(dag_run.run_after | ds, -2) }}"

# What to try first for each task that can fail.
FAILURE_HINTS = {
    "fetch_daily": (
        "Usually the API quota (resets at 00:00 UTC) or the network. "
        "load_games and run_checks did not run."
    ),
    "load_games": "Read the traceback in the log. run_checks did not run.",
    "run_checks": "The games were loaded, but a check failed. Look for ERROR lines in the log.",
    "notify_success": "The pipeline itself finished. Only the success message failed to send.",
}

SUMMARY_SQL = """
SELECT
    (SELECT COUNT(*) FROM basketball.fact_games WHERE match_date = %(day)s),
    (SELECT COUNT(*) FROM basketball.quarantine_games WHERE status = 'open')
"""

DB_ENV_NAMES = ("DB_HOST", "DB_PORT", "DB_NAME", "DB_USER", "DB_PASSWORD")


# ---------------------------------------------------------------------------
# Slack messages
# ---------------------------------------------------------------------------
def failure_message(task_id, attempts, day, error, log_url):
    """Build the red message for a task that failed after all its attempts."""
    plural = "attempt" if attempts == 1 else "attempts"
    return "\n".join(
        [
            "\U0001f534 basketball_daily failed",
            f"Task: {task_id} (failed after {attempts} {plural})",
            f"Day: {day}",
            f"Error: {error}",
            f"Log: {log_url}",
            f"Next: {FAILURE_HINTS.get(task_id, 'Open the log.')}",
        ]
    )


def success_message(day, games_on_day, open_quarantine):
    """Build the green message for a run where every task succeeded."""
    lines = [
        "\U0001f7e2 basketball_daily finished",
        f"Day: {day}",
        f"Games in fact_games for that day: {games_on_day}",
        f"Open quarantine rows (all days): {open_quarantine}",
    ]
    if games_on_day == 0:
        lines.append("\u26a0\ufe0f No games for that day. Check that the fetch returned data.")
    return "\n".join(lines)


def alert_task_failed(context):
    """
    on_failure_callback for every task. Airflow calls it only when a task
    has failed for good, so a failed attempt that will be retried sends
    nothing. If Slack cannot be reached it logs the problem and does not
    raise, because Airflow ignores an error raised from a callback anyway.
    """
    ti = context["ti"]
    run_after = context["dag_run"].run_after.astimezone(timezone.utc)
    day = (run_after - timedelta(days=1)).date()

    text = failure_message(
        task_id=ti.task_id,
        attempts=ti.try_number,
        day=day,
        error=context.get("exception") or "no error message",
        log_url=ti.log_url,
    )
    try:
        send_slack(text)
    except SlackAlertError as err:
        log.error("could not send the failure alert to Slack: %s", err)


def notify_success(target_date):
    """Read two counts from the database and post the green message."""
    import psycopg  # imported here so a DAG parse never depends on it

    missing = [name for name in DB_ENV_NAMES if not os.getenv(name)]
    if missing:
        raise RuntimeError(f"missing environment variables: {', '.join(missing)}")

    day = date.fromisoformat(target_date)
    with psycopg.connect(
        host=os.getenv("DB_HOST"),
        port=int(os.getenv("DB_PORT")),
        dbname=os.getenv("DB_NAME"),
        user=os.getenv("DB_USER"),
        password=os.getenv("DB_PASSWORD"),
    ) as conn:
        games_on_day, open_quarantine = conn.execute(SUMMARY_SQL, {"day": day}).fetchone()

    send_slack(success_message(day, games_on_day, open_quarantine))


# ---------------------------------------------------------------------------
# The DAG
# ---------------------------------------------------------------------------
with DAG(
    dag_id="basketball_daily",
    description="Fetch, load and check one UTC day of Highlightly basketball matches",
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 10, 26, tz="UTC"),
    catchup=True,
    max_active_runs=1,
    default_args={"on_failure_callback": alert_task_failed},
    tags=["basketball", "highlightly"],
    doc_md=__doc__,
) as dag:
    fetch_daily = BashOperator(
        task_id="fetch_daily",
        bash_command='python fetch_daily.py "$TARGET_DATE"',
        env={"TARGET_DATE": TARGET_DATE},
        append_env=True,
        cwd=PROJECT_DIR,
        skip_on_exit_code=None,
        retries=2,
        retry_delay=timedelta(minutes=10),
    )

    load_games = BashOperator(
        task_id="load_games",
        bash_command='python load_games.py "$PREVIOUS_DATE" && python load_games.py "$TARGET_DATE"',
        env={"TARGET_DATE": TARGET_DATE, "PREVIOUS_DATE": PREVIOUS_DATE},
        append_env=True,
        cwd=PROJECT_DIR,
        skip_on_exit_code=None,
        retries=0,
    )

    run_checks = BashOperator(
        task_id="run_checks",
        bash_command="python run_checks.py",
        cwd=PROJECT_DIR,
        skip_on_exit_code=None,
        retries=0,
    )

    notify_success_task = PythonOperator(
        task_id="notify_success",
        python_callable=notify_success,
        op_kwargs={"target_date": TARGET_DATE},
        retries=2,
        retry_delay=timedelta(minutes=2),
    )

    fetch_daily >> load_games >> run_checks >> notify_success_task  