# -*- coding: utf-8 -*-
"""
Извлечение платёжных данных UPN/UNP из текста словенских платёжных поручений.
"""
import re
from dataclasses import dataclass
from typing import List, Optional


@dataclass
class UPNPayment:
    """Один платёж из UPN."""
    recipient_name: str
    recipient_address: str
    iban: str
    amount: float
    reference: str          # SI19 xxxxx-xxxxx или аналог
    purpose: str            # назначение платежа (напр. Prispevek za DO)
    payer_reference: str    # RFxx - sklic na plačnika (опционально)


def _normalize_iban(iban: str) -> str:
    """Убирает пробелы из IBAN для хранения и EPC."""
    return re.sub(r"\s+", "", iban.strip()).upper()


def _parse_amount(s: str) -> Optional[float]:
    """Парсит сумму вида ***28,74 или 28,74."""
    s = s.strip()
    s = re.sub(r"^\*+", "", s)
    s = s.replace(",", ".")
    try:
        return float(s)
    except ValueError:
        return None


def extract_upn_payments(text: str) -> List[UPNPayment]:
    """
    Извлекает все платёжные блоки UPN из текста (например, из PDF).
    Ориентируется на повторяющиеся блоки: IBAN (SI56), сумма (***X,XX), ссылка SI19.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    payments: List[UPNPayment] = []
    i = 0

    iban_re = re.compile(r"^SI\d{2}\s*[\d\s]+$")
    si19_re = re.compile(r"^SI19\s+[\d\-]+$")
    amount_re = re.compile(r"^\*+\s*[\d]+[,\.]\d{2}\s*$")

    while i < len(lines):
        line = lines[i]
        # Ищем строку с IBAN (SI56 ...)
        if not iban_re.match(re.sub(r"\s+", "", line)) or "SI56" not in line:
            i += 1
            continue

        iban = _normalize_iban(line)
        if not iban.startswith("SI56") or len(iban) != 19:
            i += 1
            continue

        # Следующие строки: название получателя, адрес, назначение
        recipient_name = ""
        recipient_address = ""
        purpose = ""
        ref_si19 = ""
        amount_val: Optional[float] = None
        payer_ref = ""

        j = i + 1
        name_candidates: List[str] = []
        address_candidates: List[str] = []

        while j < len(lines):
            cur = lines[j]
            cur_clean = re.sub(r"\s+", " ", cur)

            if iban_re.match(re.sub(r"\s+", "", cur)) and "SI56" in cur:
                # Второй раз IBAN в блоке — после него идут SI19 и сумма
                if j + 1 < len(lines) and si19_re.match(lines[j + 1].replace(" ", "")):
                    ref_si19 = re.sub(r"\s+", "", lines[j + 1])
                if j + 2 < len(lines) and amount_re.match(lines[j + 2]):
                    amount_val = _parse_amount(lines[j + 2])
                if amount_val is not None and ref_si19:
                    # Имя и адрес — всё между первым IBAN и вторым IBAN
                    if name_candidates:
                        recipient_name = name_candidates[0]
                    if len(name_candidates) > 1:
                        recipient_address = " ".join(name_candidates[1:])
                    if purpose:
                        pass  # уже есть
                    break
                j += 1
                continue

            if si19_re.match(re.sub(r"\s+", "", cur)):
                ref_si19 = re.sub(r"\s+", "", cur)
                j += 1
                continue
            if amount_re.match(cur):
                amount_val = _parse_amount(cur)
                j += 1
                continue
            if re.match(r"^RF\d{2}\s*$", cur):
                payer_ref = cur.strip()
                j += 1
                continue

            # До второго вхождения IBAN — имя/адрес/назначение
            if not ref_si19 and not amount_re.match(cur):
                if not recipient_name and cur_clean and len(cur_clean) > 2:
                    name_candidates.append(cur_clean)
                elif recipient_name and not purpose and "Prispevek" in cur:
                    purpose = cur_clean
                elif recipient_name and purpose and "Prispevek" in cur:
                    purpose = cur_clean
            j += 1

        if amount_val is not None and amount_val > 0 and ref_si19 and iban:
            if not recipient_name and name_candidates:
                recipient_name = name_candidates[0]
            if len(name_candidates) > 1:
                recipient_address = " ".join(name_candidates[1:])
            if not purpose:
                purpose = "UPN payment"
            payments.append(
                UPNPayment(
                    recipient_name=recipient_name or "Recipient",
                    recipient_address=recipient_address,
                    iban=iban,
                    amount=amount_val,
                    reference=ref_si19,
                    purpose=purpose,
                    payer_reference=payer_ref,
                )
            )

        i += 1

    return payments


def extract_upn_payments_v2(text: str) -> List[UPNPayment]:
    """
    Альтернативный парсер: ищем блоки по паттерну SI19 + сумма подряд.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    payments: List[UPNPayment] = []
    seen = set()

    iban_re = re.compile(r"^SI56\s*[\d\s]+$")
    si19_re = re.compile(r"^SI19\s*[\d\-]+$")
    amount_re = re.compile(r"^\*+\s*[\d]+[,\.]\d{2}\s*$")

    i = 0
    while i < len(lines):
        line = lines[i]
        # Ищем SI19
        if not si19_re.match(re.sub(r"\s+", "", line)):
            i += 1
            continue
        ref_si19 = re.sub(r"\s+", "", line)
        # Следующая строка — сумма
        if i + 1 >= len(lines) or not amount_re.match(lines[i + 1]):
            i += 1
            continue
        amount_val = _parse_amount(lines[i + 1])
        if amount_val is None or amount_val <= 0:
            i += 1
            continue

        # Ищем IBAN и получателя выше (в обратном порядке по тексту)
        iban = ""
        recipient_name = ""
        recipient_address = ""
        purpose = ""
        payer_ref = ""

        for k in range(i - 1, max(-1, i - 25), -1):
            cur = lines[k]
            cur_clean = re.sub(r"\s+", " ", cur)
            if iban_re.match(re.sub(r"\s+", "", cur)) and "SI56" in cur and len(re.sub(r"\s+", "", cur)) == 19:
                iban = _normalize_iban(cur)
                break

        if not iban:
            i += 1
            continue

        # Имя и назначение: в PDF после SI19 и двух строк ***сумма идут NAME, ADDRESS, RFxx, SI19, PURPOSE
        name_lines = []
        j = i + 3  # после SI19, ***, ***
        while j < len(lines):
            ln = lines[j]
            ln_clean = re.sub(r"\s+", " ", ln)
            if amount_re.match(ln) or si19_re.match(re.sub(r"\s+", "", ln)):
                j += 1
                continue
            if re.match(r"^RF\d{2}\s*$", ln):
                payer_ref = ln.strip()
                j += 1
                continue
            if "Prispevek" in ln and not name_lines:
                # назначение может идти после RF и второго SI19
                purpose = ln_clean
                j += 1
                break
            if "Prispevek" in ln:
                purpose = ln_clean
                j += 1
                break
            if ln and re.sub(r"\s+", "", ln) != ref_si19 and "SI56" not in ln:
                name_lines.append(ln_clean)
            j += 1
            if purpose and len(name_lines) >= 1:
                break
        if name_lines:
            recipient_name = name_lines[0]
            if len(name_lines) > 1:
                recipient_address = " ".join(name_lines[1:])
        if not purpose:
            purpose = "UPN payment"

        key = (iban, ref_si19, amount_val)
        if key not in seen:
            seen.add(key)
            payments.append(
                UPNPayment(
                    recipient_name=recipient_name or "Recipient",
                    recipient_address=recipient_address,
                    iban=iban,
                    amount=amount_val,
                    reference=ref_si19,
                    purpose=purpose,
                    payer_reference=payer_ref,
                )
            )
        i += 1

    return payments


def extract_upn_payments_from_text_fallback(text: str) -> List[UPNPayment]:
    """
    Парсер под порядок полей в извлечённом pdfplumber тексте:
    ***сумма, ***сумма, SI56, SI19, ... (LBRI/дата), SI56, PREHODNI/имя, адрес, ...
    Ищем пары *** и затем в следующих строках SI56 и SI19.
    """
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
    payments: List[UPNPayment] = []
    seen = set()
    iban_re = re.compile(r"^SI56\s*[\d\s]+$")
    si19_re = re.compile(r"^SI19\s*[\d\-]+$")
    amount_re = re.compile(r"^\*+\s*[\d]+[,\.]\d{2}\s*$")

    i = 0
    while i < len(lines):
        if not amount_re.match(lines[i]):
            i += 1
            continue
        amount_val = _parse_amount(lines[i])
        if amount_val is None or amount_val <= 0:
            i += 1
            continue
        # Пропускаем возможную вторую строку ***
        j = i + 1
        if j < len(lines) and amount_re.match(lines[j]):
            j += 1
        # Ищем SI56 затем SI19 в следующих ~15 строках
        iban = ""
        ref_si19 = ""
        for k in range(j, min(len(lines), j + 18)):
            cur = lines[k]
            cur_nospace = re.sub(r"\s+", "", cur)
            if iban_re.match(cur_nospace) and "SI56" in cur and len(cur_nospace) == 19:
                iban = _normalize_iban(cur)
            if si19_re.match(cur_nospace):
                ref_si19 = cur_nospace
                break
        if not iban or not ref_si19:
            i += 1
            continue
        # Имя получателя и назначение — строки после SI19 (часто PREHODNI DAVČNI PODRAČUN и т.д.)
        name_lines = []
        purpose = ""
        for k in range(j + 1, min(len(lines), j + 25)):
            ln = lines[k]
            ln_clean = re.sub(r"\s+", " ", ln)
            if "Prispevek" in ln:
                purpose = ln_clean
                break
            if iban_re.match(re.sub(r"\s+", "", ln)) or si19_re.match(re.sub(r"\s+", "", ln)):
                continue
            if ln and "LBRI" not in ln and "LT10" not in ln and not re.match(r"^\d{10}\s*$", ln):
                name_lines.append(ln_clean)
        recipient_name = name_lines[0] if name_lines else "Recipient"
        recipient_address = " ".join(name_lines[1:]) if len(name_lines) > 1 else ""
        if not purpose:
            purpose = "UPN payment"

        key = (iban, ref_si19, amount_val)
        if key not in seen:
            seen.add(key)
            payments.append(
                UPNPayment(
                    recipient_name=recipient_name,
                    recipient_address=recipient_address,
                    iban=iban,
                    amount=amount_val,
                    reference=ref_si19,
                    purpose=purpose,
                    payer_reference="",
                )
            )
        i += 1

    return payments
