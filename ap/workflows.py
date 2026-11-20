import hashlib
import logging
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from time import monotonic
from typing import TypedDict

from fastapi import HTTPException
from langgraph.graph import END, START, StateGraph
from langsmith import tracing_context
from psycopg.types.json import Jsonb

from .db import Actor, event, outbox, transaction, workflow
from .documents import context_vector, extract, inspect_file, read_object, store_object
from .policy import POLICY, RULES, Invoice, business_key, evaluate, required_role


class State(TypedDict):
    actor: Actor
    wid: str


PODS = {
    "Ingestion_Pod": "extract",
    "Validation_Pod": "match",
    "Database_Pod": "save",
    "API_Synthesis_Pod": "synthesize",
}


def dispatch(intent, wid):
    routes = {
        "review invoice": ["Ingestion_Pod", "Validation_Pod", "Database_Pod"],
        "create adapter": ["API_Synthesis_Pod"],
    }
    if intent not in routes:
        raise HTTPException(422, "Unsupported intent.")
    return {
        "workflow_id": str(wid),
        "steps": [
            {
                "step_sequence": i,
                "target_pod": pod,
                "action": PODS[pod],
                "payload": {"id": str(wid)},
            }
            for i, pod in enumerate(routes[intent], 1)
        ],
    }


def start(actor, filename, blob):
    actor.require("clerk")
    mime = inspect_file(blob)
    digest = hashlib.sha256(blob).hexdigest()
    with transaction(actor, serialize=True) as db:
        existing = db.execute(
            "SELECT w.id FROM workflow w JOIN document d ON (w.tenant,w.document_id)=(d.tenant,d.id) WHERE d.digest=%s",
            (digest,),
        ).fetchone()
        if existing:
            return str(existing["id"])
        doc, wid = uuid.uuid4(), uuid.uuid4()
        data, key = store_object(actor.tenant, blob, digest)
        db.execute(
            "INSERT INTO document(tenant,id,digest,filename,mime,ciphertext,object_key) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (actor.tenant, doc, digest, filename[:180], mime, data, key),
        )
        db.execute(
            "INSERT INTO workflow(tenant,id,document_id,stage) VALUES (%s,%s,%s,'received')",
            (actor.tenant, wid, doc),
        )
        event(db, actor, wid, "received", dispatch("review invoice", wid))
    return str(wid)


def ingest(state):
    actor, wid = state["actor"], state["wid"]
    with transaction(actor) as db:
        row = workflow(db, wid)
        if row["stage"] != "received":
            return {}
        blob, mime = read_object(db, actor, row["document_id"])
        filename = db.execute(
            "SELECT filename FROM document WHERE id=%s", (row["document_id"],)
        ).fetchone()["filename"]
        history = db.execute(
            """SELECT id::text,summary FROM workflow WHERE stage='queued' AND embedding IS NOT NULL
                             ORDER BY embedding <=> %s::vector LIMIT 3""",
            (context_vector(filename),),
        ).fetchall()
        aliases = {}
        for item in db.execute(
            "SELECT aliases FROM adapter WHERE status='released' ORDER BY created,id"
        ):
            aliases.update(item["aliases"])
    try:
        fields, refs, issues = extract(blob, mime, aliases, history)
    except Exception as exc:  # noqa: BLE001 -- isolate parser and model-provider failures at the pod boundary
        logging.getLogger(__name__).warning(
            "Extraction requires review (%s)", type(exc).__name__
        )
        fields, refs, issues = (
            {},
            {},
            ["Extraction unavailable. Inspect the original and enter its fields."],
        )
    with transaction(actor, serialize=True) as db:
        if workflow(db, wid)["stage"] == "received":
            db.execute(
                "UPDATE workflow SET stage='extracted',fields=%s,evidence=%s,issues=%s WHERE id=%s",
                (Jsonb(fields), Jsonb(refs), Jsonb(issues), wid),
            )
            event(
                db,
                actor,
                wid,
                "extracted",
                {
                    "fields": fields,
                    "evidence": refs,
                    "issues": issues,
                    "context_workflows": [r["id"] for r in history],
                },
            )
    return {}


def validate(state):
    actor, wid = state["actor"], state["wid"]
    with transaction(actor, serialize=True) as db:
        row = workflow(db, wid)
        if row["stage"] == "extracted":
            issues, matches = evaluate(db, row["fields"], wid)
            db.execute(
                "UPDATE workflow SET matches=%s, issues=%s, stage='validated' WHERE id=%s",
                (Jsonb(matches), Jsonb(row["issues"] + issues), wid),
            )
    return {}


def persist(state):
    actor, wid = state["actor"], state["wid"]
    with transaction(actor, serialize=True) as db:
        row = workflow(db, wid)
        if row["stage"] == "validated":
            finish_review(db, actor, wid, row["fields"], row["issues"], row["matches"])
    return {}


def finish_review(db, actor, wid, fields, issues, matches):
    summary = " ".join(str(fields.get(k, "")) for k in ("supplier", "number", "total"))
    stage = "review" if issues else "ready"
    db.execute(
        """UPDATE workflow SET stage=%s,summary=%s,embedding=%s::vector,issues=%s,matches=%s,
               updated=now() WHERE id=%s""",
        (stage, summary, context_vector(summary), Jsonb(issues), Jsonb(matches), wid),
    )
    event(
        db, actor, wid, stage, {"policy": POLICY, "issues": issues, "matches": matches}
    )


def measured(name, worker):
    def invoke(state):
        began = monotonic()
        result = worker(state)
        with transaction(state["actor"]) as db:
            db.execute(
                "INSERT INTO timing(tenant,workflow_id,pod,elapsed_ms) VALUES (%s,%s,%s,%s)",
                (
                    state["actor"].tenant,
                    state["wid"],
                    name,
                    round((monotonic() - began) * 1000),
                ),
            )
        return result

    return invoke


def engine():
    g = StateGraph(State)
    nodes = {
        "Ingestion_Pod": ingest,
        "Validation_Pod": validate,
        "Database_Pod": persist,
    }
    previous = START
    for step in dispatch("review invoice", "template")["steps"]:
        name = step["target_pod"]
        g.add_node(name, measured(name, nodes[name]))
        g.add_edge(previous, name)
        previous = name
    g.add_edge(previous, END)
    return g.compile()


GRAPH = engine()


def resume(actor, wid):
    actor.require("clerk")
    with tracing_context(enabled=False):
        GRAPH.invoke({"actor": actor, "wid": str(wid)}, config={"recursion_limit": 8})
    with transaction(actor) as db:
        return workflow(db, wid)


def check_version(row, version):
    if row["version"] != version:
        raise HTTPException(
            409, "The proposal changed. Refresh and inspect the latest version."
        )


def correct(actor, wid, version, fields, reason, page):
    actor.require("clerk")
    with transaction(actor, serialize=True) as db:
        row = workflow(db, wid)
        check_version(row, version)
        if row["stage"] in ("batch_finance", "batch_executive"):
            from .batches import invalidate

            invalidate(db, actor, row["batch_id"])
            row = workflow(db, wid)
            version = row["version"]
        if row["stage"] not in ("ready", "review", "pending", "executive"):
            raise HTTPException(409, "This workflow cannot be edited.")
        blob, mime = read_object(db, actor, row["document_id"])
        if mime == "application/pdf":
            import io

            from pypdf import PdfReader

            count = len(PdfReader(io.BytesIO(blob)).pages)
        else:
            count = 1
        if not 1 <= page <= count:
            raise HTTPException(422, "Evidence page outside document.")
        issues, matches = evaluate(db, fields, wid)
        refs = dict(row["evidence"])
        for key, val in fields.items():
            if key == "lines":
                previous_lines = row["fields"].get("lines", [])
                for i, line in enumerate(val):
                    path = f"lines.{i}"
                    if (
                        i >= len(previous_lines)
                        or line != previous_lines[i]
                        or path not in refs
                    ):
                        refs[path] = {
                            "page": page,
                            "quote": reason,
                            "reviewer": actor.user,
                        }
                for i in range(len(val), len(previous_lines)):
                    refs.pop(f"lines.{i}", None)
            elif row["fields"].get(key) != val or key not in refs:
                refs[key] = {"page": page, "quote": reason, "reviewer": actor.user}
        db.execute(
            "UPDATE workflow SET version=version+1,fields=%s,evidence=%s,expires=NULL WHERE id=%s",
            (Jsonb(fields), Jsonb(refs), wid),
        )
        event(
            db,
            actor,
            wid,
            "corrected",
            {
                "previous": row["fields"],
                "current": fields,
                "reason": reason,
                "page": page,
                "version": version + 1,
            },
        )
        finish_review(db, actor, wid, fields, issues, matches)
        return workflow(db, wid)


def submit(actor, wid, version):
    actor.require("clerk")
    with transaction(actor, serialize=True) as db:
        row = workflow(db, wid)
        check_version(row, version)
        if row["stage"] != "ready":
            raise HTTPException(409, "Review all exceptions before submission.")
        issues, matches = evaluate(db, row["fields"], wid)
        if issues:
            finish_review(db, actor, wid, row["fields"], issues, matches)
        else:
            role = required_role(Decimal(row["fields"]["total"]))
            ctrl = db.execute(
                "SELECT queue_enabled,mode_epoch FROM controls"
            ).fetchone()
            if not ctrl["queue_enabled"]:
                event(
                    db,
                    actor,
                    wid,
                    "shadow_reviewed",
                    {"version": version, "required_role": role},
                )
                return workflow(db, wid)
            stage = "executive" if role == "executive" else "pending"
            db.execute(
                "UPDATE workflow SET stage=%s,submission_epoch=%s,matches=%s,expires=now()+make_interval(hours => %s),updated=now() WHERE id=%s",
                (
                    stage,
                    ctrl["mode_epoch"],
                    Jsonb(matches),
                    RULES["approval_ttl_hours"],
                    wid,
                ),
            )
            event(
                db,
                actor,
                wid,
                "submitted",
                {"version": version, "required_role": role, "policy": POLICY},
            )
            if stage == "executive":
                outbox(db, actor, wid, version, "executive_review")
        return workflow(db, wid)


def approve(actor, wid, version):
    actor.require("finance", "executive")
    with transaction(actor, serialize=True) as db:
        row = workflow(db, wid)
        check_version(row, version)
        if row["stage"] == "queued":
            return workflow(db, wid)
        if row["stage"] not in ("pending", "executive"):
            raise HTTPException(409, "A submitted proposal is required.")
        data = Invoice.model_validate(row["fields"])
        if required_role(data.total) == "executive":
            actor.require("executive")
        if row["expires"] <= datetime.now(UTC):
            raise HTTPException(
                409, "Approval expired. Clerk must review and resubmit."
            )
        control = db.execute("SELECT queue_enabled,mode_epoch FROM controls").fetchone()
        if row["submission_epoch"] != control["mode_epoch"]:
            raise HTTPException(
                409, "Queue authority changed. Review and resubmit this proposal."
            )
        if not control["queue_enabled"]:
            raise HTTPException(409, "Shadow mode is active. Queue writes are paused.")
        issues, matches = evaluate(db, row["fields"], wid)
        if matches != row["matches"]:
            issues.append(
                "Receipt allocation changed after submission. Review the updated matches."
            )
        if issues:
            finish_review(db, actor, wid, row["fields"], issues, matches)
            return workflow(db, wid)
        commit_entry(db, actor, row, data, matches)
        return workflow(db, wid)


def commit_entry(db, actor, row, data, matches):
    wid, version = row["id"], row["version"]
    db.execute(
        "INSERT INTO queue(tenant,workflow_id,version,business_key,amount,approver,role) VALUES (%s,%s,%s,%s,%s,%s,%s)",
        (
            actor.tenant,
            wid,
            version,
            business_key(data),
            data.total,
            actor.user,
            actor.role,
        ),
    )
    for m in matches:
        db.execute(
            "INSERT INTO allocation VALUES (%s,%s,%s,%s,%s,%s)",
            (actor.tenant, wid, m["grn"], m["po"], m["sku"], m["qty"]),
        )
    db.execute(
        "UPDATE workflow SET stage='queued',matches=%s,updated=now() WHERE id=%s",
        (Jsonb(matches), wid),
    )
    event(
        db,
        actor,
        wid,
        "queued",
        {
            "version": version,
            "total": str(data.total),
            "role": actor.role,
            "policy": POLICY,
        },
    )
    outbox(db, actor, wid, version, "queue_created")


def dismiss(actor, wid, version, reason):
    actor.require("clerk")
    with transaction(actor, serialize=True) as db:
        row = workflow(db, wid)
        check_version(row, version)
        if row["stage"] in ("batch_finance", "batch_executive"):
            from .batches import invalidate

            invalidate(db, actor, row["batch_id"])
            row = workflow(db, wid)
            version = row["version"]
        if row["stage"] not in ("ready", "review", "pending", "executive"):
            raise HTTPException(409, "Only an open proposal can be dismissed.")
        db.execute(
            "UPDATE workflow SET stage='dismissed',version=version+1,updated=now() WHERE id=%s",
            (wid,),
        )
        event(db, actor, wid, "dismissed", {"reason": reason})
        return workflow(db, wid)
