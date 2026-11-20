from datetime import date
from decimal import Decimal
from pathlib import Path

from .admin import BUYER, VENDOR


def fields(number="DC-1042", qty="10"):
    net = Decimal(qty) * 100
    tax = net * Decimal("0.09")
    return {
        "number": number,
        "date": date.today().isoformat(),
        "supplier": VENDOR,
        "buyer": BUYER,
        "place": "27",
        "currency": "INR",
        "supply": "domestic_goods",
        "reverse_charge": "no",
        "lines": [
            {
                "po": "PO-410",
                "sku": "BR-20",
                "hsn": "8482",
                "qty": qty,
                "unit_price": "100.00",
                "gst_rate": "18",
            }
        ],
        "taxable": str(net),
        "cgst": str(tax),
        "sgst": str(tax),
        "igst": "0",
        "total": str(net + 2 * tax),
    }


def write_sample(path, data=None):
    from reportlab.pdfgen.canvas import Canvas

    canvas = Canvas(str(path) if isinstance(path, Path) else path, invariant=True)
    canvas.setTitle("Synthetic supplier invoice")
    page = canvas.beginText(54, 780)
    page.setFont("Helvetica-Bold", 18)
    page.textLine("Deccan Components | Tax invoice")
    page.setFont("Helvetica", 11)
    page.textLine("Synthetic pilot fixture")
    for key, value in (data or fields()).items():
        if key == "lines":
            for row in value:
                page.textLine(
                    "Line: "
                    + " | ".join(
                        str(row[k])
                        for k in ("po", "sku", "hsn", "qty", "unit_price", "gst_rate")
                    )
                )
        else:
            page.textLine(f"{key}: {value}")
    canvas.drawText(page)
    canvas.save()
