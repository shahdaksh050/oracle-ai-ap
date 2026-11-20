import hashlib
import hmac
import json
import os
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path

import psycopg
from fastapi import HTTPException
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

ROOT = Path(__file__).resolve().parents[1]


def settings():
    path = Path(os.environ.get("AP_CONFIG", ROOT / ".runtime" / "app.json"))
    return json.loads(path.read_text(encoding="utf8"))


@dataclass(frozen=True)
class Actor:
    tenant: str
    user: str
    role: str

    def require(self, *roles):
        if self.role not in roles:
            raise HTTPException(403, "This account cannot perform that action.")


def authenticate(token):
    digest = hashlib.sha256(token.encode()).hexdigest()
    for account in settings()["accounts"]:
        if hmac.compare_digest(digest, account["digest"]):
            return Actor(account["tenant"], account["user"], account["role"])
    raise HTTPException(401, "Sign in with a valid workspace access key.")


@contextmanager
def transaction(actor, *, serialize=False):
    with psycopg.connect(settings()["dsn"], row_factory=dict_row) as db:
        db.execute("SET LOCAL search_path = ap, public")
        db.execute(
            "SELECT set_config('ap.tenant',%s,true), set_config('ap.role',%s,true)",
            (actor.tenant, actor.role),
        )
        if serialize:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (actor.tenant,)
            )
        yield db


def workflow(db, wid):
    row = db.execute(
        "SELECT id,document_id,batch_id,submission_epoch,stage,version,fields,evidence,issues,matches,summary,expires,created FROM workflow WHERE id=%s",
        (wid,),
    ).fetchone()
    if not row:
        raise HTTPException(404, "Workflow unavailable.")
    return row


def event(db, actor, wid, kind, details):
    db.execute(
        "INSERT INTO event(tenant,workflow_id,actor,kind,details) VALUES (%s,%s,%s,%s,%s)",
        (actor.tenant, wid, actor.user, kind, Jsonb(details)),
    )


def outbox(db, actor, wid, version, kind):
    db.execute(
        "INSERT INTO outbox(tenant,workflow_id,version,kind) VALUES (%s,%s,%s,%s) ON CONFLICT DO NOTHING",
        (actor.tenant, wid, version, kind),
    )
