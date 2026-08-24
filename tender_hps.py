"""Helper HPS Tender yang dipakai lintas-tab Streamlit."""

import os


def find_tender_xlsm(folder_paket: str) -> str:
    """Cari workbook Tender di root folder paket; utamakan ``0. BAPK``."""
    try:
        files = [
            os.path.join(folder_paket, name)
            for name in os.listdir(folder_paket)
            if os.path.isfile(os.path.join(folder_paket, name))
            and name.casefold().endswith(".xlsm")
        ]
    except (OSError, TypeError):
        return ""

    files.sort(key=lambda path: os.path.basename(path).casefold())
    preferred = [
        path for path in files
        if os.path.basename(path).casefold().startswith("0. bapk")
    ]
    return (preferred or files)[0] if (preferred or files) else ""


def update_hps_tender(kode_tender: str, folder_paket: str, progress_cb=None) -> dict:
    """Ambil HPS SPSE lalu tulis ke Sheet ``5. HPS`` workbook paket.

    Penulisan tetap didelegasikan ke writer resmi ``hps_engine`` (Excel COM).
    Fungsi ini hanya menyatukan resolver workbook dan error contract agar bisa
    dipakai Tab 0 maupun Tab 6 tanpa membuat jalur penulisan kedua.
    """
    excel_path = find_tender_xlsm(folder_paket)
    if not excel_path:
        return {
            "ok": False,
            "pesan": "File .xlsm Tender tidak ditemukan di root folder paket",
            "count": 0,
            "excel_path": "",
        }

    try:
        import hps_engine

        result = hps_engine.scrape_hps_ke_excel(
            kode_tender,
            excel_path,
            progress_cb=progress_cb,
        )
    except Exception as exc:
        return {
            "ok": False,
            "pesan": str(exc),
            "count": 0,
            "excel_path": excel_path,
        }

    if not isinstance(result, dict):
        result = {"ok": False, "pesan": "Writer HPS mengembalikan hasil tidak valid", "count": 0}
    result.setdefault("excel_path", excel_path)
    return result
