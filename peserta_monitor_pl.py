"""
Monitor jumlah peserta yang sudah mendaftar di paket PL (non-tender).
Pakai endpoint public SPSE — tidak butuh login.
"""

import requests
import time
from bs4 import BeautifulSoup
from typing import List, Dict
from concurrent.futures import ThreadPoolExecutor, as_completed

_SPSE_BASE = "https://spse.inaproc.id/tapinkab"
_HEADERS = {"User-Agent": "Mozilla/5.0"}
_RETRYABLE_STATUS = {404, 408, 425, 429, 500, 502, 503, 504}
_RETRY_ATTEMPTS = 3
_RETRY_BACKOFF_SECONDS = 0.75


def fetch_jumlah_peserta_pl(kode_nontender: str) -> Dict:
    """
    GET public endpoint /nontender/{kode}/peserta.
    Return: {"jumlah": int, "error": str|None}
    """
    url = f"{_SPSE_BASE}/nontender/{kode_nontender}/peserta"
    last_error = None
    for attempt in range(_RETRY_ATTEMPTS):
        try:
            r = requests.get(url, headers=_HEADERS, timeout=15)
            if r.status_code == 200:
                soup = BeautifulSoup(r.text, "html.parser")
                tbl = soup.find("table")
                if not tbl:
                    return {"jumlah": 0, "error": None}
                rows = tbl.find("tbody").find_all("tr") if tbl.find("tbody") else []
                # Filter baris kosong
                jumlah = sum(1 for row in rows if row.find("td"))
                return {"jumlah": jumlah, "error": None}

            last_error = f"HTTP {r.status_code}"
            if r.status_code not in _RETRYABLE_STATUS:
                break
        except requests.RequestException as exc:
            last_error = str(exc)
        if attempt + 1 < _RETRY_ATTEMPTS:
            time.sleep(_RETRY_BACKOFF_SECONDS * (attempt + 1))
    return {"jumlah": 0, "error": last_error or "Gagal membaca jumlah peserta"}


def fetch_status_semua_paket(kode_list: List[str]) -> Dict[str, Dict]:
    """
    Fetch jumlah peserta untuk semua paket sekaligus.
    Return: {kode_nontender: {"jumlah": int, "error": str|None}}
    """
    kode_unik = list(dict.fromkeys(str(k) for k in kode_list if k))
    hasil = {}
    if not kode_unik:
        return hasil
    # SPSE mudah mengembalikan timeout/404 intermiten bila endpoint peserta
    # ditembak terlalu paralel. Retry per paket + concurrency kecil lebih stabil.
    with ThreadPoolExecutor(max_workers=min(3, len(kode_unik))) as pool:
        futures = {pool.submit(fetch_jumlah_peserta_pl, kode): kode for kode in kode_unik}
        for future in as_completed(futures):
            kode = futures[future]
            try:
                hasil[kode] = future.result()
            except Exception as exc:
                hasil[kode] = {"jumlah": 0, "error": str(exc)}
    return hasil
