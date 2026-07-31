"""isi_master_data_pl.py — Auto-isi sheet '@ Master Data' paket PL via COM.

Trigger macro VBA `ModDraftPaketPL.IsiDataPLByKode` (reuse 100% logika VBA:
lookup KPA/Dinas, compose nomor dokpil/undangan/BA reviu, kode unik, personil).

Dipanggil dari app.py saat buat folder PL (single/bulk), setelah HPS + refresh
template. Menggantikan tombol manual "Muat Paket PL" + "Isi Data PL" di Excel.
"""

import os


def isi_master_data_pl(kode_paket: str, excel_path: str, progress_cb=None) -> dict:
    """Buka xlsm via COM, jalankan macro IsiDataPLByKode(kode_paket) dalam silent mode.

    Return: {"ok": bool, "pesan": str}
    """
    def _log(m):
        if progress_cb:
            progress_cb(m)

    excel_path = os.path.abspath(excel_path)
    if not os.path.isfile(excel_path):
        return {"ok": False, "pesan": f"File tidak ditemukan: {excel_path}"}
    if not kode_paket:
        return {"ok": False, "pesan": "kode_paket kosong"}

    import win32com.client
    import pythoncom
    import pywintypes
    pythoncom.CoInitialize()

    xl = None
    wb = None
    sync_v2 = False
    try:
        xl = win32com.client.DispatchEx("Excel.Application")
        xl.Visible = False
        xl.DisplayAlerts = False
        # AutomationSecurity=1 (msoAutomationSecurityLow) — izinkan macro jalan
        try:
            xl.AutomationSecurity = 1
        except Exception:
            pass

        _log(f"Membuka Excel: {os.path.basename(excel_path)}")
        wb = xl.Workbooks.Open(excel_path, UpdateLinks=0)

        # Aktifkan silent mode → suppress MsgBox di jalur VBA
        try:
            xl.Run("ModDraftPaketPL.SetSilentPL", True)
        except pywintypes.com_error as ce:
            return {"ok": False, "pesan": f"Macro SetSilentPL tidak ditemukan/compile error: {ce}"}

        _log(f"Mengisi @ Master Data untuk {kode_paket}...")
        try:
            xl.Run("ModDraftPaketPL.IsiDataPLByKode", str(kode_paket))
        except pywintypes.com_error as ce:
            return {"ok": False, "pesan": f"Macro IsiDataPLByKode gagal: {ce}"}

        # Refresh sheet @ Evaluasi (tgl_pembukaan, nomor BA, dll) — 1 sesi COM
        try:
            xl.Run("ModDraftPaketPL.IsiEvaluasiPLStandalone")
            _log("@ Evaluasi ter-refresh.")
        except pywintypes.com_error:
            _log("[WARN] IsiEvaluasiPLStandalone tidak ditemukan — skip.")

        wb.Save()
        _log("@ Master Data + @ Evaluasi terisi.")
        sync_v2 = True
        return {"ok": True, "pesan": "@ Master Data + @ Evaluasi terisi otomatis"}
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
        if xl is not None:
            try:
                xl.Quit()
            except Exception:
                pass
        if sync_v2:
            try:
                import sys
                code_root = os.environ.get("POKJA_CODE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
                sys.path.insert(0, os.path.join(code_root, "procurement_core"))
                from master_data_v2 import sync_daftar_paket_snapshot
                sync_daftar_paket_snapshot(excel_path)
                _log("Snapshot Daftar Paket V2 tersinkron.")
            except Exception as exc:
                _log(f"[WARN] Snapshot V2 tidak tersinkron: {exc}")
        try:
            pythoncom.CoUninitialize()
        except Exception:
            pass


# ── CLI self-test ─────────────────────────────────────────────

def proses_hps_dan_master_data(kode_paket: str, excel_path: str,
                                hps_hasil: dict = None,
                                progress_cb=None,
                                timeout: int = 90) -> dict:
    """1 sesi COM: tulis HPS (jika ada) lalu IsiDataPLByKode — 1x DispatchEx.

    Dipakai oleh _proses_excel_paket_pl() di app.py (bulk-create folder PL).
    Urutan: Open -> (a) tulis sheet '5. HPS' [isolasi, gagal tidak blokir] ->
    (b) SetSilentPL(True) -> IsiDataPLByKode(kode) -> Save -> finally Close+Quit.

    Args:
        kode_paket: kode paket PL (string).
        excel_path: path absolut file .xlsm yang sudah di-refresh.
        hps_hasil:  dict {items, total_nilai, total_nilai_bulat} dari scrape_hps_pl().
                    Jika None, langkah HPS dilewati.
        progress_cb: callable(str) opsional untuk log progres.

    Return: {"ok": bool, "hps": {"ok", "pesan", "count"}, "md": {"ok", "pesan"}}
    """
    def _log(m):
        if progress_cb:
            try:
                progress_cb(m)
            except Exception:
                pass

    excel_path = os.path.abspath(excel_path)
    if not os.path.isfile(excel_path):
        return {
            "ok": False,
            "hps": {"ok": False, "pesan": "file tidak ada", "count": 0},
            "md":  {"ok": False, "pesan": f"File tidak ditemukan: {excel_path}"},
        }
    if not kode_paket:
        return {
            "ok": False,
            "hps": {"ok": False, "pesan": "dilewati", "count": 0},
            "md":  {"ok": False, "pesan": "kode_paket kosong"},
        }

    result_box = [None]
    import threading

    def _run_com():
        import win32com.client
        import pythoncom
        import pywintypes
        import hps_engine as _hps_eng

        pythoncom.CoInitialize()

        xl = None
        wb = None
        hps_res = {"ok": False, "pesan": "dilewati", "count": 0}
        md_res  = {"ok": False, "pesan": ""}

        try:
            xl = win32com.client.DispatchEx("Excel.Application")
            xl.Visible = False
            xl.DisplayAlerts = False
            try:
                xl.AutomationSecurity = 1  # msoAutomationSecurityLow
            except Exception:
                pass

            _log(f"Membuka Excel: {os.path.basename(excel_path)}")
            wb = xl.Workbooks.Open(excel_path, UpdateLinks=0)

            # (a) Tulis HPS ke sheet '5. HPS' --- ISOLASI: gagal tidak blokir Master Data
            if hps_hasil and hps_hasil.get("items"):
                try:
                    ws_hps = wb.Sheets("5. HPS")
                    r = _hps_eng._tulis_hps_ke_ws(ws_hps, wb, hps_hasil, progress_cb)
                    hps_res = {"ok": r["ok"], "pesan": r["pesan"], "count": r.get("count", 0)}
                    _log(f"HPS: {hps_res['count']} baris ditulis.")
                except Exception as e_hps:
                    hps_res = {"ok": False, "pesan": f"Gagal tulis HPS: {e_hps}", "count": 0}
                    _log(f"WARN HPS: {e_hps} (Master Data tetap lanjut)")
            else:
                hps_res = {"ok": True, "pesan": "hps_hasil kosong, dilewati", "count": 0}

            # (b) SetSilentPL + IsiDataPLByKode
            try:
                xl.Run("ModDraftPaketPL.SetSilentPL", True)
            except pywintypes.com_error as ce:
                md_res = {"ok": False, "pesan": f"Macro SetSilentPL tidak ditemukan/compile error: {ce}"}
                wb.Save()
                result_box[0] = {"ok": False, "hps": hps_res, "md": md_res}
                return

            _log(f"Mengisi @ Master Data untuk {kode_paket}...")
            try:
                xl.Run("ModDraftPaketPL.IsiDataPLByKode", str(kode_paket))
                md_res = {"ok": True, "pesan": "@ Master Data terisi otomatis"}
            except pywintypes.com_error as ce:
                md_res = {"ok": False, "pesan": f"Macro IsiDataPLByKode gagal: {ce}"}

            # Refresh @ Evaluasi setelah Master Data terisi
            if md_res["ok"]:
                try:
                    xl.Run("ModDraftPaketPL.IsiEvaluasiPLStandalone")
                    _log("@ Evaluasi ter-refresh.")
                except pywintypes.com_error:
                    _log("[WARN] IsiEvaluasiPLStandalone tidak ditemukan — skip.")

            wb.Save()
            _log("Excel disimpan.")
            result_box[0] = {"ok": md_res["ok"], "hps": hps_res, "md": md_res}

        except Exception as e:
            result_box[0] = {
                "ok": False,
                "hps": hps_res,
                "md":  {"ok": False, "pesan": str(e)},
            }
        finally:
            if wb is not None:
                try:
                    wb.Close(SaveChanges=False)
                except Exception:
                    pass
            if xl is not None:
                try:
                    xl.Quit()
                except Exception:
                    pass
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass

    t = threading.Thread(target=_run_com, daemon=True)
    t.start()
    t.join(timeout=timeout)
    if t.is_alive():
        return {
            "ok": False,
            "hps": {"ok": False, "pesan": "timeout", "count": 0},
            "md":  {"ok": False, "pesan": f"COM timeout {timeout}s — Excel tidak responsif"},
        }
    result = result_box[0] or {
        "ok": False,
        "hps": {"ok": False, "pesan": "tidak ada hasil", "count": 0},
        "md":  {"ok": False, "pesan": "thread selesai tanpa hasil"},
    }
    if result.get("md", {}).get("ok"):
        try:
            import sys
            code_root = os.environ.get("POKJA_CODE_ROOT") or os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            sys.path.insert(0, os.path.join(code_root, "procurement_core"))
            from master_data_v2 import sync_daftar_paket_snapshot
            sync_daftar_paket_snapshot(excel_path)
            _log("Snapshot Daftar Paket V2 tersinkron.")
        except Exception as exc:
            _log(f"[WARN] Snapshot V2 tidak tersinkron: {exc}")
    return result

if __name__ == "__main__":
    import sys
    if len(sys.argv) < 3:
        print("Usage: python isi_master_data_pl.py <kode_paket> <path.xlsm>")
        sys.exit(1)
    res = isi_master_data_pl(sys.argv[1], sys.argv[2], progress_cb=print)
    print(res)
