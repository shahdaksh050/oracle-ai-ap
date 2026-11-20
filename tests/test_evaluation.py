import json
from io import BytesIO

import psycopg
import pytest
from PIL import Image

from ap.evaluate import collect
from ap.loadcheck import run
from ap.sample import fields, write_sample


def test_held_out_and_capacity_tools(pilot, monkeypatch):
    p = pilot
    with psycopg.connect(p.admin) as db:
        db.execute(
            "UPDATE ap.controls SET queue_enabled=false WHERE tenant=%s", (p.tenant,)
        )
    data = fields("EVAL-01")
    write_sample(p.tmp / "labelled.pdf", data)
    manifest = p.tmp / "manifest.json"
    manifest.write_text(
        json.dumps(
            [
                {
                    "file": "labelled.pdf",
                    "format": "text_pdf",
                    "expected": data,
                    "ready": True,
                    "receipts": [
                        {"grn": "GR-230", "po": "PO-410", "sku": "BR-20", "qty": "10"}
                    ],
                    "baseline_minutes": 10,
                    "pilot_minutes": 7,
                }
            ]
        )
    )
    scores = collect(p.actor, manifest)
    assert (
        min(scores["per_field"].values()) == 1 and scores["incorrect_ready_rows"] == []
    )
    assert not scores["accuracy_gate"] and scores["review_rate"] == 0
    assert scores["median_handling_reduction"] == pytest.approx(0.3)
    # Use a test-only synthetic account to exercise the load runner.
    import hashlib

    cfg = json.loads(p.cfg.read_text())
    token = "local-fixture-token"
    cfg["accounts"].append(
        {
            "tenant": p.tenant,
            "user": "bench",
            "role": "clerk",
            "digest": hashlib.sha256(token.encode()).hexdigest(),
        }
    )
    p.cfg.write_text(json.dumps(cfg))
    monkeypatch.setenv("AP_EVAL_KEY", token)
    perf = run(30, 1, 1)
    assert perf["requested"] == perf["ready"] == 1
    assert p.request("GET", "/queue").json() == []


def test_shadow_submission_needs_fresh_authority(pilot):
    p = pilot
    row = p.upload()
    url = "/workflows/" + row["id"]
    with psycopg.connect(p.admin) as db:
        db.execute(
            "UPDATE ap.controls SET queue_enabled=false WHERE tenant=%s", (p.tenant,)
        )
    assert (
        p.request("POST", url + "/submit", json={"version": 1}).json()["stage"]
        == "ready"
    )
    with psycopg.connect(p.admin) as db:
        db.execute(
            "UPDATE ap.controls SET queue_enabled=true WHERE tenant=%s", (p.tenant,)
        )
    assert (
        p.request("POST", url + "/approve", "finance", json={"version": 1}).status_code
        == 409
    )
    assert (
        p.request("POST", url + "/submit", json={"version": 1}).json()["stage"]
        == "pending"
    )


def test_configured_model_evidence_and_bad_payload(pilot, monkeypatch):
    from ap import documents

    p = pilot
    cfg = json.loads(p.cfg.read_text())
    cfg["model"] = {"name": "fixture", "url": "https://private.invalid/"}
    p.cfg.write_text(json.dumps(cfg))
    data = fields("VISION-01")
    refs = {k: {"page": 1, "quote": str(v)} for k, v in data.items()}
    refs["lines.0"] = {"page": 1, "quote": "PO-410"}
    monkeypatch.setattr(
        documents, "model_json", lambda _: {"fields": data, "evidence": refs}
    )
    im = Image.new("RGB", (120, 100), "white")
    buf = BytesIO()
    im.save(buf, "PNG")
    raw, refs, issues = documents.extract(buf.getvalue(), "image/png", {})
    assert raw["number"] == "VISION-01" and refs["lines.0"]["page"] == 1 and issues
    assert raw["total"] == "1180.00"
