import sys

import psycopg
import pytest

from ap import admin, workflows
from ap.maintenance import optimize, recover
from ap.sample import fields, write_sample


def test_recovery_and_format_optimization(pilot):
    p = pilot
    sample = p.tmp / "stalled.pdf"
    write_sample(sample, fields("STALLED"))
    wid = workflows.start(p.actor, "stalled.pdf", sample.read_bytes())
    with psycopg.connect(p.admin) as db:
        db.execute(
            "UPDATE ap.workflow SET updated=now()-interval '10 minutes' WHERE id=%s",
            (wid,),
        )
    assert recover(p.tenant) == "ready"
    assert recover(p.tenant) == "idle"
    for number in ("FORMAT-001", "FORMAT-002"):
        data = fields(number)
        source = dict(data)
        source["bill no"] = source.pop("number")
        row = p.upload(source)
        assert row["stage"] == "review"
        url = "/workflows/" + row["id"]
        edited = p.request(
            "PUT",
            url + "/fields",
            json={
                "version": 1,
                "fields": data,
                "reason": "Read bill number from page one",
                "page": 1,
            },
        ).json()
        assert edited["stage"] == "ready"
        assert (
            p.request("POST", url + "/submit", json={"version": 2}).json()["stage"]
            == "pending"
        )
        assert (
            p.request("POST", url + "/approve", "finance", json={"version": 2}).json()[
                "stage"
            ]
            == "queued"
        )
    result = optimize(p.tenant)
    assert result["status"] == "blocked" and result["supporting_invoices"] == 2
    assert optimize(p.tenant)["status"] == "no_candidate"


def test_reconciliation_drift_freezes_queue(pilot, monkeypatch):
    p = pilot
    file = p.tmp / "finance-ledger.csv"
    file.write_text("business_key,amount\nexpected-reference,10.00\n")
    monkeypatch.setenv("AP_ADMIN_DSN", p.admin)
    monkeypatch.setattr(
        sys, "argv", ["admin", "reconcile", "--tenant", p.tenant, "--file", str(file)]
    )
    with pytest.raises(SystemExit) as stop:
        admin.main()
    assert stop.value.code == 1
    assert not p.request("GET", "/me").json()["queue_enabled"]
