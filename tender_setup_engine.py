"""Submit setup tender Pokja memakai form aktual SPSE.

Tender memakai prefix ``/dokumen``; PL memakai ``/dokumennontender``.
Semua payload mempertahankan ``chk_id`` dari form agar row existing tidak
dianggap row baru oleh server.
"""

from __future__ import annotations

import re
import requests
from bs4 import BeautifulSoup

import spse_browser
from config import SPSE_BASE_URL

BASE = SPSE_BASE_URL.rstrip("/")
HEADERS = {"Cookie": "", "User-Agent": "Mozilla/5.0"}


def normalize_sbu_classification(value: str) -> str:
    """Normalize Tender SBU prefix before sending it to SPSE."""
    text = str(value or "")
    prefix = re.compile(
        r"^\s*Memiliki Sertifikat Badan Usaha\s*(?:\(\s*SBU\s*\)|SBU)\s+"
        r"dengan Kualifikasi Usaha Kecil,\s*serta disyaratkan\s*:?\s*",
        re.IGNORECASE,
    )
    if not prefix.match(text):
        return text
    suffix = prefix.sub("", text, count=1).strip()
    return (
        "Memiliki Sertifikat Badan Usaha SBU dengan Kualifikasi Usaha Kecil, "
        "serta disyaratkan "
        + suffix
    )


def _get_form(kode: str, suffix: str, action_part: str) -> tuple[BeautifulSoup, dict, str]:
    url = f"{BASE}/dokumen/{kode}/{suffix}"
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        raise RuntimeError("Cookie SPSE kosong.")
    resp = requests.get(url, headers={**HEADERS, "Cookie": cookie}, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"GET {suffix} gagal: HTTP {resp.status_code}")
    soup = BeautifulSoup(resp.text, "html.parser")
    form = next((f for f in soup.find_all("form") if action_part in (f.get("action") or "")), None)
    if not form:
        raise RuntimeError(f"Form {action_part} tidak ditemukan.")
    token = form.find("input", {"name": "authenticityToken"})
    if not token:
        raise RuntimeError(f"authenticityToken {suffix} tidak ditemukan.")
    return soup, {"cookie": cookie, "token": token.get("value", ""), "url": url}, form


def _indexed_items(form, prefixes: tuple[str, ...]) -> dict[str, list[dict]]:
    result = {p: {} for p in prefixes}
    pattern = re.compile(r"^([^[]+)\[(\d+)\]\.(chk_id|ckm_id)$")
    for inp in form.find_all("input"):
        match = pattern.match(inp.get("name", ""))
        if not match or match.group(1) not in result:
            continue
        prefix, index, field = match.group(1), int(match.group(2)), match.group(3)
        result[prefix].setdefault(index, {})[field] = inp.get("value", "")
    return {p: [items[i] for i in sorted(items)] for p, items in result.items()}


def _hidden_payload(form) -> dict[str, str]:
    """Pertahankan hidden field form SPSE; server memakai sebagian untuk binding row."""
    payload = {}
    for inp in form.find_all("input", type="hidden"):
        name = inp.get("name", "")
        if name and name != "authenticityToken":
            payload[name] = inp.get("value", "")
    return payload


def _set_selected(payload: dict, prefix: str, items: list[dict], selected: list[str]) -> None:
    selected_set = {str(x) for x in selected}
    for i, item in enumerate(items):
        ckm_id = str(item.get("ckm_id", ""))
        if ckm_id in selected_set:
            payload[f"{prefix}[{i}].ckm_id"] = item.get("ckm_id", "")


def scrape_ldk(kode: str) -> dict:
    soup, meta, form = _get_form(kode, "ldk", "ldksubmitbaru")
    items = _indexed_items(form, ("syaratAdmin", "syaratTeknis", "ijin"))
    return {
        **meta,
        "admin": items["syaratAdmin"],
        "teknis": items["syaratTeknis"],
        "ijin": items["ijin"],
        "submit": f"{BASE}/dokumen/{kode}/ldksubmitbaru",
    }


def submit_izin_usaha(kode: str, ijin_rows: list[dict]) -> dict:
    """POST hanya dua row izin usaha pada form LDK tender."""
    _, meta, form = _get_form(kode, "ldk", "ldksubmitbaru")
    items = _indexed_items(form, ("syaratAdmin", "syaratTeknis", "ijin"))
    ctx = {**meta, "ijin": items["ijin"], "submit": f"{BASE}/dokumen/{kode}/ldksubmitbaru"}
    payload = {"authenticityToken": ctx["token"], **_hidden_payload(form)}
    for i, row in enumerate(ijin_rows[:2]):
        item = ctx["ijin"][i] if i < len(ctx["ijin"]) else {}
        payload[f"ijin[{i}].chk_id"] = item.get("chk_id", "")
        payload[f"ijin[{i}].chk_nama"] = row.get("jenis_izin", "")
        payload[f"ijin[{i}].chk_klasifikasi"] = normalize_sbu_classification(row.get("klasifikasi", ""))
    resp = requests.post(
        ctx["submit"], data=payload,
        headers={**HEADERS, "Cookie": ctx["cookie"], "Referer": ctx["url"]},
        allow_redirects=False, timeout=30,
    )
    return {"ok": resp.status_code in (200, 302), "status": resp.status_code, "redirect": resp.headers.get("Location", "")}


def submit_ldk(
    kode: str,
    ijin_rows: list[dict],
    admin_ids: list[str],
    teknis_ids: list[str],
    kinerja_text: str = "",
) -> dict:
    _, meta, form = _get_form(kode, "ldk", "ldksubmitbaru")
    items = _indexed_items(form, ("syaratAdmin", "syaratTeknis", "ijin"))
    ctx = {**meta, "admin": items["syaratAdmin"], "teknis": items["syaratTeknis"], "ijin": items["ijin"], "submit": f"{BASE}/dokumen/{kode}/ldksubmitbaru"}
    payload = {"authenticityToken": ctx["token"], **_hidden_payload(form)}
    for i, row in enumerate(ijin_rows[:2]):
        item = ctx["ijin"][i] if i < len(ctx["ijin"]) else {}
        payload[f"ijin[{i}].chk_id"] = item.get("chk_id", "")
        payload[f"ijin[{i}].chk_nama"] = row.get("jenis_izin", "")
        payload[f"ijin[{i}].chk_klasifikasi"] = normalize_sbu_classification(row.get("klasifikasi", ""))
    for prefix, items, selected in (("syaratAdmin", ctx["admin"], admin_ids), ("syaratTeknis", ctx["teknis"], teknis_ids)):
        for i, item in enumerate(items):
            payload[f"{prefix}[{i}].chk_id"] = item.get("chk_id", "")
        _set_selected(payload, prefix, items, selected)
        for i, item in enumerate(items):
            if str(item.get("ckm_id", "")) in {str(x) for x in selected}:
                payload[f"checklist_kualifikasi_{'administrasi' if prefix == 'syaratAdmin' else 'teknis'}_ckm_id[{i}]"] = item.get("ckm_id", "")
    if kinerja_text.strip():
        existing = next((i for i, item in enumerate(ctx["teknis"]) if str(item.get("ckm_id", "")) == "996"), None)
        index = existing if existing is not None else len(ctx["teknis"])
        payload[f"syaratTeknis[{index}].chk_id"] = ctx["teknis"][index].get("chk_id", "") if existing is not None else ""
        payload[f"syaratTeknis[{index}].ckm_id"] = "996"
        payload[f"checklist_kualifikasi_teknis_ckm_id[{index}]"] = "996"
        payload[f"syaratTeknis[{index}].chk_nama"] = kinerja_text.strip()
    resp = requests.post(ctx["submit"], data=payload, headers={**HEADERS, "Cookie": ctx["cookie"], "Referer": ctx["url"]}, allow_redirects=False, timeout=30)
    return {"ok": resp.status_code in (200, 302), "status": resp.status_code, "redirect": resp.headers.get("Location", "")}


def scrape_checklist(kode: str) -> dict:
    _, meta, form = _get_form(kode, "checklist", "checklistsubmit")
    items = _indexed_items(form, ("syaratAdmin", "syarat", "syaratHarga"))
    return {**meta, "admin": items["syaratAdmin"], "teknis": items["syarat"], "harga": items["syaratHarga"], "submit": f"{BASE}/dokumen/{kode}/checklistsubmit"}


def submit_checklist(kode: str, admin_ids: list[str], teknis_ids: list[str], harga_ids: list[str]) -> dict:
    soup, meta, form = _get_form(kode, "checklist", "checklistsubmit")
    items = _indexed_items(form, ("syaratAdmin", "syarat", "syaratHarga"))
    if not any(items.values()):
        raise RuntimeError("Field checklist SPSE tidak terbaca dari form.")
    ctx = {**meta, "admin": items["syaratAdmin"], "teknis": items["syarat"], "harga": items["syaratHarga"], "submit": f"{BASE}/dokumen/{kode}/checklistsubmit"}
    payload = {"authenticityToken": ctx["token"], "simpan": "simpan", **_hidden_payload(form)}
    for prefix, items, selected in (("syaratAdmin", ctx["admin"], admin_ids), ("syarat", ctx["teknis"], teknis_ids), ("syaratHarga", ctx["harga"], harga_ids)):
        for i, item in enumerate(items):
            payload[f"{prefix}[{i}].chk_id"] = item.get("chk_id", "")
        _set_selected(payload, prefix, items, selected)
    resp = requests.post(ctx["submit"], data=payload, headers={**HEADERS, "Cookie": ctx["cookie"], "Referer": ctx["url"]}, allow_redirects=False, timeout=30)
    return {"ok": resp.status_code in (200, 302), "status": resp.status_code, "redirect": resp.headers.get("Location", "")}


def submit_masa_berlaku(kode: str, hari: int) -> dict:
    _, meta, form = _get_form(kode, "masaberlakupenawaran", "masaberlakupenawaransubmit")
    payload = {"authenticityToken": meta["token"], "masaberlaku": str(hari)}
    action = f"{BASE}/dokumen/{kode}/masaberlakupenawaransubmit"
    resp = requests.post(action, data=payload, headers={**HEADERS, "Cookie": meta["cookie"], "Referer": meta["url"]}, allow_redirects=False, timeout=30)
    return {"ok": resp.status_code in (200, 302), "status": resp.status_code, "redirect": resp.headers.get("Location", "")}
