"""Normalisasi nama personel dan jumlah alat lintas parser PL/tender."""

import re


_PREFIX_TITLES = {
    "dr", "drs", "dra", "ir", "prof", "kh", "h", "hj", "ust", "ustz",
}
_SUFFIX_TITLES = {
    "st", "se", "sh", "sos", "spsi", "si", "skom", "mt", "mm", "msi",
    "mkom", "mh", "mpd", "mhum", "ak", "ca", "cpa", "apt", "amd", "amdt",
}
_COMPANY_PREFIX = re.compile(r"^(?:CV|PT|UD|PD|Koperasi|Firma)\b\.?", re.IGNORECASE)


def _title_key(token: str) -> str:
    return re.sub(r"[^a-z]", "", str(token or "").casefold())


def clean_person_name(value: str) -> str:
    """Kembalikan nama orang saja: tanpa jabatan, kurung, NIK, dan gelar."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    text = re.sub(r"^Nama\s+Lengkap\s*[:\-]?\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s+(?:Jabatan|Profesi|Keahlian)\b.*$", "", text, flags=re.IGNORECASE)
    previous = None
    while previous != text:
        previous = text
        text = re.sub(r"\([^()]*\)", " ", text)
    text = re.sub(r"\b\d{16}\b", " ", text)
    text = re.sub(r"\s+", " ", text).strip(" ,.;:-")
    if not text or _COMPANY_PREFIX.match(text) or re.fullmatch(r"[\d\s./-]+", text):
        return ""

    tokens = text.split()
    while tokens and _title_key(tokens[0]) in _PREFIX_TITLES:
        tokens.pop(0)
    while tokens and _title_key(tokens[-1]) in _SUFFIX_TITLES:
        tokens.pop()
    text = " ".join(tokens).strip(" ,.;:-")
    return text if text and not _COMPANY_PREFIX.match(text) else ""


def normalize_equipment_quantity(value: str) -> str:
    """Pastikan jumlah alat numerik memiliki satuan ``Unit``."""
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    if not text:
        return ""
    number = r"\d+(?:[.,]\d+)?"
    match = re.fullmatch(rf"({number})\s*(?:unit|unt|unlt)\.?", text, re.IGNORECASE)
    if match:
        return f"{match.group(1)} Unit"
    if re.fullmatch(number, text):
        return f"{text} Unit"
    return text


def format_equipment_entry(name: str, quantity: str) -> str:
    """Format alat, misalnya ``Dump Truck (1 Unit)``."""
    label = re.sub(r"\s+", " ", str(name or "")).strip()
    amount = normalize_equipment_quantity(quantity)
    return f"{label} ({amount})" if amount else label
