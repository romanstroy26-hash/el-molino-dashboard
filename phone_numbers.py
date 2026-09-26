"""Phone formats used for customer identity and Mexican SMS delivery."""

from __future__ import annotations

import re


def mexican_sms_number(phone: str) -> str:
    """Return country code plus ten digits, without punctuation or a plus sign."""
    digits = re.sub(r"[\s()+.-]", "", phone)
    if not digits.isdigit():
        raise ValueError("Número de teléfono inválido")
    if len(digits) == 10:
        return "52" + digits
    if len(digits) == 12 and digits.startswith("52"):
        return digits
    if len(digits) == 13 and digits.startswith("521"):
        return "52" + digits[3:]
    raise ValueError("Usa un número mexicano de 10 dígitos")


def normalize_customer_phone(phone: str | None) -> str | None:
    """Canonicalize real Mexican numbers while preserving legacy identifiers."""
    phone = phone.strip() if phone else None
    if not phone:
        return None
    try:
        return "+" + mexican_sms_number(phone)
    except ValueError:
        return phone
