"""isi_master_data_tender.py — Auto-isi sheet '@ Master Data' paket Tender via COM.

Trigger macro VBA `ModDraftPaket.IsiDataByKodeTender` (reuse 100% logika VBA:
lookup PPK, compose semua field dari Supabase draft_paket).

Dipanggil dari app.py saat buat folder Tender (single/bulk), setelah setup folder.
Menggantikan alur manual dropdown F1 + MuatDraftPaket + PilihDraftPaket di Excel.
"""

import os


def proses_master_data_tender(kode_tender: str, excel_path: str, progress_cb=None, xl=None) -> dict:
    """1 sesi COM: SetSilentTender + IsiDataByKodeTender — entry point utama dari app.py.

    Dipakai oleh _proses_excel_paket_tender() di app.py saat bulk-create folder Tender.

    Args:
        kode_tender: kode tender (string, format 10072844000).
        excel_path:  path absolut file .xlsm yang sudah di-copy dari template.
        progress_cb: callable(str) opsional untuk log progres.

    Return: {"ok": bool, "pesan": str}
    """
    def _log(m):
        if progress_cb:
            try:
                progress_cb(m)
            except Exception:
                pass

    excel_path = os.path.abspath(excel_path)
    if not os.path.isfile(excel_path):
        return {"ok": False, "pesan": f"File tidak ditemukan: {excel_path}"}
    if not kode_tender:
        return {"ok": False, "pesan": "kode_tender kosong"}

    import win32com.client
    import pythoncom
    import pywintypes
    pythoncom.CoInitialize()

    _own_xl = xl is None
    wb = None
    try:
        if _own_xl:
            xl = win32com.client.DispatchEx("Excel.Application")
            xl.Visible = False
            xl.DisplayAlerts = False
            try:
                xl.AutomationSecurity = 1  # msoAutomationSecurityLow — izinkan macro
            except Exception:
                pass

        _log(f"Membuka Excel: {os.path.basename(excel_path)}")
        wb = xl.Workbooks.Open(excel_path, UpdateLinks=0)

        try:
            xl.Run("ModDraftPaket.SetSilentTender", True)
        except pywintypes.com_error as ce:
            return {"ok": False, "pesan": f"Macro SetSilentTender tidak ditemukan/compile error: {ce}"}

        _log(f"Mengisi @ Master Data untuk {kode_tender}...")
        try:
            xl.Run("ModDraftPaket.IsiDataByKodeTender", str(kode_tender))
        except pywintypes.com_error as ce:
            return {"ok": False, "pesan": f"Macro IsiDataByKodeTender gagal: {ce}"}

        wb.Save()
        _log("@ Master Data terisi, Excel disimpan.")
        return {"ok": True, "pesan": "@ Master Data terisi otomatis"}

    except pywintypes.com_error as ce:
        return {"ok": False, "pesan": f"COM error: {ce}"}
    except Exception as e:
        return {"ok": False, "pesan": str(e)}
    finally:
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if _own_xl and xl is not None:
            try:
                xl.Quit()
            except Exception:
                pass
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python isi_master_data_tender.py <kode_tender> <path.xlsm>")
        sys.exit(1)
    res = proses_master_data_tender(sys.argv[1], sys.argv[2], progress_cb=print)
    print(res)
