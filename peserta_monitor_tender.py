"""
peserta_monitor_tender.py — Monitor jumlah peserta tender dari SPSE.

Endpoint: /tapinkab/lelang/{kode_tender}/peserta
Butuh akun login — fetch via JS dari tab browser yang sudah login (CDP).
"""

from bs4 import BeautifulSoup
from typing import List, Dict

_SPSE_BASE = "https://spse.inaproc.id"
_KODE_LPSE = "tapinkab"


def _parse_html_peserta(html: str, kode_tender: str) -> Dict:
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.find("table")
    if not tbl:
        return {"kode_tender": kode_tender, "jumlah": 0, "peserta": [], "error": None}

    tbody = tbl.find("tbody")
    rows = tbody.find_all("tr") if tbody else tbl.find_all("tr")[1:]

    peserta = []
    for row in rows:
        cols = row.find_all("td")
        if not cols:
            continue
        nama = cols[1].get_text(strip=True) if len(cols) > 1 else ""
        npwp = cols[2].get_text(strip=True) if len(cols) > 2 else ""
        is_pemenang = "pemenang" in " ".join(row.get("class", [])).lower()
        if nama:
            peserta.append({"nama": nama, "npwp": npwp, "is_pemenang": is_pemenang})

    return {"kode_tender": kode_tender, "jumlah": len(peserta), "peserta": peserta, "error": None}


def _get_active_spse_page():
    """Ambil tab SPSE yang sudah login dari CDP context."""
    import spse_browser as _sb
    if not _sb._cek_cdp_aktif():
        return None, "Chrome CDP tidak aktif — buka 'Buka Chrome SPSE.bat' dulu"
    if _sb._get_ctx() is None:
        try:
            _sb.buka_browser(navigate=False)
        except Exception as e:
            return None, str(e)
    if _sb._get_ctx() is None:
        return None, "CDP tidak tersambung"

    pages = _sb._get_ctx().pages
    # Pilih tab yang sedang di SPSE
    spse_page = next((p for p in pages if _SPSE_BASE in p.url), None)
    if spse_page is None and pages:
        spse_page = pages[0]
    return spse_page, None


def fetch_peserta_tender(kode_tender: str) -> Dict:
    """
    Fetch daftar peserta via JS fetch() dari tab browser yang sudah login SPSE.

    Returns:
        {
            "kode_tender": str,
            "jumlah": int,
            "peserta": [{"nama": str, "npwp": str, "is_pemenang": bool}],
            "error": str | None,
        }
    """
    try:
        import spse_browser as _sb

        page, err = _get_active_spse_page()
        if err:
            return {"kode_tender": kode_tender, "jumlah": 0, "peserta": [], "error": err}

        url = f"{_SPSE_BASE}/{_KODE_LPSE}/lelang/{kode_tender}/peserta"

        async def _fetch():
            result = await page.evaluate(
                """async (url) => {
                    const r = await fetch(url, {credentials: 'include'});
                    return {status: r.status, text: await r.text()};
                }""",
                url,
            )
            return result

        result = _sb._run(_fetch(), timeout=20)
        if result["status"] not in (200, 500):
            return {"kode_tender": kode_tender, "jumlah": 0, "peserta": [],
                    "error": f"HTTP {result['status']}"}

        return _parse_html_peserta(result["text"], kode_tender)

    except Exception as e:
        return {"kode_tender": kode_tender, "jumlah": 0, "peserta": [], "error": str(e)}


def fetch_semua_paket(kode_list: List[str]) -> Dict[str, Dict]:
    """
    Sequential fetch peserta untuk banyak paket.
    Returns: {kode_tender: hasil_fetch}
    """
    hasil = {}
    for k in kode_list:
        hasil[k] = fetch_peserta_tender(k)
    return hasil
