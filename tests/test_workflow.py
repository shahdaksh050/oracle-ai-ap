import io
from concurrent.futures import ThreadPoolExecutor

import psycopg
import pytest
from PIL import Image

from ap import workflows
from ap.adapters import audit, inspect_sql
from ap.admin import import_csv
from ap.db import transaction
from ap.sample import fields, write_sample


def posted(p, row, op, role="clerk"):
    return p.request(
        "POST", f"/workflows/{row['id']}/{op}", role, json={"version": row["version"]}
    )


def test_replay_crash_and_simultaneous_approval(pilot, monkeypatch):
    p = pilot
    row = p.upload()
    assert row["stage"] == "ready" and row["evidence"]["lines.0"]["page"] == 1
    assert p.upload()["id"] == row["id"]
    assert posted(p, row, "submit").json()["stage"] == "pending"
    original = workflows.outbox

    def crash(*args):
        raise RuntimeError("worker lost before commit")

    monkeypatch.setattr(workflows, "outbox", crash)
    with pytest.raises(RuntimeError):
        posted(p, row, "approve", "finance")
    assert p.request("GET", "/queue").json() == []
    monkeypatch.setattr(workflows, "outbox", original)
    with ThreadPoolExecutor(4) as pool:
        responses = list(
            pool.map(lambda _: posted(p, row, "approve", "finance"), range(4))
        )
    assert all(r.json()["stage"] == "queued" for r in responses)
    # Lost acknowledgement: retry after the first transaction already committed.
    assert posted(p, row, "approve", "finance").json()["stage"] == "queued"
    assert len(p.request("GET", "/queue").json()) == 1
    with transaction(p.actor) as db:
        assert (
            db.execute("SELECT count(*) n FROM event WHERE kind='queued'").fetchone()[
                "n"
            ]
            == 1
        )
        assert db.execute("SELECT count(*) n FROM outbox").fetchone()["n"] == 1
        assert db.execute("SELECT sum(qty) n FROM allocation").fetchone()["n"] == 10


@pytest.mark.parametrize(
    ("price", "stage"),
    [("499999.99", "pending"), ("500000.00", "pending"), ("500000.01", "executive")],
)
def test_authority_boundaries(pilot, price, stage):
    p = pilot
    with psycopg.connect(p.admin) as db:
        db.execute(
            "UPDATE ap.po_line SET price=%s,gst_rate=0 WHERE tenant=%s",
            (price, p.tenant),
        )
    raw = fields(qty="1")
    raw.update(taxable=price, cgst="0", sgst="0", total=price)
    raw["lines"][0].update(unit_price=price, gst_rate="0")
    row = p.upload(raw)
    assert posted(p, row, "submit").json()["stage"] == stage
    assert posted(p, row, "approve", "clerk").status_code == 403
    if stage == "executive":
        assert posted(p, row, "approve", "finance").status_code == 403
    assert (
        posted(
            p, row, "approve", "executive" if stage == "executive" else "finance"
        ).json()["stage"]
        == "queued"
    )


def test_shadow_expiry_and_version(pilot):
    p = pilot
    row = p.upload()
    posted(p, row, "submit")
    with psycopg.connect(p.admin) as db:
        db.execute(
            "UPDATE ap.controls SET queue_enabled=false WHERE tenant=%s", (p.tenant,)
        )
    assert posted(p, row, "approve", "finance").status_code == 409
    with psycopg.connect(p.admin) as db:
        db.execute(
            "UPDATE ap.controls SET queue_enabled=true WHERE tenant=%s", (p.tenant,)
        )
        db.execute(
            "UPDATE ap.workflow SET expires=now()-interval '1 hour' WHERE id=%s",
            (row["id"],),
        )
    assert posted(p, row, "approve", "finance").status_code == 409
    correction = {
        "fields": fields(qty="2"),
        "page": 1,
        "reason": "Verified source quantity",
        "version": 1,
    }
    new = p.request("PUT", f"/workflows/{row['id']}/fields", json=correction).json()
    assert new["version"] == 2 and new["stage"] == "ready"
    assert posted(p, row, "approve", "finance").status_code == 409
    assert posted(p, new, "submit").json()["stage"] == "pending"
    assert posted(p, new, "approve", "finance").json()["stage"] == "queued"


def test_isolation_auth_and_raw_access(pilot):
    p = pilot
    row = p.upload()
    wid = row["id"]
    for path in ("/workflows/" + wid, "/workflows/" + wid + "/source"):
        assert p.request("GET", path, other=True).status_code == 404
    for path in ("/workflows", "/queue", "/context?q=DC-1042", "/adapters"):
        assert p.request("GET", path, other=True).json() == []
    assert p.request("POST", f"/workflows/{wid}/resume", other=True).status_code == 404
    assert p.request("GET", "/operations", other=True).json()["invoices"] == 0
    assert p.client.get("/api/workflows").status_code == 401
    assert (
        p.request(
            "POST", f"/workflows/{wid}/submit", json={"version": 1, "tenant": p.foreign}
        ).status_code
        == 422
    )
    with transaction(p.actor) as db:
        role = db.execute(
            "SELECT rolsuper,rolbypassrls FROM pg_roles WHERE rolname=current_user"
        ).fetchone()
        assert not any(role.values())
        assert not db.execute(
            "SELECT * FROM controls WHERE tenant=%s", (p.foreign,)
        ).fetchall()
        assert not db.execute(
            "SELECT * FROM document WHERE tenant=%s", (p.foreign,)
        ).fetchall()
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            db.execute("UPDATE controls SET queue_enabled=true")


def test_partial_receipts_duplicate_and_live_recheck(pilot):
    p = pilot
    first = p.upload(fields("FIRST", "7500"))
    second = p.upload(fields("SECOND", "1000"))
    assert posted(p, first, "submit").json()["stage"] == "executive"
    assert posted(p, second, "submit").json()["stage"] == "pending"
    assert posted(p, first, "approve", "executive").json()["stage"] == "queued"
    blocked = posted(p, second, "approve", "finance").json()
    assert blocked["stage"] == "review" and any(
        "receipt" in i for i in blocked["issues"]
    )
    duplicate = p.upload(fields("FIRST", "1"))
    assert (
        duplicate["stage"] == "review"
        and "Invoice already queued" in duplicate["issues"]
    )


def test_workflow_checkpoint_resumption(pilot):
    p = pilot
    path = p.tmp / "resume.pdf"
    write_sample(path)
    wid = workflows.start(p.actor, "resume.pdf", path.read_bytes())
    workflows.ingest({"actor": p.actor, "wid": wid})
    assert p.request("GET", "/workflows/" + wid).json()["stage"] == "extracted"
    assert p.request("POST", "/workflows/" + wid + "/resume").json()["stage"] == "ready"
    assert p.request("POST", "/workflows/" + wid + "/resume").json()["stage"] == "ready"
    kinds = [r["kind"] for r in p.request("GET", "/workflows/" + wid).json()["events"]]
    assert kinds == ["received", "extracted", "ready"]


def test_image_exception_and_policy(pilot):
    p = pilot
    buf = io.BytesIO()
    Image.new("RGB", (120, 80), "white").save(buf, "PNG")
    row = p.request(
        "POST",
        "/workflows",
        files={"file": ("source.png", buf.getvalue(), "image/png")},
    ).json()
    assert row["stage"] == "review"
    assert p.request("GET", f"/workflows/{row['id']}/source").content == buf.getvalue()
    assert posted(p, row, "submit").status_code == 409
    raw = fields()
    raw["igst"] = "5"
    fixed = p.request(
        "PUT",
        f"/workflows/{row['id']}/fields",
        json={"version": 1, "page": 1, "fields": raw, "reason": "Manual transcription"},
    ).json()
    assert any("Tax components" in issue for issue in fixed["issues"])
    assert (
        p.request(
            "POST", "/workflows", files={"file": ("x", "invalid", "text/plain")}
        ).status_code
        == 422
    )


def test_adapter_qualification_and_isolated_failure(pilot):
    p = pilot
    aliases = {"bill no": "number"}
    report = audit("def adapt(row):\n    return 1", aliases)
    assert (
        report["status"] == "REJECTED"
        and audit(report["refactored_code"], aliases)["status"] == "APPROVED"
    )
    assert not inspect_sql("DELETE FROM vendor")
    assert inspect_sql(
        "SELECT name FROM vendor WHERE tenant = :tenant AND gstin = :gstin"
    )
    result = p.request("POST", "/adapters", json={"aliases": aliases}).json()
    assert result["status"] == "blocked" and result["report"]["attempts"] == [
        "APPROVED"
    ]
    assert (
        p.request("POST", f"/adapters/{result['id']}/release", "qa").status_code == 409
    )
    assert p.request("GET", "/adapters", other=True).json() == []


def test_csv_import_idempotency(pilot):
    p = pilot
    raw = "kind,grn,po,sku,qty\nreceipt,GR-extra,PO-410,BR-20,12\n"
    with psycopg.connect(p.admin) as db:
        for _ in range(2):
            import_csv(db, p.tenant, io.StringIO(raw))
        with pytest.raises(ValueError):
            import_csv(db, p.tenant, io.StringIO(raw.replace(",12", ",99")))
    with transaction(p.actor) as db:
        assert (
            db.execute("SELECT qty FROM receipt WHERE grn='GR-extra'").fetchone()["qty"]
            == 12
        )
