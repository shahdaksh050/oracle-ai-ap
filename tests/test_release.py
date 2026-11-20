import json
import os
import subprocess
import uuid

import httpx
import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo

from ap.admin import binary
from ap.db import transaction
from ap.notifications import deliver
from ap.sample import fields


def submit(p, row):
    return p.request(
        "POST", f"/workflows/{row['id']}/submit", json={"version": row["version"]}
    )


def test_batch_aggregation_and_edit_invalidation(pilot):
    p = pilot
    rows = [p.upload(fields(n, "2500")) for n in ["A", "B"]]
    items = [{"id": r["id"], "version": r["version"]} for r in rows]
    batch = p.request("POST", "/batches", json={"items": items}).json()
    assert float(batch["amount"]) == 590000
    url = f"/batches/{batch['id']}/approve"
    assert p.request("POST", url, "finance").status_code == 403
    assert (
        p.request(
            "POST",
            f"/workflows/{rows[0]['id']}/approve",
            "finance",
            json={"version": 1},
        ).status_code
        == 409
    )
    result = p.request(
        "PUT",
        f"/workflows/{rows[0]['id']}/fields",
        json={
            "version": 1,
            "reason": "Changed quantity",
            "page": 1,
            "fields": fields("A", "2000"),
        },
    )
    assert result.json()["stage"] == "ready"
    assert p.request("POST", url, "executive").status_code == 409
    items = [
        {
            "id": r["id"],
            "version": p.request("GET", "/workflows/" + r["id"]).json()["version"],
        }
        for r in rows
    ]
    batch = p.request("POST", "/batches", json={"items": items}).json()
    assert (
        p.request("POST", f"/batches/{batch['id']}/approve", "executive").json()[
            "status"
        ]
        == "queued"
    )
    assert len(p.request("GET", "/queue").json()) == 2


def test_entire_batch_rolls_back_if_receipts_run_out(pilot):
    p = pilot
    rows = [p.upload(fields(n, "5000")) for n in ["A", "B"]]
    batch = p.request(
        "POST",
        "/batches",
        json={"items": [{"id": r["id"], "version": 1} for r in rows]},
    ).json()
    assert (
        p.request("POST", f"/batches/{batch['id']}/approve", "executive").status_code
        == 409
    )
    assert p.request("GET", "/queue").json() == []


def test_notification_outage(pilot, monkeypatch):
    p = pilot
    row = p.upload(fields("EXEC", "5000"))
    assert submit(p, row).json()["stage"] == "executive"
    cfg = json.loads(p.cfg.read_text())
    cfg.update(
        public_origin="https://test.invalid",
        slack_webhooks={p.tenant: "https://hooks.slack.com/services/test"},
    )
    p.cfg.write_text(json.dumps(cfg))

    def outage(self, url, **kwargs):
        raise httpx.ConnectError("simulated offline")

    monkeypatch.setattr(httpx.Client, "post", outage)
    assert deliver(p.tenant)["status"] == "retry_scheduled"
    assert deliver(p.tenant)["status"] == "idle"
    with transaction(p.actor) as db:
        assert db.execute("SELECT attempts FROM outbox").fetchone()["attempts"] == 1
    assert p.request("GET", "/queue").json() == []


def test_dump_restore_and_shadow_rollback(pilot):
    p = pilot
    row = p.upload()
    submit(p, row)
    p.request(
        "POST", f"/workflows/{row['id']}/approve", "finance", json={"version": 1}
    ).raise_for_status()
    cfg = conninfo_to_dict(p.admin)
    backup = p.tmp / "snapshot.dump"
    env = {**os.environ, "PGPASSWORD": cfg["password"]}
    flags = ["-h", cfg["host"], "-p", cfg["port"], "-U", cfg["user"]]
    subprocess.run(
        [binary("pg_dump"), *flags, "-Fc", "-f", str(backup), cfg["dbname"]],
        env=env,
        check=True,
    )
    restored = "ap_restore_" + uuid.uuid4().hex
    with psycopg.connect(p.admin, autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(restored)))
    try:
        subprocess.run(
            [
                binary("pg_restore"),
                *flags,
                "--exit-on-error",
                "-d",
                restored,
                str(backup),
            ],
            env=env,
            check=True,
        )
        with psycopg.connect(make_conninfo(p.admin, dbname=restored)) as db:
            assert (
                db.execute(
                    "SELECT amount FROM ap.queue WHERE tenant=%s", (p.tenant,)
                ).fetchone()[0]
                == 1180
            )
            assert (
                db.execute(
                    "SELECT count(*) FROM ap.event WHERE tenant=%s AND kind='queued'",
                    (p.tenant,),
                ).fetchone()[0]
                == 1
            )
            assert (
                db.execute(
                    "SELECT qty FROM ap.allocation WHERE tenant=%s", (p.tenant,)
                ).fetchone()[0]
                == 10
            )
            assert db.execute(
                "SELECT extname FROM pg_extension WHERE extname='vector'"
            ).fetchone()
    finally:
        with psycopg.connect(p.admin, autocommit=True) as db:
            db.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(restored)))
    with psycopg.connect(p.admin) as db:
        db.execute(
            "UPDATE ap.controls SET queue_enabled=false WHERE tenant=%s", (p.tenant,)
        )
    another = p.upload(fields("NEXT"))
    submit(p, another)
    assert (
        p.request(
            "POST",
            f"/workflows/{another['id']}/approve",
            "finance",
            json={"version": 1},
        ).status_code
        == 409
    )
    assert len(p.request("GET", "/queue").json()) == 1
