"""Deterministic, exact-match domestic PO policy. Amounts are expressed in INR."""

import json
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, ValidationError

from .db import settings

Text = Annotated[
    str, StringConstraints(strip_whitespace=True, min_length=1, max_length=120)
]
GSTIN = Annotated[str, StringConstraints(pattern=r"^[0-9]{2}[A-Z0-9]{13}$")]
Money = Annotated[Decimal, Field(ge=0, max_digits=16, decimal_places=2)]
Quantity = Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=3)]
CENT = Decimal("0.01")
RULES = json.loads(Path(__file__).with_name("rules.json").read_text())
CAP = Decimal(RULES["executive_above"])
POLICY = RULES["version"]


class Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Line(Strict):
    po: Text
    sku: Text
    hsn: Text
    qty: Quantity
    unit_price: Money
    gst_rate: Annotated[Decimal, Field(ge=0, le=100, decimal_places=2)]


class InvoiceIdentity(Strict):
    number: Annotated[
        str, StringConstraints(strip_whitespace=True, pattern=r"^[A-Za-z0-9/\-]{1,16}$")
    ]
    date: date
    supplier: GSTIN


class Invoice(InvoiceIdentity):
    buyer: GSTIN
    place: Annotated[str, StringConstraints(pattern=r"^\d{2}$")]
    currency: Literal["INR"]
    supply: Literal["domestic_goods"]
    reverse_charge: Literal["no"]
    lines: list[Line] = Field(min_length=1, max_length=100)
    taxable: Money
    cgst: Money
    sgst: Money
    igst: Money
    total: Annotated[Decimal, Field(gt=0, max_digits=16, decimal_places=2)]


def rounded(value):
    return value.quantize(CENT, rounding=ROUND_HALF_UP)


def invoice_totals(inv):
    # Two 16-digit operands, a rate, and up to 100 lines can exceed Decimal's default precision.
    with localcontext(prec=42):
        net = central = state = integrated = Decimal(0)
        for line in inv.lines:
            value = rounded(line.qty * line.unit_price)
            net += value
            if inv.supplier[:2] == inv.place:
                half_tax = rounded(value * line.gst_rate / 200)
                central += half_tax
                state += half_tax
            else:
                integrated += rounded(value * line.gst_rate / 100)
        return net, central, state, integrated, net + central + state + integrated


def business_key(data):
    fy = data.date.year - int(data.date.month < 4)
    return f"{data.supplier}/{fy}/{data.number.upper()}"


def required_role(total):
    return "executive" if total > CAP else "finance"


def evaluate(db, raw, wid):
    try:
        inv = Invoice.model_validate(raw)
    except ValidationError as exc:
        return ["Check " + ".".join(map(str, e["loc"])) for e in exc.errors()][:25], []
    issues, matches = [], []
    cfg = settings()
    if cfg.get("environment") != "synthetic":
        tenant = db.execute("SELECT current_setting('ap.tenant') AS tenant").fetchone()[
            "tenant"
        ]
        approved = cfg.get("tax_approvals", {}).get(tenant, {})
        if (
            approved.get("version") != POLICY
            or not approved.get("owner")
            or not approved.get("from", "9999")
            <= inv.date.isoformat()
            <= approved.get("through", "")
        ):
            issues.append("Invoice outside finance-approved GST rule period")
    ctrl = db.execute("SELECT buyer_gstin,eligible_vendors FROM controls").fetchone()
    if not ctrl or inv.buyer != ctrl["buyer_gstin"] or inv.place != inv.buyer[:2]:
        issues.append("Buyer or place of supply outside the approved domestic policy")
    if not ctrl or inv.supplier not in ctrl["eligible_vendors"]:
        issues.append("Supplier outside pilot cohort")
    if inv.date > date.today():
        issues.append("Invoice date is in the future")
    if not db.execute(
        "SELECT 1 FROM vendor WHERE gstin=%s", (inv.supplier,)
    ).fetchone():
        issues.append("Unknown supplier")
    key = business_key(inv)
    if db.execute(
        "SELECT 1 FROM queue WHERE business_key=%s AND workflow_id<>%s", (key, wid)
    ).fetchone():
        issues.append("Invoice already queued")
    # A matching number and supplier need a clear financial year to rule out a duplicate.
    peers = db.execute(
        "SELECT fields FROM workflow WHERE id<>%s AND upper(fields->>'number')=%s AND fields->>'supplier'=%s AND stage<>'dismissed'",
        (wid, inv.number.upper(), inv.supplier),
    ).fetchall()
    for peer in peers:
        try:
            identity = {k: peer["fields"].get(k) for k in InvoiceIdentity.model_fields}
            possible_duplicate = (
                business_key(InvoiceIdentity.model_validate(identity)) == key
            )
        except ValidationError:
            # Missing identity evidence keeps the match open for human review.
            possible_duplicate = True
        if possible_duplicate:
            issues.append("Possible duplicate invoice")
            break
    seen = set()
    for line in inv.lines:
        ref = (line.po, line.sku)
        if ref in seen:
            issues.append(f"Repeated order line {line.po}/{line.sku}")
            continue
        seen.add(ref)
        po = db.execute("SELECT * FROM po_line WHERE po=%s AND sku=%s", ref).fetchone()
        if not po or (po["gstin"], po["price"], po["gst_rate"], po["hsn"]) != (
            inv.supplier,
            line.unit_price,
            line.gst_rate,
            line.hsn,
        ):
            issues.append(f"Order terms differ or are missing for {line.po}/{line.sku}")
            continue
        allocated = db.execute(
            "SELECT coalesce(sum(qty),0) AS used FROM allocation WHERE po=%s AND sku=%s",
            ref,
        ).fetchone()["used"]
        if line.qty + allocated > po["ordered"]:
            issues.append(f"Exceeds remaining purchase order quantity for {line.sku}")
        remaining = line.qty
        receipts = db.execute(
            """SELECT r.grn,r.qty-coalesce(sum(a.qty),0) available FROM receipt r
            LEFT JOIN allocation a USING (tenant,grn,po,sku) WHERE r.po=%s AND r.sku=%s
            GROUP BY r.grn,r.qty ORDER BY r.grn""",
            ref,
        ).fetchall()
        for receipt in receipts:
            qty = min(remaining, receipt["available"])
            if qty > 0:
                matches.append(
                    {
                        "grn": receipt["grn"],
                        "po": line.po,
                        "sku": line.sku,
                        "qty": str(qty),
                    }
                )
                remaining -= qty
        if remaining:
            issues.append(f"Missing receipt for {remaining} units of {line.sku}")
    if (inv.taxable, inv.cgst, inv.sgst, inv.igst, inv.total) != invoice_totals(inv):
        issues.append(
            "Tax components or invoice total differ from approved order arithmetic"
        )
    return issues, matches
