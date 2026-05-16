"""
inspect_pl_latihan.py — Bedah form LDK + masa berlaku + upload dokpil di SPSE latihan (eproc.dev).

Goal:
1. List paket PL di latihan via /dt/paketpp
2. GET /ldknontender/{id}/edit -> inspect semua checkbox ckm_id teknis a-d + admin (root cause kenapa cuma kinerja yang tercentang)
3. GET /dokumennontender/{id}/edit -> inspect form upload Dokpil PDF + field
4. GET form masa berlaku penawaran + dokumen penawaran
"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import re
import json
import requests
from bs4 import BeautifulSoup

# Latihan base URL
BASE = "https://spse.eproc.dev/latihan"

# Cookie latihan
COOKIE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "_eproc_dev_cookies.txt")
with open(COOKIE_FILE, "r", encoding="utf-8") as f:
    COOKIE = f.read().strip()

HDRS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml",
    "Referer": BASE + "/admin/pegawai",
    "Cookie": COOKIE,
}


def list_paket_pl():
    """List paket PL di latihan via dt/paketpp."""
    url = f"{BASE}/dt/paketpp"
    r = requests.get(url, headers=HDRS, timeout=30)
    print(f"List paket PL: HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        print(r.text[:500])
        return []
    try:
        d = r.json()
        rows = d.get("data", [])
        print(f"Total paket: {len(rows)}")
        for row in rows[:15]:
            print(f"  id={row[0]} | kode={row[5]} | nama={row[1][:50] if len(row) > 1 else ''}")
        return rows
    except Exception as e:
        print(f"JSON parse fail: {e}")
        print(r.text[:500])
        return []


def inspect_ldk_form(id_nontender: str):
    """GET /dokumennontender/{id}/ldk -> list semua field/checkbox/ckm_id."""
    url = f"{BASE}/dokumennontender/{id_nontender}/ldk"
    print(f"\n=== GET {url} ===")
    r = requests.get(url, headers=HDRS, timeout=30)
    print(f"HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        print(r.text[:500])
        return

    # Save full HTML for offline inspect
    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"_pl_ldk_{id_nontender}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"  saved -> {out}")

    soup = BeautifulSoup(r.text, "html.parser")

    # Form ldk
    form = None
    for f in soup.find_all("form"):
        action = (f.get("action") or "")
        if "simpan" in action.lower() or "ldk" in action.lower():
            form = f
            print(f"  Form action: {action}")
            break
    if not form:
        # Fallback: ambil semua form
        for f in soup.find_all("form"):
            print(f"  Form found: action={f.get('action')}")
        return

    # CSRF
    csrf_inp = form.find("input", {"name": "authenticityToken"})
    if csrf_inp:
        print(f"  CSRF: {csrf_inp['value'][:30]}...")

    # Semua checkbox
    print("\n  === ALL CHECKBOXES ===")
    cbs = form.find_all("input", {"type": "checkbox"})
    print(f"  Total checkbox: {len(cbs)}")
    for cb in cbs[:50]:
        name = cb.get("name", "")
        val = cb.get("value", "")
        checked = cb.has_attr("checked")
        # Cari label
        label_text = ""
        # parent atau next sibling
        parent_tr = cb.find_parent("tr")
        if parent_tr:
            tds = parent_tr.find_all("td")
            if len(tds) >= 2:
                label_text = tds[1].get_text(strip=True)[:80]
        print(f"    name={name} | value={val} | checked={checked} | label={label_text}")

    # Semua hidden input
    print("\n  === ALL HIDDEN INPUT (sample) ===")
    hiddens = form.find_all("input", {"type": "hidden"})
    print(f"  Total hidden: {len(hiddens)}")
    for h in hiddens[:30]:
        print(f"    {h.get('name', '')} = {(h.get('value') or '')[:60]}")


def inspect_dokumennontender_edit(id_nontender: str):
    """GET /dokumennontender/{id}/edit -> form upload dokpil + masa berlaku."""
    url = f"{BASE}/dokumennontender/{id_nontender}/edit"
    print(f"\n=== GET {url} ===")
    r = requests.get(url, headers=HDRS, timeout=30)
    print(f"HTTP {r.status_code}, len={len(r.text)}")
    if r.status_code != 200:
        print(r.text[:500])
        return

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)), f"_pl_dokumen_{id_nontender}.html")
    with open(out, "w", encoding="utf-8") as f:
        f.write(r.text)
    print(f"  saved -> {out}")

    soup = BeautifulSoup(r.text, "html.parser")

    # Semua form
    print("\n  === ALL FORMS ===")
    for i, frm in enumerate(soup.find_all("form")):
        print(f"  [{i}] action={frm.get('action')} | enctype={frm.get('enctype')}")
        # File input
        files = frm.find_all("input", {"type": "file"})
        if files:
            for fi in files:
                print(f"    FILE: name={fi.get('name')} | accept={fi.get('accept')}")
        # Tombol Upload
        for btn in frm.find_all(["button", "input"]):
            t = (btn.get("type") or "").lower()
            txt = btn.get_text(strip=True) or btn.get("value", "")
            if t in {"submit"} or "upload" in txt.lower() or "simpan" in txt.lower():
                print(f"    BTN: type={t} | text={txt}")

    # Cari semua link/href yang mengarah ke upload
    print("\n  === LINKS w/ 'upload' or 'dokpil' ===")
    for a in soup.find_all("a"):
        href = a.get("href") or ""
        txt = a.get_text(strip=True)
        if "upload" in href.lower() or "dokpil" in href.lower() or "upload" in txt.lower():
            print(f"    {txt[:40]} -> {href}")

    # Cari masa berlaku
    print("\n  === FIELDS w/ 'masa' or 'berlaku' ===")
    for inp in soup.find_all(["input", "select", "textarea"]):
        name = (inp.get("name") or "")
        if "masa" in name.lower() or "berlaku" in name.lower():
            print(f"    name={name} | type={inp.get('type')} | value={inp.get('value')}")


if __name__ == "__main__":
    if len(sys.argv) >= 2:
        action = sys.argv[1]
        if action == "list":
            list_paket_pl()
        elif action == "ldk":
            inspect_ldk_form(sys.argv[2])
        elif action == "dok":
            inspect_dokumennontender_edit(sys.argv[2])
    else:
        # Default: list paket lalu inspect 1
        rows = list_paket_pl()
        if rows:
            first_id = rows[0][0]
            print(f"\n-> Inspect paket pertama: {first_id}")
            inspect_ldk_form(first_id)
            inspect_dokumennontender_edit(first_id)
