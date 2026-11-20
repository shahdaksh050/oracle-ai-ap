"""Generate a narrow supplier adapter and qualify it using synthetic data only."""

import ast
import json
import re
import subprocess
import uuid

from fastapi import HTTPException
from psycopg.types.json import Jsonb
from sqlglot import exp, parse
from sqlglot.errors import SqlglotError

from .db import settings, transaction
from .documents import model_json, resolve_model_config
from .policy import RULES, Invoice
from .workflows import dispatch

VENDOR_LOOKUP = "SELECT name FROM vendor WHERE tenant = :tenant AND gstin = :gstin"


def inspect_sql(query):
    """Generated SQL has one supported shape: tenant-scoped vendor lookup."""
    try:
        statements = parse(query, read="postgres")
        expected = parse(
            VENDOR_LOOKUP,
            read="postgres",
        )[0]
        return (
            len(statements) == 1
            and isinstance(statements[0], exp.Select)
            and statements[0] == expected
        )
    except (SqlglotError, TypeError, ValueError, RecursionError):
        return False


def canonical(aliases):
    return (
        "def adapt(row):\n    return {"
        + ", ".join(
            f"{key!r}: row[{label!r}]" for label, key in sorted(aliases.items())
        )
        + "}\n"
    )


def audit(code, aliases):
    anomalies = []
    try:
        # An exact allowlisted tree admits only a pure projection from synthetic row keys.
        if ast.dump(ast.parse(code)) != ast.dump(ast.parse(canonical(aliases))):
            anomalies.append("Adapter exceeds the approved projection grammar")
    except (SyntaxError, ValueError, TypeError):
        anomalies.append("Invalid Python")
    return {
        "status": "REJECTED" if anomalies else "APPROVED",
        "risk_score": 1.0 if anomalies else 0.0,
        "detected_anomalies": anomalies,
        "refactored_code": canonical(aliases) if anomalies else None,
    }


def sandbox(code, aliases):
    cfg = settings()
    image = cfg.get("sandbox_image", "")
    if not re.fullmatch(r"[a-zA-Z0-9./:_-]+@sha256:[0-9a-f]{64}", image):
        return (
            False,
            "Configure an approved digest-pinned Python image on the gVisor runner",
        )
    fixture = {key: f"sample-{i}" for i, key in enumerate(aliases)}
    expected = {v: fixture[k] for k, v in aliases.items()}
    seconds = RULES["sandbox_wall_seconds"]
    memory = f"{RULES['sandbox_memory_mib']}m"
    script = (
        f"import signal\nsignal.alarm({seconds})\n"
        + code
        + f"\nassert adapt({fixture!r}) == {expected!r}\n"
    )
    name = "ap-stage-" + uuid.uuid4().hex
    # No host directories, network, database keys, or client samples enter the container.
    try:
        create = subprocess.run(
            [
                "docker",
                "create",
                "--pull=never",
                "--name",
                name,
                "--runtime=runsc",
                "--network=none",
                "--read-only",
                "--user=65534:65534",
                "--cap-drop=ALL",
                "--security-opt=no-new-privileges",
                "--pids-limit=16",
                "--memory=" + memory,
                "--memory-swap=" + memory,
                "--cpus=1",
                image,
                "python",
                "-I",
                "-B",
                "-c",
                script,
            ],
            check=False,
            capture_output=True,
            timeout=15,
        )
        if create.returncode:
            return False, "Isolated runner unavailable"
        result = subprocess.run(
            ["docker", "start", "-a", name],
            check=False,
            capture_output=True,
            timeout=seconds,
        )
        state = subprocess.run(
            [
                "docker",
                "inspect",
                "--format",
                "{{.State.Status}} {{.State.ExitCode}} {{.State.OOMKilled}}",
                name,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return (
            (True, "Fixture passed in runsc")
            if result.returncode == state.returncode == 0
            and state.stdout.strip() == "exited 0 false"
            else (False, "Sandbox fixture failed")
        )
    except (OSError, subprocess.TimeoutExpired):
        return False, "Isolated runner unavailable or execution exceeded three seconds"
    finally:
        try:
            subprocess.run(
                ["docker", "rm", "-f", name],
                timeout=10,
                check=False,
                capture_output=True,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def valid_label(label):
    return bool(re.fullmatch(r"[a-z][a-z0-9 _-]{0,49}", label)) and label not in {
        *Invoice.model_fields,
        "line",
    }


def stage(actor, aliases):
    actor.require("clerk", "qa")
    if not 1 <= len(aliases) <= 24 or len(set(aliases.values())) != len(aliases):
        raise HTTPException(422, "Use unique canonical fields.")
    reserved = set(Invoice.model_fields) | {"line"}
    for label, key in aliases.items():
        if (
            not valid_label(label)
            or key not in reserved - {"lines"}
            or label in reserved
        ):
            raise HTTPException(422, "Invalid supplier label or target field.")
    aid = uuid.uuid4()
    plan = dispatch("create adapter", aid)
    code = canonical(aliases)
    lookup = VENDOR_LOOKUP
    if resolve_model_config():
        result = model_json(
            [
                {
                    "role": "user",
                    "content": "Return JSON with code defining only def adapt(row) that returns these output fields from the corresponding input labels: "
                    + json.dumps(aliases),
                }
            ]
        )
        code = result.get("code", "")
        lookup = result.get("vendor_lookup", VENDOR_LOOKUP)
    report = audit(code, aliases)
    attempts = [report["status"]]
    for _ in range(2):
        if report["status"] == "APPROVED":
            break
        code = report["refactored_code"]
        report = audit(code, aliases)
        attempts.append(report["status"])
    if not inspect_sql(lookup):
        report.update(
            status="REJECTED",
            risk_score=1.0,
            detected_anomalies=["Vendor lookup exceeds tenant-scoped read policy"],
        )
    passed, message = (
        sandbox(code, aliases)
        if report["status"] == "APPROVED"
        else (False, "Static review failed")
    )
    status = "staged" if passed else "blocked"
    report.update(sandbox=message, attempts=attempts, plan=plan)
    with transaction(actor) as db:
        db.execute(
            "INSERT INTO adapter(tenant,id,aliases,code,report,status,created_by) VALUES (%s,%s,%s,%s,%s,%s,%s)",
            (
                actor.tenant,
                aid,
                Jsonb(aliases),
                code,
                Jsonb(report),
                status,
                actor.user,
            ),
        )
    return {"id": aid, "status": status, "report": report}


def release(actor, aid):
    actor.require("qa")
    with transaction(actor, serialize=True) as db:
        row = db.execute("SELECT * FROM adapter WHERE id=%s", (aid,)).fetchone()
        if not row:
            raise HTTPException(404, "Adapter unavailable.")
        if row["status"] != "staged" or row["created_by"] == actor.user:
            raise HTTPException(
                409, "Independent QA and a passed sandbox fixture are required."
            )
        existing = db.execute(
            "SELECT aliases FROM adapter WHERE status='released'"
        ).fetchall()
        if any(
            k in item["aliases"] and item["aliases"][k] != v
            for k, v in row["aliases"].items()
            for item in existing
        ):
            raise HTTPException(409, "Active adapters map this label differently.")
        db.execute(
            "UPDATE adapter SET status='released',released_by=%s WHERE id=%s",
            (actor.user, aid),
        )
    return {"status": "released"}
