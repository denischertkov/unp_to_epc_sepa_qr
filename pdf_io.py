# -*- coding: utf-8 -*-
"""
Чтение PDF: извлечение данных из UNP QR-кодов (содержимое QR), формирование
итогового PDF с EPC QR-кодами и реестром платежей.
"""
import io
from typing import List, Tuple

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    Image,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from upn_parser import UPNPayment
from epc_qr import build_epc_payload, payload_to_qr_image
from unp_qr_decode import parse_all_unp_qr_contents
from pdf_qr_extract import extract_qr_strings_from_pdf


def _ascii_slovenian(s: str) -> str:
    """Replace Slovenian diacritics for PDF display: c, s, z -> c, s, z."""
    if not s:
        return s
    return (
        s.replace("\u010d", "c").replace("\u010c", "C")  # c, C
        .replace("\u0161", "s").replace("\u0160", "S")  # s, S
        .replace("\u017e", "z").replace("\u017d", "Z")  # z, Z
    )


def build_output_pdf(
    payments: List[UPNPayment],
    output_path: str,
    title: str = "Payments with QR codes (EPC / Revolut)",
) -> None:
    """
    Builds PDF: title, payment register (table with amounts and total),
    then for each payment — description and QR code.
    """
    doc = SimpleDocTemplate(
        output_path,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=15 * mm,
        bottomMargin=15 * mm,
    )
    story = []
    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        name="CustomTitle",
        parent=styles["Heading1"],
        fontSize=16,
        spaceAfter=8 * mm,
    )
    story.append(Paragraph(title, title_style))
    story.append(Spacer(1, 4 * mm))

    story.append(Paragraph("Payment register", styles["Heading2"]))
    story.append(Spacer(1, 2 * mm))

    total = sum(p.amount for p in payments)
    table_data = [
        ["#", "Recipient", "Reference", "Amount (EUR)", "QR"],
    ]
    for idx, p in enumerate(payments, 1):
        rec = _ascii_slovenian(p.recipient_name or "")
        table_data.append([
            str(idx),
            (rec[:40] + "..." if len(rec) > 40 else rec),
            p.reference,
            f"{p.amount:.2f}",
            "Y",
        ])
    table_data.append(["", "", "TOTAL", f"{total:.2f}", ""])

    # # narrow, Recipient wider so text does not overflow into Reference
    t = Table(table_data, colWidths=[12 * mm, 75 * mm, 45 * mm, 25 * mm, 18 * mm])
    t.setStyle(
        TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#4472C4")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("ALIGN", (0, 0), (-1, -1), "LEFT"),
            ("ALIGN", (3, 0), (3, -1), "RIGHT"),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, 0), 10),
            ("BOTTOMPADDING", (0, 0), (-1, 0), 8),
            ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#E2EFDA")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("GRID", (0, 0), (-1, -1), 0.5, colors.grey),
            ("FONTSIZE", (0, 1), (-1, -1), 9),
        ])
    )
    story.append(t)
    story.append(Spacer(1, 10 * mm))

    story.append(Paragraph("Payment QR codes (EPC SCT)", styles["Heading2"]))
    story.append(Spacer(1, 2 * mm))

    qr_size = 45 * mm
    desc_width = 120 * mm
    pad = 5 * mm  # gap between frame and content (QR / text)
    # Column width = content + padding on both sides so the frame does not overlap content
    col0_width = desc_width + 2 * pad
    col1_width = qr_size + 2 * pad
    for idx, p in enumerate(payments, 1):
        payload = build_epc_payload(p)
        qr_bytes = payload_to_qr_image(payload, box_size=5, border=2)
        img = Image(io.BytesIO(qr_bytes), width=qr_size, height=qr_size)

        rec = _ascii_slovenian(p.recipient_name or "")
        purp = _ascii_slovenian(p.purpose)
        purp_show = purp[:70] + "..." if len(purp) > 70 else purp
        desc_para = Paragraph(
            f"<b>Recipient</b> {rec}<br/>"
            f"IBAN {p.iban} &middot; {p.amount:.2f} EUR<br/>"
            f"Ref. {p.reference}<br/>"
            f"{purp_show}",
            styles["Normal"],
        )
        row_data = [[desc_para, img]]
        tbl = Table(row_data, colWidths=[col0_width, col1_width])
        tbl.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), pad),
            ("RIGHTPADDING", (0, 0), (-1, -1), pad),
            ("TOPPADDING", (0, 0), (-1, -1), pad),
            ("BOTTOMPADDING", (0, 0), (-1, -1), pad),
            ("BOX", (0, 0), (-1, -1), 0.5, colors.lightgrey),
            ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8f9fa")),
        ]))
        story.append(tbl)
        # Увеличенный промежуток между платежами — удобнее сканировать один QR, не задевая соседний
        if idx < len(payments):
            story.append(Spacer(1, 14 * mm))

    doc.build(story)


def process_pdf(input_pdf: str, output_pdf: str, verbose: bool = False) -> Tuple[List[UPNPayment], str]:
    """
    Read PDF, extract payment data from UNP QR code content only.
    If no UNP codes found, raises with diagnostic message.
    """
    qr_strings = extract_qr_strings_from_pdf(input_pdf, verbose=verbose)
    payments = parse_all_unp_qr_contents(qr_strings)

    if not payments:
        n = len(qr_strings)
        if n == 0:
            msg = (
                "No QR codes found in the PDF. "
                "The file may contain text only (no QR images). "
                "Use a PDF that includes actual QR codes (e.g. upn-qr.si)."
            )
        else:
            preview = (qr_strings[0][:200] + "...") if len(qr_strings[0]) > 200 else qr_strings[0]
            first_line = qr_strings[0].strip().split("\n")[0] if qr_strings[0].strip() else ""
            msg = (
                f"Found {n} QR code(s) in the PDF, but content is not valid UPN QR format.\n"
                f"First line: {repr(first_line)}\n"
                f"Content preview: {repr(preview)}\n"
                "Expected first line: 'UPNQR' (Slovenian payment order, upn-qr.si)."
            )
        raise ValueError(msg)

    build_output_pdf(payments, output_pdf)
    return payments, "QR"


def format_payment_register_text(payments: List[UPNPayment]) -> str:
    """Format payment register as plain text (e.g. for email body)."""
    total = sum(p.amount for p in payments)
    lines = [
        "Payment register",
        "",
        "#\tRecipient\tReference\tAmount (EUR)",
        "-" * 60,
    ]
    for idx, p in enumerate(payments, 1):
        rec = _ascii_slovenian(p.recipient_name or "")
        rec_short = (rec[:50] + "...") if len(rec) > 50 else rec
        lines.append(f"{idx}\t{rec_short}\t{p.reference}\t{p.amount:.2f}")
    lines.append("-" * 60)
    lines.append(f"TOTAL\t\t\t{total:.2f}")
    return "\n".join(lines)
