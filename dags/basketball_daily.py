"""
basketball_daily

Daily pipeline for the Basketball Intelligence System:

    fetch_daily  ->  load_games  ->  run_checks

Each task runs one of the project's scripts as a command inside the Airflow
container, from /opt/airflow/project (the mounted project folder). A script's
exit code decides the task's result: 0 = success, anything else = failed.

Dates (all UTC):
    A run triggered at 06:00 UTC on day D fetches D-1 (the target day) and
    D-2 (the day before, re-fetched to pick up late API corrections), then
    loads both days and runs the checks.

    The date comes from dag_run.run_after, which every run has. logical_date
    (and so {{ ds }}) is not used, because a manually triggered run in
    Airflow 3 can have no logical date.

Old gaps are filled by backfill.py, not by this DAG.
"""

from datetime import timedelta

import pendulum

from airflow.providers.standard.operators.bash import BashOperator
from airflow.sdk import DAG

PROJECT_DIR = "/opt/airflow/project"

TARGET_DATE = "{{ macros.ds_add(dag_run.run_after | ds, -1) }}"
PREVIOUS_DATE = "{{ macros.ds_add(dag_run.run_after | ds, -2) }}"

with DAG(
    dag_id="basketball_daily",
    description="Fetch, load and check one UTC day of Highlightly basketball matches",
    schedule="0 6 * * *",
    start_date=pendulum.datetime(2026, 10, 26, tz="UTC"),
    catchup=True,
    max_active_runs=1,
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

    fetch_daily >> load_games >> run_checks