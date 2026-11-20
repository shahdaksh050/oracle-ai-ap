import logging
from typing import Annotated, Literal
from uuid import UUID

import httpx
from cryptography.fernet import Fernet, InvalidToken
from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
from fastapi.staticfiles import StaticFiles
from pydantic import Field

from . import adapters, batches, workflows
from .db import ROOT, Actor, authenticate, settings, transaction, workflow
from .documents import (
    LIMIT,
    context_vector,
    model_json,
    read_object,
    resolve_model_config,
)
from .policy import CAP, POLICY, RULES, Invoice, Strict

app = FastAPI(title="Enterprise Oracle · Accounts Payable", version="0.1.0")


class SignIn(Strict):
    token: str = Field(min_length=16, max_length=256)


class Version(Strict):
    version: int = Field(ge=1)


class Correction(Version):
    fields: Invoice
    reason: str = Field(min_length=3, max_length=500)
    page: int = Field(ge=1, le=12)


class Dismiss(Version):
    reason: str = Field(min_length=3, max_length=500)


class AdapterInput(Strict):
    aliases: dict[str, str]


class SecurityAuditInput(Strict):
    code: str = Field(min_length=1, max_length=10000)
    sql: str | None = Field(default=None, max_length=5000)
    aliases: dict[str, str] = Field(default_factory=dict)


@app.middleware("http")
async def protect(request, call_next):
    if (
        request.method not in ("GET", "HEAD", "OPTIONS")
        and request.headers.get("sec-fetch-site") == "cross-site"
    ):
        return Response(status_code=403)
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    if request.url.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


def identity(request: Request):
    header = request.headers.get("authorization", "")
    if header.startswith("Bearer "):
        return authenticate(header[7:])
    try:
        token = (
            Fernet(settings()["key"])
            .decrypt(request.cookies.get("ap_session", "").encode(), ttl=8 * 3600)
            .decode()
        )
    except (InvalidToken, ValueError):
        raise HTTPException(401, "Sign in to your workspace.")
    return authenticate(token)


User = Annotated[Actor, Depends(identity)]


@app.post("/api/session")
def login(body: SignIn, response: Response):
    actor = authenticate(body.token)
    cfg = settings()
    cookie = Fernet(cfg["key"]).encrypt(body.token.encode()).decode()
    response.set_cookie(
        "ap_session",
        cookie,
        max_age=8 * 3600,
        httponly=True,
        samesite="strict",
        secure=cfg.get("environment") != "synthetic",
    )
    return actor


@app.delete("/api/session")
def logout(response: Response):
    response.delete_cookie("ap_session")
    return {"signed_out": True}


@app.get("/api/me")
def me(actor: User):
    with transaction(actor) as db:
        mode = db.execute("SELECT queue_enabled FROM controls").fetchone()
    return {
        "tenant": actor.tenant,
        "user": actor.user,
        "role": actor.role,
        "queue_enabled": bool(mode and mode["queue_enabled"]),
    }


@app.get("/api/workflows")
def inbox(actor: User):
    with transaction(actor) as db:
        return db.execute("""SELECT w.id,stage,version,fields->>'number' number,fields->>'supplier' supplier,
            fields->>'total' amount,filename,created FROM workflow w JOIN document d ON (w.tenant,w.document_id)=(d.tenant,d.id)
            ORDER BY created DESC""").fetchall()


@app.post("/api/workflows", status_code=201)
def upload(actor: User, file: Annotated[UploadFile, File()]):
    actor.require("clerk")
    wid = workflows.start(actor, file.filename or "document", file.file.read(LIMIT + 1))
    return workflows.resume(actor, wid)


@app.get("/api/workflows/{wid}")
def details(wid: UUID, actor: User):
    with transaction(actor) as db:
        row = workflow(db, wid)
        row["events"] = db.execute(
            "SELECT kind,actor,details,created FROM event WHERE workflow_id=%s ORDER BY id",
            (wid,),
        ).fetchall()
        if row["batch_id"]:
            row["batch"] = db.execute(
                "SELECT id,amount,amount::text AS amount_exact,status,items FROM batch WHERE id=%s",
                (row["batch_id"],),
            ).fetchone()
        row["components"] = ["source", "fields", "matches", "history"]
        return row


@app.get("/api/workflows/{wid}/source")
def source(wid: UUID, actor: User):
    with transaction(actor) as db:
        row = workflow(db, wid)
        blob, mime = read_object(db, actor, row["document_id"])
    return Response(
        blob,
        media_type=mime,
        headers={
            "Content-Disposition": "inline",
            "Content-Security-Policy": "sandbox; default-src 'none'",
        },
    )


@app.post("/api/workflows/{wid}/resume")
def resume(wid: UUID, actor: User):
    return workflows.resume(actor, wid)


@app.put("/api/workflows/{wid}/fields")
def correct(wid: UUID, body: Correction, actor: User):
    return workflows.correct(
        actor,
        wid,
        body.version,
        body.fields.model_dump(mode="json"),
        body.reason.strip(),
        body.page,
    )


@app.post("/api/workflows/{wid}/submit")
def submit(wid: UUID, body: Version, actor: User):
    return workflows.submit(actor, wid, body.version)


@app.post("/api/workflows/{wid}/approve")
def approve(wid: UUID, body: Version, actor: User):
    return workflows.approve(actor, wid, body.version)


@app.post("/api/workflows/{wid}/dismiss")
def dismiss(wid: UUID, body: Dismiss, actor: User):
    return workflows.dismiss(actor, wid, body.version, body.reason)


class Member(Version):
    id: UUID


class BatchInput(Strict):
    items: list[Member] = Field(min_length=2, max_length=50)


@app.post("/api/batches")
def batch_submit(body: BatchInput, actor: User):
    return batches.submit_batch(actor, body.items)


@app.post("/api/batches/{bid}/approve")
def batch_approve(bid: UUID, actor: User):
    return batches.approve_batch(actor, bid)


@app.get("/api/queue")
def queue(actor: User):
    with transaction(actor) as db:
        return db.execute(
            "SELECT workflow_id,version,business_key,amount,amount::text AS amount_exact,approver,role,created FROM queue ORDER BY created DESC"
        ).fetchall()


@app.get("/api/context")
def context(actor: User, q: str = Query(min_length=1, max_length=200)):
    with transaction(actor) as db:
        return db.execute(
            """SELECT id,summary,stage FROM workflow WHERE embedding IS NOT NULL
                           ORDER BY embedding <=> %s::vector LIMIT 8""",
            (context_vector(q),),
        ).fetchall()


class ViewChoice(Strict):
    component: Literal["queue", "operations", "invoices", "security", "context"]
    filter: Literal["all", "approvals", "review"] = "all"


@app.get("/api/view")
def view(actor: User, q: str = Query(max_length=200)):
    if resolve_model_config():
        try:
            spec = ViewChoice.model_validate(
                model_json(
                    [
                        {
                            "role": "system",
                            "content": "Choose a workspace view. Return only JSON matching "
                            + str(ViewChoice.model_json_schema()),
                        },
                        {"role": "user", "content": q},
                    ]
                )
            )
            return {**spec.model_dump(), "query": q}
        except (httpx.HTTPError, ValueError, KeyError, IndexError, TypeError) as exc:
            logging.getLogger(__name__).info(
                "View inference unavailable (%s)", type(exc).__name__
            )
    words = q.lower().split()
    if any(
        w in words
        for w in ("security", "guardrail", "ast", "sandbox", "firewall", "interceptor")
    ):
        return {"component": "security"}
    if any(w in words for w in ("queue", "payments", "queued", "paid")):
        return {"component": "queue"}
    if any(
        w in words for w in ("metrics", "telemetry", "health", "ops", "performance")
    ):
        return {"component": "operations"}
    if any(
        w in words for w in ("exceptions", "disputed", "review", "rejected", "flags")
    ):
        return {"component": "invoices", "filter": "review"}
    if any(w in words for w in ("approvals", "pending", "awaiting")):
        return {"component": "invoices", "filter": "approvals"}
    return {"component": "context", "query": q}


@app.get("/api/security/specs")
def security_specs(actor: User):
    return {
        "policy_version": POLICY,
        "executive_above_inr": str(CAP),
        "sandbox_seconds": RULES["sandbox_wall_seconds"],
        "sandbox_memory_mib": RULES["sandbox_memory_mib"],
        "rules": RULES,
        "stages": [
            {
                "stage": 1,
                "name": "Static AST & SQL Parsing",
                "status": "enforced",
                "rules": [
                    "Pure dictionary projection AST allowlist",
                    "Keyword blacklist: blocks os.system, subprocess, sys.modules, eval, socket",
                    "SQL struct checking: restricts queries strictly to single tenant-scoped vendor lookup",
                ],
            },
            {
                "stage": 2,
                "name": "Virtual Container Sandbox",
                "status": "configured",
                "rules": [
                    "Ephemeral micro-VM isolation via runsc (gVisor)",
                    f"3-second execution budget ({RULES['sandbox_wall_seconds']}s ceiling)",
                    f"128 MB RAM ceiling ({RULES['sandbox_memory_mib']}m)",
                    "Network isolation: --network=none",
                    "Read-only root filesystem with dropped privileges",
                ],
            },
            {
                "stage": 3,
                "name": "Deterministic Enterprise Rules",
                "status": "enforced",
                "rules": [
                    f"Financial movements > ₹{CAP:,.2f} freeze autonomy for Executive approval",
                    "Driver-level tenant and role injection via set_config",
                    "PostgreSQL FORCE ROW LEVEL SECURITY (RLS) on all domain tables",
                    "Paise-exact arithmetic using Decimal with ROUND_HALF_UP",
                ],
            },
        ],
    }


@app.post("/api/security/audit")
def security_audit(body: SecurityAuditInput, actor: User):
    ast_result = adapters.audit(body.code, body.aliases)
    sql_result = adapters.inspect_sql(body.sql) if body.sql else True
    return {
        "status": "APPROVED"
        if (ast_result["status"] == "APPROVED" and sql_result)
        else "REJECTED",
        "ast_audit": ast_result,
        "sql_check": {
            "supplied": body.sql,
            "approved": sql_result,
            "anomaly": None
            if sql_result
            else "SQL statement violates tenant-scoped read shape",
        },
    }


@app.get("/api/operations")
def operations(actor: User):
    with transaction(actor) as db:
        stages = db.execute(
            "SELECT stage,count(*) count FROM workflow GROUP BY stage ORDER BY stage"
        ).fetchall()
        backlog = db.execute(
            "SELECT count(*) pending,coalesce(sum(attempts),0) failures FROM outbox WHERE delivered IS NULL"
        ).fetchone()
        metrics = db.execute("""SELECT count(*) invoices,coalesce(max(extract(epoch FROM now()-created)) FILTER
          (WHERE stage NOT IN ('queued','dismissed')),0) oldest_open_seconds FROM workflow""").fetchone()
        timings = db.execute("""SELECT pod,count(*) runs,round(percentile_cont(0.95) WITHIN GROUP (ORDER BY elapsed_ms)) p95_ms
                             FROM timing GROUP BY pod ORDER BY pod""").fetchall()
        return {
            "timings": timings,
            "stages": stages,
            "notifications": backlog,
            **metrics,
        }


@app.post("/api/adapters")
def stage(body: AdapterInput, actor: User):
    return adapters.stage(actor, body.aliases)


@app.get("/api/adapters")
def adapters_list(actor: User):
    with transaction(actor) as db:
        return db.execute(
            "SELECT id,aliases,status,created_by,released_by,report FROM adapter ORDER BY created DESC"
        ).fetchall()


@app.post("/api/adapters/{aid}/release")
def release(aid: UUID, actor: User):
    return adapters.release(actor, aid)


if (ROOT / "web/dist").is_dir():
    app.mount("/", StaticFiles(directory=ROOT / "web/dist", html=True), name="frontend")
