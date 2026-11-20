"""Every test suite run uses a fresh database in the synthetic local cluster."""

import hashlib
import json
import secrets
import uuid
from types import SimpleNamespace

import psycopg
import pytest
from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from psycopg import sql
from psycopg.conninfo import make_conninfo

from ap.admin import BUYER, VENDOR, cluster, dsn, migrate
from ap.api import app
from ap.db import Actor
from ap.sample import fields, write_sample


@pytest.fixture(scope="session")
def database(tmp_path_factory):
    cfg = cluster()
    root = dsn(cfg, "postgres")
    # Create the restricted cluster role on a fresh checkout before creating test schemas.
    dbname = "ap_test_" + uuid.uuid4().hex
    with psycopg.connect(root, autocommit=True) as db:
        db.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(dbname)))
    admin = make_conninfo(root, dbname=dbname)
    runtime = make_conninfo(dsn(cfg, "ap_runtime"), dbname=dbname)
    try:
        migrate(admin, cfg["runtime"])
        yield admin, runtime
    finally:
        with psycopg.connect(root, autocommit=True) as db:
            db.execute(sql.SQL("DROP DATABASE {}").format(sql.Identifier(dbname)))


@pytest.fixture
def pilot(database, tmp_path, monkeypatch):
    admin, runtime = database
    tenant = "test_" + uuid.uuid4().hex[:12]
    foreign = "second_" + tenant
    keys = {}
    accounts = []
    for org in (tenant, foreign):
        with psycopg.connect(admin) as db:
            db.execute(
                "INSERT INTO ap.controls VALUES (%s,%s,true,%s)", (org, BUYER, [VENDOR])
            )
            db.execute("INSERT INTO ap.vendor VALUES (%s,%s,'Demo')", (org, VENDOR))
            db.execute(
                "INSERT INTO ap.po_line VALUES (%s,'PO-410','BR-20',%s,10000,100,18,'8482')",
                (org, VENDOR),
            )
            db.execute(
                "INSERT INTO ap.receipt VALUES (%s,'GR-230','PO-410','BR-20',8000)",
                (org,),
            )
        for role in ("clerk", "finance", "executive", "qa"):
            token = secrets.token_urlsafe(28)
            accounts.append(
                {
                    "tenant": org,
                    "role": role,
                    "user": org + role,
                    "digest": hashlib.sha256(token.encode()).hexdigest(),
                }
            )
            keys[org, role] = {"Authorization": "Bearer " + token}
    cfg = tmp_path / "config.json"
    cfg.write_text(
        json.dumps(
            {
                "dsn": runtime,
                "key": Fernet.generate_key().decode(),
                "accounts": accounts,
                "environment": "synthetic",
            }
        )
    )
    monkeypatch.setenv("AP_CONFIG", str(cfg))
    client = TestClient(app)

    def request(method, path, role="clerk", other=False, **kwargs):
        return client.request(
            method,
            "/api" + path,
            headers=keys[(foreign if other else tenant), role],
            **kwargs,
        )

    def upload(data=None):
        doc = tmp_path / "invoice.pdf"
        write_sample(doc, data or fields())
        return request(
            "POST",
            "/workflows",
            files={"file": ("bill.pdf", doc.read_bytes(), "application/pdf")},
        ).json()

    return SimpleNamespace(
        request=request,
        upload=upload,
        tenant=tenant,
        foreign=foreign,
        admin=admin,
        cfg=cfg,
        actor=Actor(tenant, tenant + "clerk", "clerk"),
        tmp=tmp_path,
        client=client,
    )
