"""
pilih_penyedia_pl.py — Pilih penyedia PL ke SPSE via direct HTTP API.

Endpoint: GET /pilihpenyedia/{kode}?search=true&nama=...&npwp=...
Submit:   POST /action/nonlelang.pengadaanlctr/simpanpilihpenyedia?lelangId={kode}

Data rekanan (rkn_id, rkn_nama, rkn_npwp_16, dll) tersedia di HTML response GET,
sehingga bisa dipakai requests biasa tanpa Playwright.
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
      {"ok": True, "nama": "...", "mode": "npwp_exact|nama_exact|..."}
      {"ok": False, "pesan": "Tidak ditemukan / error"}
    """
    if not npwp and not nama_penyedia:
        return {"ok": False, "pesan": "NPWP dan nama penyedia kosong"}
    # cookie_str dari caller (sudah di-cache) → skip get_spse_cookies() dalam loop
    return _sb.pilih_penyedia_via_api(
        kode_paket, npwp.strip(), base_url,
        nama_penyedia=nama_penyedia,
        cookie_str=cookie_str or "",
    )
