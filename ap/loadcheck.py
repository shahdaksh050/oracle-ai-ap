"""Measure shadow ingestion at twice a supplied baseline, using distinct synthetic invoices."""

import argparse
import concurrent.futures
import io
import json
import math
import os
import time
import uuid
from collections import Counter

from .db import authenticate, settings, transaction
from .sample import fields, write_sample
from .workflows import resume, start


def run(peak_per_minute, seconds, parallel):
    actor = authenticate(os.environ["AP_EVAL_KEY"])
    actor.require("clerk")
    if settings().get("environment") != "synthetic":
        raise ValueError(
            "Use an isolated synthetic configuration for the capacity rehearsal"
        )
    with transaction(actor) as db:
        if db.execute("SELECT queue_enabled FROM controls").fetchone()["queue_enabled"]:
            raise ValueError("Capacity runs require a shadow tenant")

    def process(_):
        began = time.monotonic()
        stream = io.BytesIO()
        write_sample(stream, fields(uuid.uuid4().hex[:15], "1"))
        wid = start(actor, "load-invoice.pdf", stream.getvalue())
        row = resume(actor, wid)
        return row["stage"] == "ready", time.monotonic() - began

    target = 2 * peak_per_minute
    count = max(1, math.ceil(target * seconds / 60))
    started = time.monotonic()
    pending = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as pool:
        for i in range(count):
            time.sleep(max(0, started + i * 60 / target - time.monotonic()))
            pending.append(pool.submit(process, i))
    latencies = []
    successes = 0
    errors = Counter()
    for f in pending:
        try:
            ok, elapsed = f.result()
            successes += int(ok)
            latencies.append(elapsed)
        except Exception as exc:  # noqa: BLE001 -- record each failed independent workload
            errors[type(exc).__name__] += 1
    elapsed = max(time.monotonic() - started, 0.001)
    return {
        "target_per_minute": target,
        "scheduled_seconds": seconds,
        "elapsed_seconds": round(elapsed, 2),
        "requested": count,
        "ready": successes,
        "failed": count - successes,
        "error_types": dict(errors),
        "workers": parallel,
        "p95_seconds": round(sorted(latencies)[math.ceil(0.95 * len(latencies)) - 1], 3)
        if latencies
        else None,
    }


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--peak-per-minute", type=float, required=True)
    p.add_argument("--seconds", type=int, default=3600)
    p.add_argument("--workers", type=int, default=4)
    a = p.parse_args()
    if min(a.peak_per_minute, a.seconds, a.workers) <= 0:
        p.error("All limits must be positive")
    print(json.dumps(run(a.peak_per_minute, a.seconds, a.workers), indent=2))
