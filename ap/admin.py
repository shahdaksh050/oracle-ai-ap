"""Workspace-local synthetic database, migration, and operator commands."""

import argparse
import csv
import hashlib
import json
import os
import secrets
import subprocess
import tempfile
from decimal import Decimal
from pathlib import Path

import psycopg
from cryptography.fernet import Fernet
from psycopg import sql
from psycopg.conninfo import make_conninfo

from .db import ROOT

HOME = ROOT / ".runtime"
DATA = HOME / "pgdata"
TENANTS = ("saffron", "indigo")
BUYER = "27AAACB1234A1Z5"
VENDOR = "27AAACV1234A1Z2"


def binary(name):
    import pgserver

    directory = Path(pgserver.__file__).parent / "pginstall" / "bin"
    return str(directory / (name + (".exe" if os.name == "nt" else "")))


def save(path, content):
    path.write_text(json.dumps(content, indent=2), encoding="utf8")


def cluster():
    HOME.mkdir(exist_ok=True)
    path = HOME / "local-admin.json"
    if not path.exists():
        save(
            path,
            {
                "password": secrets.token_urlsafe(32),
                "runtime": secrets.token_urlsafe(32),
                "port": 55439,
            },
        )
    cfg = json.loads(path.read_text())
    if not (DATA / "PG_VERSION").exists():
        with tempfile.NamedTemporaryFile(mode="w", dir=HOME, delete=False) as tmp:
            tmp.write(cfg["password"] + "\n")
        try:
            subprocess.run(
                [
                    binary("initdb"),
                    "-D",
                    str(DATA),
                    "-U",
                    "postgres",
                    "-A",
                    "scram-sha-256",
                    "--encoding=UTF8",
                    "--locale=C",
                    "--pwfile",
                    tmp.name,
                ],
                check=True,
            )
        finally:
            Path(tmp.name).unlink(missing_ok=True)
    args = [binary("pg_ctl"), "-D", str(DATA)]
    if subprocess.run([*args, "status"], check=False, capture_output=True).returncode:
        subprocess.run(
            [
                *args,
                "start",
                "-w",
                "-l",
                str(HOME / "postgres.log"),
                "-o",
                f"-h 127.0.0.1 -p {cfg['port']}",
            ],
            check=True,
        )
    return cfg


def dsn(cfg, user):
    return make_conninfo(
        host="127.0.0.1",
        port=cfg["port"],
        dbname="postgres",
        user=user,
        password=cfg["password" if user == "postgres" else "runtime"],
    )


def migrate(admin_dsn, password):
    with psycopg.connect(admin_dsn) as db:
        db.execute("SELECT pg_advisory_xact_lock(173941)")
        if not db.execute(
            "SELECT 1 FROM pg_roles WHERE rolname='ap_runtime'"
        ).fetchone():
            db.execute(
                sql.SQL(
                    "CREATE ROLE ap_runtime LOGIN NOSUPERUSER NOBYPASSRLS PASSWORD {}"
                ).format(sql.Literal(password))
            )
        db.execute(
            "CREATE TABLE IF NOT EXISTS public.ap_migrations(name text PRIMARY KEY,digest text NOT NULL)"
        )
        for path in sorted((ROOT / "migrations").glob("*.sql")):
            script = path.read_text(encoding="utf8")
            digest = hashlib.sha256(script.encode()).hexdigest()
            row = db.execute(
                "SELECT digest FROM public.ap_migrations WHERE name=%s", (path.name,)
            ).fetchone()
            if row and row[0] != digest:
                raise RuntimeError(f"Applied migration changed: {path.name}")
            if not row:
                db.execute(script)
                db.execute(
                    "INSERT INTO public.ap_migrations VALUES (%s,%s)",
                    (path.name, digest),
                )


def initialize():
    cfg = cluster()
    migrate(dsn(cfg, "postgres"), cfg["runtime"])
    with psycopg.connect(dsn(cfg, "postgres")) as db:
        for tenant in TENANTS:
            db.execute(
                "INSERT INTO ap.controls VALUES (%s,%s,true,%s) ON CONFLICT DO NOTHING",
                (tenant, BUYER, [VENDOR]),
            )
            db.execute(
                "INSERT INTO ap.vendor VALUES (%s,%s,%s) ON CONFLICT DO NOTHING",
                (
                    tenant,
                    VENDOR,
                    "Deccan Components" if tenant == "saffron" else "Indigo Industrial",
                ),
            )
            db.execute(
                "INSERT INTO ap.po_line VALUES (%s,'PO-410','BR-20',%s,10000,100,18,'8482') ON CONFLICT DO NOTHING",
                (tenant, VENDOR),
            )
            db.execute(
                "INSERT INTO ap.receipt VALUES (%s,'GR-230','PO-410','BR-20',8000) ON CONFLICT DO NOTHING",
                (tenant,),
            )
    if not (HOME / "app.json").exists():
        keys, accounts = {}, []
        for tenant in TENANTS:
            for role in ("clerk", "finance", "executive", "qa"):
                user = f"{tenant}-{role}"
                token = secrets.token_urlsafe(32)
                keys[user] = token
                accounts.append(
                    {
                        "user": user,
                        "tenant": tenant,
                        "role": role,
                        "digest": hashlib.sha256(token.encode()).hexdigest(),
                    }
                )
        save(HOME / "demo-keys.json", keys)
        save(
            HOME / "app.json",
            {
                "dsn": dsn(cfg, "ap_runtime"),
                "key": Fernet.generate_key().decode(),
                "accounts": accounts,
                "environment": "synthetic",
                "policy": "domestic-po-v1",
            },
        )
    print("Synthetic tenants ready. Local sign-in keys are in .runtime/demo-keys.json.")


def import_csv(db, tenant, stream):
    # Relational import is atomic. Conflicting master records require explicit reconciliation.
    specs = {
        "vendor": ("vendor", ("gstin", "name")),
        "order": (
            "po_line",
            ("po", "sku", "gstin", "ordered", "price", "gst_rate", "hsn"),
        ),
        "receipt": ("receipt", ("grn", "po", "sku", "qty")),
    }
    for record in csv.DictReader(stream):
        table, columns = specs[record["kind"]]
        values = [record[c].strip() for c in columns]
        stmt = sql.SQL(
            "INSERT INTO ap.{} ({}) VALUES ({}) ON CONFLICT DO NOTHING RETURNING 1"
        ).format(
            sql.Identifier(table),
            sql.SQL(",").join(map(sql.Identifier, ("tenant", *columns))),
            sql.SQL(",").join(sql.Placeholder() for _ in range(len(columns) + 1)),
        )
        if not db.execute(stmt, (tenant, *values)).fetchone():
            predicates = sql.SQL(" AND ").join(
                sql.SQL("{}=%s").format(sql.Identifier(c)) for c in ("tenant", *columns)
            )
            if not db.execute(
                sql.SQL("SELECT 1 FROM ap.{} WHERE {}").format(
                    sql.Identifier(table), predicates
                ),
                (tenant, *values),
            ).fetchone():
                raise ValueError(
                    "Existing record differs from import. Reconcile the source first."
                )


def main():
    p = argparse.ArgumentParser()
    p.add_argument(
        "action",
        choices=[
            "init",
            "stop",
            "migrate",
            "shadow",
            "enable",
            "import",
            "sample",
            "notify",
            "maintain",
            "reconcile",
        ],
    )
    p.add_argument("--tenant", default="saffron")
    p.add_argument("--file", type=Path)
    p.add_argument("--number", default="DC-1042")
    args = p.parse_args()
    if args.action == "init":
        initialize()
    elif args.action == "stop":
        subprocess.run(
            [binary("pg_ctl"), "-D", str(DATA), "stop", "-m", "fast", "-w"], check=True
        )
    elif args.action == "sample":
        from .sample import fields, write_sample

        write_sample(args.file or HOME / "supplier-invoice.pdf", fields(args.number))
    elif args.action == "notify":
        from .notifications import deliver

        print(deliver(args.tenant))
    elif args.action == "maintain":
        from .maintenance import optimize, recover

        print(
            json.dumps(
                {
                    "recovery": recover(args.tenant),
                    "optimization": optimize(args.tenant),
                }
            )
        )
    else:
        admin = os.environ.get("AP_ADMIN_DSN") or dsn(
            json.loads((HOME / "local-admin.json").read_text()), "postgres"
        )
        if args.action == "migrate":
            migrate(admin, os.environ["AP_RUNTIME_PASSWORD"])
            return
        with psycopg.connect(admin) as db:
            db.execute(
                "SELECT pg_advisory_xact_lock(hashtextextended(%s,0))", (args.tenant,)
            )
            db.execute("SELECT set_config('ap.tenant',%s,true)", (args.tenant,))
            if args.action == "import":
                with args.file.open(encoding="utf-8-sig", newline="") as stream:
                    import_csv(db, args.tenant, stream)
            elif args.action == "reconcile":
                actual = dict(
                    db.execute(
                        "SELECT business_key,amount FROM ap.queue WHERE tenant=%s",
                        (args.tenant,),
                    ).fetchall()
                )
                report = {
                    "entries": len(actual),
                    "amount": str(sum(actual.values(), Decimal(0))),
                }
                if args.file:
                    expected = {}
                    with args.file.open(encoding="utf-8-sig", newline="") as stream:
                        for record in csv.DictReader(stream):
                            key = record["business_key"]
                            if key in expected:
                                raise ValueError("Duplicate finance ledger reference")
                            expected[key] = Decimal(record["amount"])
                    report["differences"] = [
                        k
                        for k in sorted(expected.keys() | actual.keys())
                        if expected.get(k) != actual.get(k)
                    ]
                print(json.dumps(report))
                if report.get("differences"):
                    db.execute(
                        "UPDATE ap.controls SET queue_enabled=false WHERE tenant=%s",
                        (args.tenant,),
                    )
                    db.commit()
                    raise SystemExit(1)
            else:
                result = db.execute(
                    "UPDATE ap.controls SET queue_enabled=%s WHERE tenant=%s",
                    (args.action == "enable", args.tenant),
                )
                if result.rowcount != 1:
                    raise ValueError("Unknown tenant")


if __name__ == "__main__":
    main()
