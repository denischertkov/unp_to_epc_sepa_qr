#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
UNP/UPN → EPC QR: извлечение платёжных данных из словенского PDF
и создание нового PDF с QR-кодами для Revolut и реестром платежей.
"""
import argparse
import sys
from pathlib import Path

from pdf_io import process_pdf


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build a PDF with EPC QR codes (Revolut) and payment register from a PDF containing UNP/UPN QR codes. "
        "Payments are read from the QR code content, not from PDF text."
    )
    parser.add_argument(
        "input_pdf",
        type=Path,
        help="Input PDF file with payment orders (UNP/UPN)",
    )
    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output PDF (default: input_epc_qr.pdf)",
    )
    parser.add_argument(
        "-d", "--debug",
        action="store_true",
        help="Print extracted data and payment count",
    )
    args = parser.parse_args()

    input_path = args.input_pdf
    if not input_path.is_file():
        print(f"Error: file not found: {input_path}", file=sys.stderr)
        return 1

    output_path = args.output
    if output_path is None:
        output_path = input_path.parent / f"{input_path.stem}_epc_qr.pdf"

    try:
        payments, raw_text = process_pdf(str(input_path), str(output_path), verbose=args.debug)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1

    print(f"Processed: {len(payments)} payment(s).")
    print(f"Total: {sum(p.amount for p in payments):.2f} EUR.")
    print(f"Written: {output_path}")

    if args.debug:
        print("\n--- Extracted data (excerpt) ---")
        print(raw_text[:2000] + "..." if len(raw_text) > 2000 else raw_text)
        print("\n--- Payments ---")
        for i, p in enumerate(payments, 1):
            print(f"{i}. {p.recipient_name} | {p.amount:.2f} EUR | {p.reference}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
