# -*- coding: utf-8 -*-
"""
Парсинг содержимого UNP/UPN QR кода (строка, полученная при декодировании QR).
Спецификация: UPN QR (upn-qr.si), формат — строки, разделённые \\n.
"""
import re
from typing import List, Optional

from upn_parser import UPNPayment


# Порядок полей в UPN QR (по py-upn-qr и NavodilaZaProgramerjeUPNQR):
# 0: UPNQR
# 1-4: резерв
# 5: ime_placnika, 6: ulica_placnika, 7: kraj_placnika
# 8: znesek (11 цифр, без запятой — последние 2 знака копейки)
# 9-10: резерв
# 11: koda_namena (4 символа)
# 12: namen_placila
# 13: rok_placila
# 14: IBAN prejemnika (без пробелов)
# 15: referenca prejemnika (model + sklic, без пробелов)
# 16: ime_prejemnika, 17: ulica_prejemnika, 18: kraj_prejemnika
# После 19 строк может идти \\n + 3-значная контрольная сумма + \\n


def _normalize_iban(iban: str) -> str:
    return re.sub(r"\s+", "", (iban or "").strip()).upper()


def _parse_upn_amount(znesek_11: str) -> Optional[float]:
    """Парсит сумму из 11 цифр (последние 2 — копейки)."""
    s = (znesek_11 or "").strip()
    s = re.sub(r"\D", "", s)
    if len(s) != 11:
        return None
    try:
        return int(s) / 100.0
    except ValueError:
        return None


def parse_unp_qr_content(qr_string: str) -> Optional[UPNPayment]:
    """
    Парсит одну строку — содержимое декодированного UNP QR кода.
    Возвращает UPNPayment или None, если строка не является валидным UPNQR.
    """
    if not qr_string or not qr_string.strip():
        return None
    lines = [ln.strip() for ln in qr_string.strip().split("\n")]
    # Убираем последнюю строку, если это 3-значная контрольная сумма
    if len(lines) > 19 and lines[-1].isdigit() and len(lines[-1]) == 3:
        lines = lines[:-1]
    if len(lines) < 19:
        return None
    if lines[0] != "UPNQR":
        return None

    znesek_val = _parse_upn_amount(lines[8])
    if znesek_val is None or znesek_val < 0:
        return None

    iban = _normalize_iban(lines[14])
    if not iban.startswith("SI") or len(iban) != 19:
        return None

    recipient_name = (lines[16] or "").strip()
    recipient_address = " ".join(filter(None, [lines[17], lines[18]])).strip()
    reference = (lines[15] or "").strip()
    purpose_code = (lines[11] or "").strip()[:4]
    purpose_text = (lines[12] or "").strip()
    purpose = purpose_text or purpose_code or "UPN payment"

    return UPNPayment(
        recipient_name=recipient_name or "Recipient",
        recipient_address=recipient_address,
        iban=iban,
        amount=znesek_val,
        reference=reference,
        purpose=purpose,
        payer_reference="",
    )


def parse_all_unp_qr_contents(qr_strings: List[str]) -> List[UPNPayment]:
    """Парсит список строк (содержимое нескольких QR). Убирает дубликаты по (iban, reference, amount)."""
    seen = set()
    payments: List[UPNPayment] = []
    for s in qr_strings:
        p = parse_unp_qr_content(s)
        if p is None:
            continue
        key = (p.iban, p.reference, p.amount)
        if key in seen:
            continue
        seen.add(key)
        payments.append(p)
    return payments
