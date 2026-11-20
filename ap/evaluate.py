"""Score pre-correction results against independent finance labels in a shadow tenant."""

import argparse
import json
import os
import statistics
from collections import Counter, defaultdict
from decimal import Decimal, InvalidOperation
from pathlib import Path

from .db import authenticate, transaction
from .policy import Invoice
from .workflows import resume, start

CRITICAL = (
    "number",
    "date",
    "supplier",
    "buyer",
    "taxable",
    "cgst",
    "sgst",
    "igst",
    "total",
    "lines",
)
MONEY = {"taxable", "cgst", "sgst", "igst", "total", "qty", "unit_price", "gst_rate"}


def normalize(field, value):
    if field in MONEY:
        try:
            return Decimal(str(value)).normalize()
        except InvalidOperation:
            return None
    if field == "lines" and isinstance(value, list):
        return [
            dict(sorted((k, normalize(k, v)) for k, v in row.items())) for row in value
        ]
    return value


def collect(actor, manifest):
    actor.require("clerk")
    records = json.loads(manifest.read_text(encoding="utf8"))
    if not records:
        raise ValueError("Empty dataset")
    with transaction(actor) as db:
        if db.execute("SELECT queue_enabled FROM controls").fetchone()["queue_enabled"]:
            raise ValueError("An evaluation requires a dedicated shadow tenant")
        if db.execute("SELECT 1 FROM workflow LIMIT 1").fetchone():
            raise ValueError(
                "Use a fresh evaluation tenant to keep pre-correction evidence independent"
            )
    counts = defaultdict(Counter)
    totals = Counter()
    discrepancies = []
    comparisons = []
    documents = set()
    base = manifest.resolve().parent
    # Validate labels before making the first workflow.
    for row in records:
        path = (base / row["file"]).resolve()
        if not path.is_relative_to(base) or not path.is_file():
            raise ValueError("Missing dataset file or path outside the dataset")
        Invoice.model_validate(row["expected"])
        if (
            type(row["ready"]) is not bool
            or not isinstance(row["receipts"], list)
            or not row.get("format")
        ):
            raise ValueError(
                "Provide format, expected readiness, and receipt allocations for each record"
            )
    for index, row in enumerate(records, 1):
        path = base / row["file"]
        wid = start(actor, path.name, path.read_bytes())
        if wid in documents:
            raise ValueError("Duplicate file bytes in held-out dataset")
        documents.add(wid)
        result = resume(actor, wid)
        correct = {}
        for field in CRITICAL:
            correct[field] = normalize(field, result["fields"].get(field)) == normalize(
                field, row["expected"][field]
            )
        group = counts[row["format"]]
        group["documents"] += 1
        for field, ok in correct.items():
            group[field] += int(ok)
        ready = result["stage"] == "ready"
        totals["review"] += int(not ready)
        totals["ready"] += int(ready)
        if ready:

            def allocations(lines):
                return sorted(
                    (r["grn"], r["po"], r["sku"], Decimal(str(r["qty"]))) for r in lines
                )

            if not (
                row["ready"]
                and all(correct[k] for k in ("supplier", "total"))
                and allocations(result["matches"]) == allocations(row["receipts"])
            ):
                discrepancies.append(index)
        if "baseline_minutes" in row and "pilot_minutes" in row:
            comparisons.append((row["baseline_minutes"], row["pilot_minutes"]))
    n = len(records)
    scores = {
        fmt: {field: round(count[field] / count["documents"], 5) for field in CRITICAL}
        for fmt, count in counts.items()
    }
    rates = {field: sum(g[field] for g in counts.values()) / n for field in CRITICAL}
    handling = None
    if len(comparisons) == n:
        base_median = statistics.median(x for x, y in comparisons)
        if base_median > 0:
            handling = 1 - statistics.median(y for x, y in comparisons) / base_median
    coverage = {tag for row in records for tag in row.get("scenarios", [])}
    required = {"clean", "poor_scan", "duplicate", "partial_receipt", "tax_exception"}
    return {
        "missing_scenarios": sorted(required - coverage),
        "documents": n,
        "per_format": scores,
        "per_field": rates,
        "review_rate": totals["review"] / n,
        "ready": totals["ready"],
        "incorrect_ready_rows": discrepancies,
        "median_handling_reduction": handling,
        "accuracy_gate": required <= coverage
        and n >= 200
        and min(rates.values()) >= 0.98
        and totals["ready"] > 0
        and not discrepancies,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("manifest", type=Path)
    args = parser.parse_args()
    print(
        json.dumps(
            collect(authenticate(os.environ["AP_EVAL_KEY"]), args.manifest), indent=2
        )
    )
