"""
inspect_pl_production.py — Bedah ulang form LDK + Checklist + Upload Dokpil di akun PP PRODUCTION.

Sesi 43 ckm_id JKK didapat dari latihan (eproc.dev). User cek di prod (spse.inaproc.id/tapinkab):
  - SBU tercentang OK
  - Penilaian Kinerja TIDAK tercentang & TIDAK terisi
=> kemungkinan ckm_id production beda dgn latihan. Bedah ulang.

Usage:
    python scratch/inspect_pl_production.py list
    python scratch/inspect_pl_production.py ldk <id_nontender>
    python scratch/inspect_pl_production.py dok <id_nontender>
    python scratch/inspect_pl_production.py checklist <kode_paket>
    python scratch/inspect_pl_production.py upload <id_nontender>
    python scratch/inspect_pl_production.py edit <id_nontender>

Cookie diambil otomatis dari Chrome via spse_browser.get_spse_cookies().
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import requests
from bs4 import BeautifulSoup

import spse_browser
from config import SPSE_BASE_URL

BASE = SPSE_BASE_URL.rstrip("/")
SCRATCH = os.path.dirname(os.path.abspath(__file__))


def _hdrs():
    cookie = spse_browser.get_spse_cookies()
    if not cookie:
        print("[ERROR] Cookie SPSE kosong. Pastikan Chrome CDP nyala + login SPSE.")
        sys.exit(1)
    return {
        "User-Agent": "Mozilla/5.0",
        "Accept": "text/html,application/xhtml+xml",
        "Referer": BASE + "/admin/pegawai",
        "Cookie": cookie,
    }


def list_paket_pl():
    """List paket PL via /dt/paketpp."""
    url = f"{BASE}/dt/paketpp"
    r = requests.get(url, headers=_hdrs(), timeout=30)
    print(f"List paket PL: HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        print(r.text[:500])
        return []
    try:
        d = r.json()
        rows = d.get("data", [])
        print(f"Total paket: {len(rows)}")
        for row in rows[:30]:
            kode = row[5] if len(row) > 5 else ""
            nama = row[1][:60] if len(row) > 1 else ""
            print(f"  id={row[0]} | kode={kode} | nama={nama}")
        return rows
    except Exception as e:
        print(f"JSON parse fail: {e}")
        print(r.text[:500])
        return []


def inspect_ldk_form(id_or_kode: str):
    """GET /dokumennontender/{kode}/ldk -> list semua ckm_id."""
    url = f"{BASE}/dokumennontender/{id_or_kode}/ldk"
    print(f"\n=== GET {url} ===")
    r = requests.get(url, headers=_hdrs(), timeout=30)
    print(f"HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        print(r.text[:800])
        return

    out = os.path.join(SCRATCH, f"_prod_ldk_{id_or_kode}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"  saved -> {out}")

    soup = BeautifulSoup(r.text, "html.parser")

    form = None
    for f in soup.find_all("form"):
        action = (f.get("action") or "")
        if "ldksubmit" in action.lower() or "simpan" in action.lower():
            form = f
            print(f"  Form action: {action}")
            break
    if not form:
        forms = soup.find_all("form")
        if not forms:
            print("  Tidak ada form di halaman")
            return
        form = forms[0]
        print(f"  Fallback form pertama: action={form.get('action')}")

    csrf_inp = form.find("input", {"name": "authenticityToken"})
    if csrf_inp:
        print(f"  CSRF: {csrf_inp['value'][:40]}...")

    print("\n  === ALL CHECKBOXES ===")
    cbs = form.find_all("input", {"type": "checkbox"})
    print(f"  Total checkbox: {len(cbs)}")
    for cb in cbs:
        name = cb.get("name", "")
        val = cb.get("value", "")
        checked = cb.has_attr("checked")
        label_text = ""
        parent_tr = cb.find_parent("tr")
        if parent_tr:
            tds = parent_tr.find_all("td")
            if len(tds) >= 2:
                label_text = tds[1].get_text(" ", strip=True)[:120]
        print(f"    name={name!r:30s} value={val!r:8s} checked={checked} | {label_text}")

    print("\n  === ALL TEXT INPUT (sample) ===")
    texts = form.find_all("input", {"type": "text"})
    for t in texts[:40]:
        print(f"    name={t.get('name')!r:40s} value={(t.get('value') or '')[:60]}")

    print("\n  === ALL TEXTAREA ===")
    for ta in form.find_all("textarea"):
        print(f"    name={ta.get('name')!r:40s} value={(ta.text or '')[:80]}")


def inspect_checklist_form(kode_paket: str):
    """GET /dokumennontender/{kode}/checklist -> list checklist Dok Penawaran."""
    url = f"{BASE}/dokumennontender/{kode_paket}/checklist"
    print(f"\n=== GET {url} ===")
    r = requests.get(url, headers=_hdrs(), timeout=30)
    print(f"HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        print(r.text[:500])
        return
    out = os.path.join(SCRATCH, f"_prod_checklist_{kode_paket}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"  saved -> {out}")

    soup = BeautifulSoup(r.text, "html.parser")
    for frm in soup.find_all("form"):
        print(f"  Form: action={frm.get('action')}")
        cbs = frm.find_all("input", {"type": "checkbox"})
        for cb in cbs:
            name = cb.get("name", "")
            val = cb.get("value", "")
            checked = cb.has_attr("checked")
            label_text = ""
            parent_tr = cb.find_parent("tr")
            if parent_tr:
                tds = parent_tr.find_all("td")
                if len(tds) >= 2:
                    label_text = tds[1].get_text(" ", strip=True)[:120]
            print(f"    cb name={name!r} val={val!r} checked={checked} | {label_text}")


def inspect_upload_form(id_nontender: str):
    """GET /dokumennontender/{id_nontender}/uploaddoknontender -> form upload Dokpil."""
    url = f"{BASE}/dokumennontender/{id_nontender}/uploaddoknontender"
    print(f"\n=== GET {url} ===")
    r = requests.get(url, headers=_hdrs(), timeout=30)
    print(f"HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        print(r.text[:500])
        return
    out = os.path.join(SCRATCH, f"_prod_uploaddoknontender_{id_nontender}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"  saved -> {out}")

    soup = BeautifulSoup(r.text, "html.parser")
    for i, frm in enumerate(soup.find_all("form")):
        print(f"\n  [Form {i}] action={frm.get('action')} | enctype={frm.get('enctype')}")
        for inp in frm.find_all(["input", "select", "textarea"]):
            t = inp.get("type", inp.name)
            n = inp.get("name", "")
            v = (inp.get("value") or "")[:60]
            print(f"    {t!r:10s} name={n!r:30s} value={v!r}")


def inspect_edit_page(id_nontender: str):
    """GET /dokumennontender/{id_nontender}/edit -> list semua tombol Upload + form."""
    url = f"{BASE}/dokumennontender/{id_nontender}/edit"
    print(f"\n=== GET {url} ===")
    r = requests.get(url, headers=_hdrs(), timeout=30)
    print(f"HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        print(r.text[:500])
        return
    out = os.path.join(SCRATCH, f"_prod_edit_{id_nontender}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"  saved -> {out}")

    soup = BeautifulSoup(r.text, "html.parser")
    print("\n  === LINKS / TOMBOL UPLOAD ===")
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        txt = a.get_text(" ", strip=True)[:60]
        if "upload" in href.lower() or "upload" in txt.lower() or "ldk" in href.lower() or "checklist" in href.lower() or "masaberlaku" in href.lower():
            print(f"    [{txt}] -> {href}")

    print("\n  === ALL FORMS ===")
    for i, frm in enumerate(soup.find_all("form")):
        print(f"  [Form {i}] action={frm.get('action')} | enctype={frm.get('enctype')}")


def inspect_dokumen_edit(kode_paket: str):
    """GET /dokumennontender/{kode_paket}/edit -> sama dgn edit tapi pakai kode_paket."""
    inspect_edit_page(kode_paket)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(0)
    action = sys.argv[1]
    if action == "list":
        list_paket_pl()
    elif action == "ldk":
        inspect_ldk_form(sys.argv[2])
    elif action == "checklist":
        inspect_checklist_form(sys.argv[2])
    elif action == "upload":
        inspect_upload_form(sys.argv[2])
    elif action == "edit":
        inspect_edit_page(sys.argv[2])
    elif action == "dok":
        # legacy: alias edit
        inspect_edit_page(sys.argv[2])
    else:
        print(f"Unknown action: {action}")
        print(__doc__)
