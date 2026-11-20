"""Run tenant-scoped outbox delivery and periodic workflow maintenance."""

import argparse
import json
import logging
import time

from .db import settings
from .maintenance import optimize, recover
from .notifications import deliver


def run_once(tenant, maintenance=True):
    result = {"tenant": tenant, "delivered": 0}
    for _ in range(20):
        notification = deliver(tenant)
        result["notification_status"] = notification["status"]
        result["delivered"] += notification["delivered"]
        if notification["status"] != "processed":
            break
    if maintenance:
        result["recovery"] = recover(tenant)
        result["optimization"] = optimize(tenant)["status"]
    return result


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--tenant", required=True)
    parser.add_argument("--once", action="store_true")
    args = parser.parse_args()
    if args.tenant not in {account["tenant"] for account in settings()["accounts"]}:
        parser.error("Unknown configured tenant")
    next_maintenance = 0
    while True:
        now = time.monotonic()
        maintenance = now >= next_maintenance
        try:
            print(json.dumps(run_once(args.tenant, maintenance)), flush=True)
        except Exception as exc:
            if args.once:
                raise
            logging.getLogger(__name__).error(
                "Worker cycle failed (%s)", type(exc).__name__
            )
        if args.once:
            return
        if maintenance:
            next_maintenance = now + 300
        time.sleep(15)


if __name__ == "__main__":
    main()
