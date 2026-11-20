import io

import psycopg
import pytest
from PIL import Image
from pypdf import PdfReader, PdfWriter
from reportlab.lib.utils import ImageReader
from reportlab.pdfgen.canvas import Canvas

from ap.sample import fields, write_sample


@pytest.mark.parametrize("missing_field", ["taxable", "date"])
def test_partial_copy_blocks_ready_invoice_until_dismissed(pilot, missing_field):
    original = fields("COPY-10")
    ready = pilot.upload(original)
    partial = dict(original)
    del partial[missing_field]
    duplicate = pilot.upload(partial)
    assert duplicate["stage"] == "review"
    url = f"/workflows/{ready['id']}/submit"
    result = pilot.request("POST", url, json={"version": ready["version"]}).json()
    assert result["stage"] == "review"
    assert "Possible duplicate invoice" in result["issues"]
    assert pilot.request("GET", "/queue").json() == []
    pilot.request(
        "POST",
        f"/workflows/{duplicate['id']}/dismiss",
        json={"version": duplicate["version"], "reason": "Confirmed second copy"},
    ).raise_for_status()
    verified = pilot.request(
        "PUT",
        f"/workflows/{ready['id']}/fields",
        json={
            "fields": original,
            "version": result["version"],
            "page": 1,
            "reason": "Original verified",
        },
    ).json()
    assert (
        pilot.request("POST", url, json={"version": verified["version"]}).json()[
            "stage"
        ]
        == "pending"
    )


def test_large_mismatched_amount_reaches_review(pilot):
    data = fields("VALUE-10")
    data["lines"][0].update(qty="9999999999999.999", unit_price="99999999999999.99")
    result = pilot.upload(data)
    assert result["stage"] == "review"
    assert result["issues"]


def test_large_batch_keeps_paise_from_submission_to_queue(pilot):
    price = "99999999999999.99"
    with psycopg.connect(pilot.admin) as db:
        db.execute(
            "UPDATE ap.po_line SET price=%s,gst_rate=0 WHERE tenant=%s",
            (price, pilot.tenant),
        )
    items = []
    for number in ("BIG-A", "BIG-B"):
        data = fields(number, "1")
        data.update(taxable=price, cgst="0", sgst="0", total=price)
        data["lines"][0].update(unit_price=price, gst_rate="0")
        row = pilot.upload(data)
        assert row["stage"] == "ready"
        items.append({"id": row["id"], "version": row["version"]})
    batch = pilot.request("POST", "/batches", json={"items": items}).json()
    assert batch["amount"] == "199999999999999.98"
    detail = pilot.request("GET", "/workflows/" + items[0]["id"]).json()
    assert detail["batch"]["amount_exact"] == batch["amount"]
    assert (
        pilot.request("POST", f"/batches/{batch['id']}/approve", "executive").json()[
            "status"
        ]
        == "queued"
    )
    assert [r["amount_exact"] for r in pilot.request("GET", "/queue").json()] == [
        price,
        price,
    ]


def test_invoice_with_unread_scanned_attachment_needs_review(pilot):
    doc = io.BytesIO()
    write_sample(doc, fields("MIXED-10"))
    extra = io.BytesIO()
    canvas = Canvas(extra)
    canvas.drawImage(ImageReader(Image.new("RGB", (30, 30), "gray")), 50, 50)
    canvas.save()
    writer = PdfWriter()
    writer.append(PdfReader(doc))
    writer.append(PdfReader(extra))
    combined = io.BytesIO()
    writer.write(combined)
    result = pilot.request(
        "POST",
        "/workflows",
        files={"file": ("mixed.pdf", combined.getvalue(), "application/pdf")},
    ).json()
    assert result["fields"]["number"] == "MIXED-10"
    assert result["stage"] == "review"
    assert any("2" in issue for issue in result["issues"])
