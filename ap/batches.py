from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

from fastapi import HTTPException
from psycopg.types.json import Jsonb

from .db import event, outbox, transaction, workflow
from .policy import RULES, Invoice, evaluate, required_role
from .workflows import check_version, commit_entry


def submit_batch(actor, items):
    actor.require("clerk")
    if len({item.id for item in items}) != len(items):
        raise HTTPException(422, "Each invoice may appear once.")
    with transaction(actor, serialize=True) as db:
        ctrl = db.execute("SELECT queue_enabled,mode_epoch FROM controls").fetchone()
        if not ctrl["queue_enabled"]:
            raise HTTPException(409, "Batch submission requires an enabled queue.")
        snapshots = []
        total = Decimal(0)
        for item in items:
            row = workflow(db, item.id)
            check_version(row, item.version)
            issues, matches = evaluate(db, row["fields"], item.id)
            if row["stage"] != "ready" or issues or matches != row["matches"]:
                raise HTTPException(
                    409, "Every batch member must be ready and still match."
                )
            data = Invoice.model_validate(row["fields"])
            snapshots.append(
                {
                    "id": str(item.id),
                    "version": item.version,
                    "number": data.number,
                    "supplier": data.supplier,
                    "total": str(data.total),
                }
            )
            total += data.total
        bid = uuid4()
        stage = (
            "batch_executive"
            if required_role(total) == "executive"
            else "batch_finance"
        )
        db.execute(
            "INSERT INTO batch(tenant,id,status,amount,items,created_by,expires) VALUES (%s,%s,'pending',%s,%s,%s,now()+make_interval(hours => %s))",
            (
                actor.tenant,
                bid,
                total,
                Jsonb(snapshots),
                actor.user,
                RULES["approval_ttl_hours"],
            ),
        )
        for item in items:
            db.execute(
                "UPDATE workflow SET stage=%s,batch_id=%s,submission_epoch=%s,expires=now()+make_interval(hours => %s),updated=now() WHERE id=%s",
                (stage, bid, ctrl["mode_epoch"], RULES["approval_ttl_hours"], item.id),
            )
            event(
                db,
                actor,
                item.id,
                "batch_submitted",
                {
                    "batch": str(bid),
                    "total": str(total),
                    "version": item.version,
                    "stage": stage,
                },
            )
        if stage == "batch_executive":
            outbox(db, actor, items[0].id, items[0].version, "executive_review")
        return {
            "id": bid,
            "amount": str(total),
            "items": snapshots,
            "status": "pending",
        }


def invalidate(db, actor, bid):
    row = db.execute(
        "SELECT items FROM batch WHERE id=%s AND status='pending'", (bid,)
    ).fetchone()
    if not row:
        return
    db.execute("UPDATE batch SET status='invalidated' WHERE id=%s", (bid,))
    for item in row["items"]:
        db.execute(
            "UPDATE workflow SET stage='ready',version=version+1,expires=NULL,batch_id=NULL,updated=now() WHERE id=%s",
            (item["id"],),
        )
        event(db, actor, item["id"], "batch_invalidated", {"batch": str(bid)})


def approve_batch(actor, bid):
    actor.require("finance", "executive")
    with transaction(actor, serialize=True) as db:
        batch = db.execute("SELECT * FROM batch WHERE id=%s", (bid,)).fetchone()
        if not batch:
            raise HTTPException(404, "Batch unavailable.")
        if required_role(batch["amount"]) == "executive":
            actor.require("executive")
        if batch["status"] == "queued":
            return {"status": "queued", "id": bid}
        if batch["status"] != "pending" or batch["expires"] <= datetime.now(UTC):
            raise HTTPException(
                409, "Batch expired or changed. Review and submit a new batch."
            )
        ctrl = db.execute("SELECT queue_enabled,mode_epoch FROM controls").fetchone()
        if not ctrl["queue_enabled"]:
            raise HTTPException(409, "Shadow mode is active.")
        for item in batch["items"]:
            row = workflow(db, item["id"])
            check_version(row, item["version"])
            if (
                row["submission_epoch"] != ctrl["mode_epoch"]
                or row["batch_id"] != bid
                or row["stage"] not in ("batch_finance", "batch_executive")
            ):
                raise HTTPException(409, "Batch membership changed.")
            issues, matches = evaluate(db, row["fields"], row["id"])
            if matches != row["matches"]:
                issues.append("Receipt allocation changed after batch submission")
            if issues:
                raise HTTPException(409, "Batch requires review: " + "; ".join(issues))
            commit_entry(db, actor, row, Invoice.model_validate(row["fields"]), matches)
        db.execute(
            "UPDATE batch SET status='queued',approved_by=%s WHERE id=%s",
            (actor.user, bid),
        )
        return {"status": "queued", "id": bid}
