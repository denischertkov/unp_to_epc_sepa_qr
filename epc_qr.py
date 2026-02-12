# -*- coding: utf-8 -*-
"""
Формирование EPC QR-кода для SEPA Credit Transfer (Revolut, N26, bunq и др.).
Спецификация: EPC069-12 Quick Response Code Guidelines.
"""
import io
from typing import Optional

import qrcode
from qrcode.constants import ERROR_CORRECT_M

from upn_parser import UPNPayment


def build_epc_payload(p: UPNPayment, bic: Optional[str] = None) -> str:
    """
    Собирает строку для QR-кода в формате EPC (BCD, версия 002).
    Разделитель — перевод строки (LF). Последнее поле без LF.
    """
    # Character set: 1 = UTF-8
    # BIC пустой для EEA (Словения) допустим
    bic = (bic or "").strip()
    name = (p.recipient_name or "")[:70]
    iban = (p.iban or "").replace(" ", "").upper()[:34]
    amount_str = f"{p.amount:.2f}".replace(".", ",")  # в спецификации пример EUR12.3 — с точкой; многие используют запятую
    # Для совместимости с Revolut используем точку в сумме
    amount_str = f"{p.amount:.2f}"
    purpose = (p.purpose or "")[:4] if p.purpose else ""
    # Remittance: структурированная (RF) или неструктурированная. SI19 не RF — передаём как неструктурированную
    remittance = (p.reference or "")[:35]
    if len(remittance) > 35:
        remittance = remittance[:35]
    # Beneficiary to originator — описание платежа
    b2o = (p.purpose or "")[:70]

    parts = [
        "BCD",
        "002",
        "1",  # UTF-8
        "SCT",
        bic,
        name,
        iban,
        "EUR" + amount_str,
        purpose,
        remittance,
        b2o,
    ]
    # Убираем пустые хвосты (последний элемент без разделителя не должен быть пустым)
    while len(parts) > 1 and parts[-1] == "":
        parts.pop()
    return "\n".join(parts)


def payload_to_qr_image(payload: str, box_size: int = 6, border: int = 2) -> bytes:
    """Генерирует PNG-изображение QR-кода. Возвращает bytes (PNG)."""
    qr = qrcode.QRCode(
        version=None,
        error_correction=ERROR_CORRECT_M,
        box_size=box_size,
        border=border,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()
