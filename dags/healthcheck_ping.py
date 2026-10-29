"""
healthcheck_ping.py

Tells Healthchecks.io that the daily pipeline finished successfully. This is
the "dead man's switch": Healthchecks.io expects one ping a day (06:00 UTC
plus a grace time) and posts to Slack itself when the ping does not arrive.
That covers the case where Airflow never ran, which Airflow cannot report.

The ping URL is read from the HEALTHCHECK_PING_URL environment variable (in
.env, loaded into the Airflow containers by docker-compose). The URL is a
secret: anyone who has it can send "all fine" pings. This file never logs or
prints it.

Can also be run by hand to test the ping (inside a container):
    python /opt/airflow/dags/healthcheck_ping.py
"""

import logging
import os
import sys
import urllib.error
import urllib.request

PING_URL_ENV = "HEALTHCHECK_PING_URL"
TIMEOUT_SECONDS = 10

log = logging.getLogger("healthcheck_ping")


class HealthcheckError(Exception):
    """The ping could not be delivered to Healthchecks.io."""


def ping_healthcheck():
    """Send one success ping. Raises HealthcheckError if it was not delivered."""
    url = os.getenv(PING_URL_ENV)
    if not url:
        raise HealthcheckError(f"{PING_URL_ENV} is not set")

    request = urllib.request.Request(
        url,
        headers={"User-Agent": "basketball-pipeline"},
        method="GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            status = response.status
    except urllib.error.HTTPError as err:
        raise HealthcheckError(f"Healthchecks.io returned HTTP {err.code}") from None
    except urllib.error.URLError as err:
        raise HealthcheckError(f"could not reach Healthchecks.io: {err.reason}") from None
    except TimeoutError:
        raise HealthcheckError(
            f"no reply from Healthchecks.io within {TIMEOUT_SECONDS} seconds"
        ) from None

    if status != 200:
        raise HealthcheckError(f"unexpected HTTP status from Healthchecks.io: {status}")


def main():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    try:
        ping_healthcheck()
    except HealthcheckError as err:
        log.error("healthcheck ping failed: %s", err)
        return 1

    log.info("healthcheck ping sent")
    return 0


if __name__ == "__main__":
    sys.exit(main())