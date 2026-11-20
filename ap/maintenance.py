"""Recover stalled AP work and stage recurring supplier-format improvements for QA."""

from collections import defaultdict
from io import BytesIO

from pypdf import PdfReader

from . import adapters, workflows
from .db import Actor, event, transaction
from .documents import read_object


def recover(tenant):
    actor = Actor(tenant, "workflow-recovery", "clerk")
    with transaction(actor, serialize=True) as db:
        row = db.execute("""SELECT w.id FROM workflow w WHERE stage IN ('received','extracted','validated')
            AND updated < now()-interval '5 minutes' AND NOT EXISTS
            (SELECT 1 FROM event e WHERE e.workflow_id=w.id AND e.kind='recovery_attempt'
             AND e.created>now()-interval '5 minutes') ORDER BY w.created LIMIT 1""").fetchone()
        if not row:
            return "idle"
        wid = row["id"]
        attempts = db.execute(
            "SELECT count(*) n FROM event WHERE workflow_id=%s AND kind='recovery_attempt'",
            (wid,),
        ).fetchone()["n"]
        if attempts >= 2:
            db.execute(
                """UPDATE workflow SET stage='review',issues='["Automatic recovery exhausted. Inspect the original."]'::jsonb,
                        updated=now() WHERE id=%s""",
                (wid,),
            )
            event(db, actor, wid, "recovery_exhausted", {})
            return "review"
        event(db, actor, wid, "recovery_attempt", {"attempt": attempts + 1})
    return workflows.resume(actor, wid)["stage"]


def optimize(tenant):
    # Use human-verified corrections from distinct approved documents to avoid repeated model/manual extraction.
    actor = Actor(tenant, "format-telemetrist", "clerk")
    observed = defaultdict(lambda: defaultdict(set))
    with transaction(actor) as db:
        existing = {
            key
            for row in db.execute("SELECT aliases FROM adapter")
            for key in row["aliases"]
        }
        rows = db.execute("""SELECT w.id,w.document_id,w.fields,e.details->'fields' original
            FROM workflow w JOIN event e ON e.workflow_id=w.id AND e.tenant=w.tenant
            WHERE w.stage='queued' AND e.kind='extracted' AND EXISTS
            (SELECT 1 FROM event c WHERE c.workflow_id=w.id AND c.kind='corrected')
            ORDER BY w.updated DESC LIMIT 40""").fetchall()
        for row in rows:
            blob, mime = read_object(db, actor, row["document_id"])
            if mime != "application/pdf":
                continue
            for page in PdfReader(BytesIO(blob)).pages:
                for text in (page.extract_text() or "").splitlines():
                    name, sep, value = text.partition(":")
                    name = name.strip().lower()
                    if not sep or name in existing or not adapters.valid_label(name):
                        continue
                    candidates = [
                        k
                        for k, v in row["fields"].items()
                        if k != "lines"
                        and k not in row["original"]
                        and str(v) == value.strip()
                    ]
                    if len(candidates) == 1:
                        observed[name][candidates[0]].add(row["id"])
    for name, targets in sorted(observed.items()):
        if len(targets) == 1:
            key, ids = next(iter(targets.items()))
            if len(ids) >= 2:
                candidate = adapters.stage(actor, {name: key})
                return {
                    "candidate": str(candidate["id"]),
                    "status": candidate["status"],
                    "supporting_invoices": len(ids),
                }
    return {"status": "no_candidate"}
