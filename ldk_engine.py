"""
LDK Engine v4 — Pure requests, tanpa Playwright click.

Flow:
1. GET /dokumen/[ID]/ldk  → ambil authenticityToken + hidden IDs
2. Build payload (checkbox + izin usaha + kinerja)
3. POST /dokumen/[ID]/ldksubmitbaru  → 302 = sukses
"""

import re
import requests
from bs4 import BeautifulSoup
from ldk_config import AUTO_CHECK_KEYWORDS, CHECK_AND_FILL, SKIP_KEYWORDS, IJIN_USAHA_DEFAULT
import spse_browser

BASE_URL = "https://spse.inaproc.id/tapinkab"
HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/120.0.0.0",
    "Origin": "https://spse.inaproc.id",
    "Content-Type": "application/x-www-form-urlencoded",
}


# ─────────────────────────────────────────────────────────────────────────────
# Scrape halaman LDK via requests
# ─────────────────────────────────────────────────────────────────────────────

def scrape_ldk_page(paket_id: str) -> dict:
    """
    GET halaman LDK dan parse semua data yang diperlukan untuk submit.
    Return dict berisi: token, hidden_ids, checkboxes, action_url.
    """
    cookie_str = spse_browser.get_spse_cookies()
    url = f"{BASE_URL}/dokumen/{paket_id}/ldk"
    resp = requests.get(url, headers={**HEADERS_BASE, "Cookie": cookie_str}, timeout=20)
    if resp.status_code != 200:
        raise RuntimeError(f"GET halaman LDK gagal: status {resp.status_code}")

    html = resp.text
    soup = BeautifulSoup(html, "html.parser")

    # authenticityToken
    token_input = soup.find("input", {"name": "authenticityToken"})
    token = token_input["value"] if token_input else ""

    # Hidden IDs: ijin, syaratAdmin, syaratTeknis + ckm_id
    hidden = {}
    for inp in soup.find_all("input", type="hidden"):
        name = inp.get("name", "")
        if name and any(x in name for x in ["chk_id", "ckm_id", "checklist_kualifikasi", "syarat_ijin"]):
            hidden[name] = inp.get("value", "")

    # Checkbox info: name, value, label, disabled
    checkboxes = []
    for cb in soup.find_all("input", type="checkbox"):
        cb_name  = cb.get("name", "")
        cb_value = cb.get("value", "")
        disabled = cb.has_attr("disabled")
        checked  = cb.has_attr("checked")
        is_kso   = "kso" in cb.get("class", [])

        # Label: cari <td> saudara berikutnya di <tr> yang sama
        label = ""
        tr = cb.find_parent("tr")
        if tr:
            tds = tr.find_all("td")
            for td in tds:
                if not td.find("input", {"name": cb_name}):
                    label = td.get_text(separator=" ").strip()
                    label = re.sub(r'\s+', ' ', label)
                    break

        checkboxes.append({
            "name":     cb_name,
            "value":    cb_value,
            "disabled": disabled,
            "checked":  checked,
            "label":    label,
            "is_kso":   is_kso,
        })

    # Hitung index syaratTeknis berikutnya untuk row kinerja baru
    teknis_count = len([
        cb for cb in soup.find_all("input", type="checkbox")
        if cb.get("name", "").startswith("syaratTeknis[")
    ])

    return {
        "token": token,
        "hidden": hidden,
        "checkboxes": checkboxes,
        "teknis_count": teknis_count,
        "action_url": f"{BASE_URL}/dokumen/{paket_id}/ldksubmitbaru",
        "referer_url": url,
        "cookie": cookie_str,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Klasifikasi checkbox
# ─────────────────────────────────────────────────────────────────────────────

def _matches(label: str, keywords: list[str]) -> bool:
    label_lower = label.lower()
    return any(kw.lower() in label_lower for kw in keywords)


def classify_checkboxes(checkboxes: list[dict]) -> dict:
    result = {"locked": [], "auto_check": [], "check_and_fill": [], "skip": [], "unknown": []}

    for cb in checkboxes:
        if cb["disabled"] or cb.get("is_kso", False):
            result["locked"].append(cb)
            continue
        if _matches(cb["label"], SKIP_KEYWORDS):
            result["skip"].append(cb)
            continue
        matched_fill = False
        for cfg in CHECK_AND_FILL:
            if cfg["keyword"].lower() in cb["label"].lower():
                result["check_and_fill"].append((cb, cfg))
                matched_fill = True
                break
        if matched_fill:
            continue
        if _matches(cb["label"], AUTO_CHECK_KEYWORDS):
            result["auto_check"].append(cb)
            continue
        result["unknown"].append(cb)

    return result


# ─────────────────────────────────────────────────────────────────────────────
# Build payload
# ─────────────────────────────────────────────────────────────────────────────

def build_payload(
    scraped: dict,
    classified: dict,
    ijin_usaha_rows: list[dict] | None = None,
    kinerja_text: str = "",
) -> dict:
    payload = {}
    hidden = scraped["hidden"]

    # Token
    if scraped["token"]:
        payload["authenticityToken"] = scraped["token"]

    # Semua hidden fields (chk_id, ckm_id, dll) — wajib disertakan
    payload.update(hidden)

    # Auto-check: tambahkan nilai checkbox ke payload
    for cb in classified["auto_check"]:
        payload[cb["name"]] = cb["value"]

    # Check + fill
    for cb, cfg in classified["check_and_fill"]:
        payload[cb["name"]] = cb["value"]

    # Multi-row Izin Usaha
    rows = ijin_usaha_rows or IJIN_USAHA_DEFAULT["rows"]
    for i, row in enumerate(rows):
        payload[f"ijin[{i}].chk_nama"] = row.get("jenis_izin", "")
        payload[f"ijin[{i}].chk_klasifikasi"] = row.get("klasifikasi", "")

    # Kinerja Penyedia — tambah row baru syaratTeknis dengan ckm_id=996
    # Row ini dibuat client-side saat klik "Tambah Syarat Teknis",
    # cukup sertakan di payload dengan index berikutnya
    if kinerja_text:
        n = scraped.get("teknis_count", 5)
        payload[f"syaratTeknis[{n}].ckm_id"] = "996"
        payload[f"checklist_kualifikasi_teknis_ckm_id[{n}]"] = "996"
        payload[f"syaratTeknis[{n}].chk_nama"] = kinerja_text

    return payload


# ─────────────────────────────────────────────────────────────────────────────
# Submit
# ─────────────────────────────────────────────────────────────────────────────

def submit_ldk(
    paket_id: str,
    ijin_usaha_rows: list[dict] | None = None,
    kinerja_text: str = "",
) -> dict:
    """
    Submit LDK via direct HTTP POST.
    1. GET halaman LDK → ambil token + hidden IDs
    2. Build payload
    3. POST → 302 = sukses
    """
    # Step 1: Scrape
    scraped = scrape_ldk_page(paket_id)
    if not scraped["token"]:
        raise RuntimeError("authenticityToken tidak ditemukan di halaman LDK.")

    # Step 2: Classify & build
    classified = classify_checkboxes(scraped["checkboxes"])
    payload = build_payload(scraped, classified, ijin_usaha_rows, kinerja_text)

    # Step 3: POST
    headers = {
        **HEADERS_BASE,
        "Cookie": scraped["cookie"],
        "Referer": scraped["referer_url"],
    }
    resp = requests.post(
        scraped["action_url"],
        data=payload,
        headers=headers,
        allow_redirects=False,
        timeout=20,
    )

    ok = resp.status_code in (200, 302)
    return {
        "ok": ok,
        "status": resp.status_code,
        "url": resp.headers.get("Location", scraped["referer_url"]),
        "classified": classified,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Preview (dry-run tanpa submit)
# ─────────────────────────────────────────────────────────────────────────────

def preview_ldk(paket_id: str) -> dict:
    """Scrape + classify saja, tanpa submit. Untuk preview di UI."""
    scraped = scrape_ldk_page(paket_id)
    classified = classify_checkboxes(scraped["checkboxes"])
    return {"scraped": scraped, "classified": classified}
