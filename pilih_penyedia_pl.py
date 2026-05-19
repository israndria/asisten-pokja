"""
pilih_penyedia_pl.py — Pilih penyedia PL ke SPSE via Playwright browser CDP.

Data penyedia di-render via JavaScript sehingga requests biasa tidak bisa ambil
rkn_id. Pakai Playwright (browser yang sudah login) untuk search + submit.
"""

import spse_browser as _sb


def cari_dan_pilih_penyedia(
    kode_paket: str,
    npwp: str,
    cookie_str: str,   # tidak dipakai, kept untuk backward compat
    base_url: str,
    nama_penyedia: str = "",
) -> dict:
    """
    Cari penyedia by NPWP (fallback nama) via SPSE, pilih ke paket.

    Return:
      {"ok": True, "nama": "...", "kabupaten_id": "22"}
      {"ok": False, "pesan": "Tidak ditemukan / error"}
    """
    if not npwp and not nama_penyedia:
        return {"ok": False, "pesan": "NPWP dan nama penyedia kosong"}
    return _sb.pilih_penyedia_via_playwright(
        kode_paket, npwp.strip(), base_url, nama_penyedia=nama_penyedia
    )
