"""
slack_alert.py

Sends a message to the #pipeline-alerts Slack channel through an Incoming
Webhook. The webhook URL is read from the SLACK_WEBHOOK_URL environment
variable (it lives in .env, and docker-compose loads .env into every Airflow
container). The URL is a secret: this file never logs or prints it.

Used by the basketball_daily DAG for the failure and success alerts.
Can also be run by hand to test the webhook (inside a container):
    python /opt/airflow/dags/slack_alert.py "test message"
"""

import json
import logging
import os
import sys
import urllib.error
import urllib.request

WEBHOOK_ENV = "SLACK_WEBHOOK_URL"
TIMEOUT_SECONDS = 10

log = logging.getLogger("slack_alert")


class SlackAlertError(Exception):
    """The message could not be delivered to Slack."""


def send_slack(text):
    """Post one message to Slack. Raises SlackAlertError if it was not delivered."""
    url = os.getenv(WEBHOOK_ENV)
    if not url:
        raise SlackAlertError(f"{WEBHOOK_ENV} is not set")

    body = json.dumps({"text": text}).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            reply = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as err:
        detail = err.read().decode("utf-8", errors="replace")
        raise SlackAlertError(f"Slack returned HTTP {err.code}: {detail}") from None
    except urllib.error.URLError as err:
        raise SlackAlertError(f"could not reach Slack: {err.reason}") from None
    except TimeoutError:
        raise SlackAlertError(f"no reply from Slack within {TIMEOUT_SECONDS} seconds") from None

    if reply != "ok":
        raise SlackAlertError(f"unexpected reply from Slack: {reply!r}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    if len(sys.argv) != 2:
        log.error('usage: python slack_alert.py "message"')
        return 1

    try:
        send_slack(sys.argv[1])
    except SlackAlertError as err:
        log.error("slack alert failed: %s", err)
        return 1

    log.info("slack alert sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())