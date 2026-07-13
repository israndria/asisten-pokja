"""Engine input hasil negosiasi dan penetapan pemenang PL."""

import json
import re
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import SPSE_BASE_URL


def _headers(cookie: str, referer: str = "") -> dict:
    h = {"Cookie": cookie, "User-Agent": "Mozilla/5.0"}
    if referer:
        h["Referer"] = referer
    return h


def _json_array_from_script(html: str) -> list:
    """Ambil array data Handsontable dari konfigurasi JS inline."""
    for match in re.finditer(r"\b(?:data|dataSet)\s*:\s*\[", html):
        start = html.find("[", match.start())
        try:
            value, _ = json.JSONDecoder().raw_decode(html[start:])
            if isinstance(value, list):
                return value
        except (ValueError, json.JSONDecodeError):
            continue
    return []


def scrape_peserta(kode_paket: str, cookie: str) -> dict:
    url = f"{SPSE_BASE_URL}evaluasinontender/{kode_paket}"
    try:
        r = requests.get(url, headers=_headers(cookie), timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        peserta = []
        for a in soup.select('a[href*="/evaluasinontender/"][href*="/detail"]'):
            m = re.search(r"/evaluasinontender/(\d+)/detail", a.get("href", ""))
            if m and not any(x["id_nontender"] == m.group(1) for x in peserta):
                peserta.append({"id_nontender": m.group(1), "nama": a.get_text(" ", strip=True)})
        return {"ok": bool(peserta), "peserta": peserta, "pesan": "" if peserta else "Peserta tidak ditemukan"}
    except Exception as e:
        return {"ok": False, "peserta": [], "pesan": f"Gagal membaca peserta: {e}"}


def scrape_negosiasi(id_nontender: str, cookie: str) -> dict:
    url = f"{SPSE_BASE_URL}evaluasinontender/{id_nontender}/negosiasi"
    try:
        r = requests.get(url, headers=_headers(cookie), timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        token = next((x.get("value", "") for x in soup.select('input[name="authenticityToken"]')), "")
        data = _json_array_from_script(r.text)
        if not data:
            # Be tolerant of a server-rendered table or a JS variable named postdata.
            table = soup.select_one("#tbl-rincian")
            if table:
                data = [[c.get_text(" ", strip=True) for c in row.select("th,td")] for row in table.select("tr")]
        if not token:
            return {"ok": False, "data": [], "token": "", "pesan": "Token negosiasi tidak ditemukan"}
        if not data:
            return {"ok": False, "data": [], "token": token, "pesan": "Rincian negosiasi tidak ditemukan di halaman"}
        return {"ok": True, "data": data, "token": token, "pesan": ""}
    except Exception as e:
        return {"ok": False, "data": [], "token": "", "pesan": f"Gagal membaca negosiasi: {e}"}


def submit_negosiasi(id_nontender: str, token: str, data: list, cookie: str) -> dict:
    url = f"{SPSE_BASE_URL}evaluasinontender/{id_nontender}/submit_negosiasi"
    try:
        r = requests.post(
            url,
            data={"authenticityToken": token, "data": json.dumps(data, ensure_ascii=False)},
            headers={**_headers(cookie, url), "X-Requested-With": "XMLHttpRequest"},
            timeout=20,
            allow_redirects=False,
        )
        ok = r.status_code in (200, 302)
        return {"ok": ok, "pesan": f"HTTP {r.status_code}" + (" — hasil negosiasi tersimpan" if ok else "")}
    except Exception as e:
        return {"ok": False, "pesan": f"Submit negosiasi gagal: {e}"}


def submit_negosiasi_dan_penetapan_pl(kode_paket: str, cookie: str) -> dict:
    """Submit negosiasi lalu penetapan untuk PL satu peserta."""
    peserta_result = scrape_peserta(kode_paket, cookie)
    if not peserta_result.get("ok"):
        return {"ok": False, "pesan": peserta_result.get("pesan", "Peserta tidak ditemukan")}
    peserta = peserta_result.get("peserta", [])
    if len(peserta) != 1:
        return {"ok": False, "pesan": f"Ditemukan {len(peserta)} peserta; flow otomatis hanya untuk tepat 1 peserta."}

    peserta_id = peserta[0]["id_nontender"]
    nego = scrape_negosiasi(peserta_id, cookie)
    if not nego.get("ok"):
        return {"ok": False, "pesan": f"Negosiasi: {nego.get('pesan', 'gagal membaca rincian')}"}
    submit_nego = submit_negosiasi(peserta_id, nego["token"], nego["data"], cookie)
    if not submit_nego.get("ok"):
        return {"ok": False, "pesan": f"Negosiasi: {submit_nego.get('pesan', 'submit gagal')}"}

    penetapan = scrape_penetapan(kode_paket, cookie)
    if not penetapan.get("ok"):
        return {"ok": False, "pesan": f"Penetapan: {penetapan.get('pesan', 'form tidak ditemukan')}"}
    submit_pen = submit_penetapan(kode_paket, penetapan, cookie)
    if not submit_pen.get("ok"):
        return {"ok": False, "pesan": f"Penetapan: {submit_pen.get('pesan', 'submit gagal')}"}
    return {"ok": True, "pesan": f"{peserta[0]['nama']}: negosiasi dan penetapan berhasil"}


def scrape_penetapan(kode_paket: str, cookie: str) -> dict:
    url = f"{SPSE_BASE_URL}evaluasinontender/{kode_paket}/penetapan"
    try:
        r = requests.get(url, headers=_headers(cookie), timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        form = next((f for f in soup.find_all("form") if f.find("input", {"name": "authenticityToken"})), None)
        if not form:
            return {"ok": False, "token": "", "action": url, "peserta": [], "pesan": "Form penetapan tidak ditemukan"}
        peserta = []
        for row in form.select("table tr"):
            cells = row.find_all("td")
            if len(cells) >= 2:
                nama = cells[1].get_text(" ", strip=True)
                if nama:
                    peserta.append({"urutan": len(peserta) + 1, "nama": nama})
        hidden = {x.get("name"): x.get("value", "") for x in form.select('input[type="hidden"][name]')}
        action = urljoin(url, form.get("action") or url)
        return {"ok": True, "token": hidden.get("authenticityToken", ""), "action": action, "peserta": peserta, "hidden": hidden, "pesan": ""}
    except Exception as e:
        return {"ok": False, "token": "", "action": url, "peserta": [], "pesan": f"Gagal membaca penetapan: {e}"}


def submit_penetapan(kode_paket: str, form_data: dict, cookie: str) -> dict:
    url = form_data.get("action") or f"{SPSE_BASE_URL}evaluasinontender/{kode_paket}/submit_penetapan"
    payload = dict(form_data.get("hidden") or {})
    payload["authenticityToken"] = form_data.get("token") or payload.get("authenticityToken", "")
    payload["allowfailedchekblacklist"] = "1"
    payload.setdefault("simpan", "simpan")
    try:
        r = requests.post(url, files={k: (None, str(v)) for k, v in payload.items()}, headers=_headers(cookie, url), timeout=20, allow_redirects=False)
        ok = r.status_code in (200, 302) and "login" not in r.headers.get("Location", "").lower()
        return {"ok": ok, "pesan": f"HTTP {r.status_code}" + (" — penetapan tersimpan" if ok else "")}
    except Exception as e:
        return {"ok": False, "pesan": f"Submit penetapan gagal: {e}"}
