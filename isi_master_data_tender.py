"""isi_master_data_tender.py - auto-isi sheet '@ Master Data' paket Tender via COM."""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path


INPUT_ROWS = {
    "mak": 3, "kode_tender": 4, "nama_tender": 5, "kode_rup": 6,
    "nilai_pagu": 7, "nilai_hps": 8, "nomor_surat_dinas": 9,
    "nomor_pp": 10, "kode_pokja": 11, "jangka_waktu": 12,
    "nama_dinas": 14, "nama_ppk": 15, "nip_ppk": 16, "sk_ppk": 17,
    "anggota_1": 18, "anggota_2": 19, "anggota_3": 20,
    "sumber_anggaran": 22, "sbu_baru": 26,
}

REVIU_ROWS = {
    "E6": 26, "E7": 27, "E9": 28, "E10": 29, "E11": 30,
    "E12": 31, "E13": 32, "E14": 33, "E15": 34, "E16": 35,
    "E17": 36, "E18": 37, "E19": 38, "E20": 39, "E21": 40,
    "E22": 41, "E23": 42, "E24": 43, "E25": 44, "E26": 45,
    "E27": 46, "E28": 47, "E29": 48, "E30": 49, "E31": 50,
    "E32": 51, "E33": 52, "E34": 53,
}

DOKPIL_ROWS = {
    "E6": 56, "E7": 57, "E8": 58, "E9": 59, "E10": 60, "E11": 61,
    "E12": 62, "E13": 63, "E14": 64, "E15": 65,
}


def _hari_angka(v):
    s = str(v or "").strip()
    if not s:
        return ""
    head = s.split()[0]
    head = head.translate(str.maketrans({"O": "0", "o": "0", "L": "1", "l": "1", "I": "1"}))
    return int(head) if head.isdigit() else s


def _isi_master_data_dari_row(wb, row: dict):
    ws = wb.Sheets("@ Master Data")
    values = {
        3: row.get("mak"),
        4: row.get("kode_tender"),
        5: row.get("nama_tender"),
        6: row.get("kode_rup"),
        7: row.get("nilai_pagu"),
        8: row.get("nilai_hps"),
        9: row.get("nomor_surat_dinas"),
        10: row.get("nomor_pp"),
        11: row.get("kode_pokja"),
        12: _hari_angka(row.get("jangka_waktu")),
        14: row.get("nama_dinas"),
        15: row.get("nama_ppk"),
        18: row.get("anggota_1"),
        19: row.get("anggota_2"),
        20: row.get("anggota_3"),
        22: row.get("sumber_anggaran"),
        26: row.get("sbu_baru"),
    }
    for r, v in values.items():
        if v not in (None, ""):
            ws.Cells(r, 3).Value = v


def _cari_draft_pdf(folder: Path, kode_pokja: str) -> Path | None:
    candidates = sorted(folder.rglob("Draft_Pokja_*.pdf"))
    if kode_pokja:
        hit = [p for p in candidates if kode_pokja in p.name]
        if hit:
            return hit[0]
    return candidates[0] if candidates else None


def _nama_bersih(nama: str) -> str:
    s = str(nama or "").split(",", 1)[0].strip().upper()
    s = re.sub(r"^(IR\.?|H\.?|HJ\.?|DR\.?|DRA\.?|DRS\.?)\s+", "", s)
    return s.strip()


def _sk_kpa_pdf_path() -> Path:
    return Path(r"D:\Dokumen\@ POKJA 2026\@ Pejabat Pengadaan 2026\@ DPUPR Bina Marga\(5) SK KPA 2026 PERUBAHAN KESATU - Salin.pdf")


_SK_KPA_CACHE = None


def _load_sk_kpa_2026() -> dict:
    global _SK_KPA_CACHE
    if _SK_KPA_CACHE is not None:
        return _SK_KPA_CACHE
    pdf = _sk_kpa_pdf_path()
    if not pdf.exists():
        _SK_KPA_CACHE = {}
        return _SK_KPA_CACHE
    try:
        import pdfplumber
        text_pages = []
        rows = {}
        with pdfplumber.open(str(pdf)) as doc:
            for pg in doc.pages:
                text_pages.append(pg.extract_text() or "")
                for table in (pg.extract_tables() or []):
                    for row in table:
                        if not row or len(row) < 4:
                            continue
                        no_raw = str(row[0] or "").strip().rstrip(".")
                        if not no_raw.isdigit():
                            continue
                        parts = [p.strip() for p in str(row[1] or "").split("\n") if p.strip()]
                        if not parts:
                            continue
                        nama = parts[0]
                        nip = ""
                        for p in parts[1:]:
                            m = re.search(r"NIP\.?\s*([\d\s]+)", p)
                            if m:
                                nip = m.group(1).strip()
                                break
                        rows[_nama_bersih(nama)] = {"nip": nip}
        full = "\n".join(text_pages)
        m_no = re.search(r"NOMOR\s+([\d\.]+/\d+/[A-Z]+/\d+)", full)
        m_tgl = re.search(r"Ditetapkan\s+di\s+Rantau\s+pada\s+tanggal\s+(\d{1,2}\s+\w+\s+\d{4})", full, re.IGNORECASE)
        sk = ""
        if m_no and m_tgl:
            sk = f"Keputusan Bupati Tapin Nomor {m_no.group(1)} tanggal {m_tgl.group(1)}"
        for v in rows.values():
            v["sk_ppk"] = sk
        _SK_KPA_CACHE = rows
    except Exception:
        _SK_KPA_CACHE = {}
    return _SK_KPA_CACHE


def _isi_ppk_dari_sheet_ref_com(wb, ws, nama_ppk: str):
    sk2026 = _load_sk_kpa_2026().get(_nama_bersih(nama_ppk), {})
    if sk2026:
        if sk2026.get("nip"):
            ws.Cells(16, 3).Value = sk2026["nip"]
        if sk2026.get("sk_ppk"):
            ws.Cells(17, 3).Value = sk2026["sk_ppk"]
        return
    if ws.Cells(16, 3).Value and ws.Cells(17, 3).Value:
        return
    try:
        ref = wb.Sheets("0. Data Nama Pokja & PPK")
    except Exception:
        return
    target = _nama_bersih(nama_ppk)
    if not target:
        return
    last_row = ref.Cells(ref.Rows.Count, 3).End(-4162).Row  # xlUp
    for r in range(2, last_row + 1):
        nama_ref = ref.Cells(r, 3).Value
        if _nama_bersih(nama_ref) == target or str(nama_ref or "").strip().upper() == str(nama_ppk or "").strip().upper():
            if not ws.Cells(16, 3).Value:
                ws.Cells(16, 3).Value = ref.Cells(r, 5).Value
            if not ws.Cells(17, 3).Value:
                ws.Cells(17, 3).Value = ref.Cells(r, 6).Value
            return


def _kegiatan_valid(v: str) -> bool:
    s = str(v or "").strip().lower()
    if len(s) < 8:
        return False
    if s.endswith((" dan", " atau", " dengan", " secara")):
        return False
    if any(bad in s for bad in ("dokumen tersebut", "memahami benar", "dengan seksama")):
        return False
    return True


def _fungsi_bangunan_gemini(nama_tender: str) -> str:
    try:
        from kode_unik_engine import _load_gemini_key
        api_key = _load_gemini_key()
        if not api_key:
            return ""
        from google import genai
        client = genai.Client(api_key=api_key)
        prompt = (
            "Tulis fungsi/manfaat bangunan/pekerjaan konstruksi dari nama paket ini.\n"
            "Jawab 1 frasa formal Bahasa Indonesia, maksimal 18 kata, tanpa penjelasan.\n"
            "Contoh: Normalisasi Sungai X -> Untuk mengurangi risiko banjir dan sedimentasi pada alur sungai.\n"
            f"Nama paket: {nama_tender}\nOutput:"
        )
        resp = client.models.generate_content(model="gemini-2.5-flash-lite", contents=prompt)
        val = (resp.text or "").strip().splitlines()[0].strip(" .")
        return val[:180] if val else ""
    except Exception:
        return ""


def _fallback_fungsi_bangunan(nama_tender: str) -> str:
    n = (nama_tender or "").lower()
    if any(k in n for k in ("normalisasi", "sungai", "sei.", "saluran", "drainase")):
        return "Untuk mengurangi risiko banjir dan sedimentasi pada alur sungai atau saluran."
    if "jalan" in n:
        return "Untuk meningkatkan konektivitas dan kelancaran akses transportasi masyarakat."
    if any(k in n for k in ("gedung", "bangunan")):
        return "Untuk menunjang pelayanan dan operasional kegiatan pada bangunan tersebut."
    if "jembatan" in n:
        return "Untuk mendukung konektivitas lintasan dan akses masyarakat."
    return nama_tender or ""


def _fresh_viewdraft_data(kode_tender: str) -> dict:
    try:
        import inbox_engine
        return inbox_engine._scrape_viewdraft_tender(kode_tender) or {}
    except Exception:
        return {}

def _normalisasi_sumber_anggaran(v: str) -> str:
    s = str(v or "").strip()
    if not s:
        return ""
    tahun = re.search(r"\b(20\d{2})\b", s)
    tahun = tahun.group(1) if tahun else "2026"
    # Output parser lama sering salah membaca APBD biasa sebagai APBDP.
    if re.search(r"\bAPBDP\b", s, re.IGNORECASE) and "PERUBAHAN" not in s.upper():
        return f"APBD {tahun}"
    if re.search(r"\bAPBD\s*[- ]\s*P\b|\bAPBD\s+PERUBAHAN\b", s, re.IGNORECASE):
        return f"APBDP {tahun}"
    if re.search(r"\bAPBD\b", s, re.IGNORECASE):
        return f"APBD {tahun}"
    return s


def _parse_metadata_pdf_local(pdf: Path) -> dict:
    """Parse metadata halaman awal Draft_Pokja lokal sebagai fallback row DB."""
    try:
        import inbox_engine
        return inbox_engine.parse_pdf_inmemory("", pdf_bytes=pdf.read_bytes()) or {}
    except Exception:
        return {}


def _isi_metadata_fallback(kode_tender: str, row_data: dict, data: dict, pdf: Path, log) -> dict:
    """Isi field metadata kosong dari PDF lokal, lalu simpan balik ke draft_paket."""
    parsed = _parse_metadata_pdf_local(pdf)
    src = data.get("input_data", {})
    pdf_reviu = src.get("E33", {}).get("nilai")
    candidates = {
        "nomor_pp": parsed.get("nomor_pp"),
        "nomor_surat_dinas": parsed.get("nomor_surat_dinas"),
        "nama_dinas": parsed.get("nama_dinas"),
        "jangka_waktu": parsed.get("jangka_waktu"),
        # E33 hasil parse_reviu sudah menormalkan APBD + tahun; gunakan itu
        # sebelum nilai mentah halaman surat yang kadang berbunyi APBD/APBN.
        "sumber_anggaran": pdf_reviu or parsed.get("sumber_anggaran"),
    }
    filled = {}
    for key, value in candidates.items():
        if row_data.get(key) in (None, "") and value not in (None, ""):
            row_data[key] = value
            filled[key] = value
    if not filled:
        return {}

    log("Fallback metadata: " + ", ".join(filled))
    try:
        import inbox_engine
        inbox_engine._sb().table("draft_paket").update(filled).eq(
            "kode_tender", kode_tender
        ).execute()
        log("Metadata draft_paket disinkronkan")
    except Exception as e:
        log(f"WARN sync metadata draft_paket: {e}")
    return filled


def _proses_com_direct(kode_tender: str, excel_path: str, row_data: dict, progress_cb=None, xl=None) -> dict:

    def _log(m):
        if progress_cb:
            try: progress_cb(m)
            except Exception: pass

    import pythoncom
    import win32com.client

    xlsm = Path(excel_path)
    folder = xlsm.parent
    data = {}
    fresh_viewdraft = _fresh_viewdraft_data(kode_tender)
    row_data = {
        **row_data,
        **{k: v for k, v in fresh_viewdraft.items() if v not in (None, "")},
    }
    row_data["sumber_anggaran"] = _normalisasi_sumber_anggaran(row_data.get("sumber_anggaran"))

    pdf = _cari_draft_pdf(folder, str(row_data.get("kode_pokja") or ""))
    if pdf:
        _log(f"Parse PDF: {pdf.name}")
        from config import V19_ROOT as _v19_root
        script = Path(_v19_root) / "parse_reviu.py"
        try:
            res = subprocess.run(
                [sys.executable, str(script), str(pdf), str(folder), str(row_data.get("bidang") or ""), str(row_data.get("nama_tender") or "")],
                capture_output=True, text=True, timeout=120,
            )
            if res.returncode != 0:
                _log(f"WARN parse_reviu gagal: {(res.stderr or res.stdout or 'error')[-300:]}")
            else:
                data = json.loads((folder / "_parse_reviu.json").read_text(encoding="utf-8"))
                _isi_metadata_fallback(kode_tender, row_data, data, pdf, _log)
        except subprocess.TimeoutExpired:
            _log("WARN parse_reviu timeout — data utama tetap diisi dari draft_paket")
    else:
        _log("WARN Draft_Pokja PDF tidak ditemukan")

    pythoncom.CoInitialize()
    own_xl = xl is None
    wb = None
    try:
        if own_xl:
            xl = win32com.client.DispatchEx("Excel.Application")
            xl.Visible = False
            xl.DisplayAlerts = False
            xl.EnableEvents = False
            try:
                xl.AutomationSecurity = 1
            except Exception:
                pass
        wb = xl.Workbooks.Open(str(xlsm), UpdateLinks=0)
        ws = wb.Sheets("@ Master Data")

        # Template dapat membawa nilai paket donor; kosongkan semua field data
        # sebelum menulis data paket target agar tidak ada identitas stale.
        _clear_rows = (
            set(INPUT_ROWS.values())
            | set(REVIU_ROWS.values())
            | set(DOKPIL_ROWS.values())
            | {25, 27, 66}
        )
        for _row in _clear_rows:
            ws.Cells(_row, 3).Value = ""
        ws.Range("G2").Value = ""

        for key, row in INPUT_ROWS.items():
            v = _hari_angka(row_data.get(key)) if key == "jangka_waktu" else row_data.get(key)
            if v not in (None, ""):
                ws.Cells(row, 3).Value = v
        _isi_ppk_dari_sheet_ref_com(wb, ws, row_data.get("nama_ppk"))

        src = data.get("input_data", {})
        keg = src.get("E16", {}).get("nilai")
        if keg:
            ws.Cells(13, 3).Value = keg if _kegiatan_valid(keg) else row_data.get("nama_tender")
        if src.get("E32", {}).get("nilai"):
            ws.Cells(21, 3).Value = src["E32"]["nilai"]
        # Jangan overwrite sumber dana dari PDF parser; SPSE/detail DB lebih otoritatif.

        for sec, row_map in (("reviu", REVIU_ROWS), ("dokpil", DOKPIL_ROWS)):
            for cell, row in row_map.items():
                nilai = data.get(sec, {}).get(cell, {}).get("nilai")
                if nilai not in (None, ""):
                    ws.Cells(row, 3).Value = nilai

        wb.Save()
        return {"ok": True, "pesan": "@ Master Data terisi via COM direct"}
    finally:
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if own_xl and xl is not None:
            try:
                xl.Quit()
            except Exception:
                pass
        pythoncom.CoUninitialize()


def proses_master_data_tender(
    kode_tender: str,
    excel_path: str,
    progress_cb=None,
    xl=None,
    row_data: dict | None = None,
) -> dict:
    """Isi @ Master Data.

    Jika row_data ada: tulis langsung dari data Streamlit, lalu parse PDF lokal.
    Jika tidak: fallback macro lama yang fetch Supabase.
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

    if row_data:
        row_data = dict(row_data)
        # Kode argumen adalah identitas otoritatif create-folder. Jangan pernah
        # mengosongkan template bila payload metadata ternyata tidak lengkap.
        row_data["kode_tender"] = str(kode_tender)
        if not str(row_data.get("nama_tender") or "").strip():
            return {
                "ok": False,
                "pesan": "nama_tender kosong; @ Master Data tidak diubah",
            }
        return _proses_com_direct(kode_tender, excel_path, row_data, progress_cb, xl=xl)

    import pythoncom
    import pywintypes
    import win32com.client

    pythoncom.CoInitialize()
    own_xl = xl is None
    wb = None
    try:
        if own_xl:
            xl = win32com.client.DispatchEx("Excel.Application")
            xl.Visible = False
            xl.DisplayAlerts = False
            try:
                xl.AutomationSecurity = 1
            except Exception:
                pass

        _log(f"Membuka Excel: {os.path.basename(excel_path)}")
        wb = xl.Workbooks.Open(excel_path, UpdateLinks=0)

        try:
            xl.Run("ModDraftPaket.SetSilentTender", True)
        except pywintypes.com_error as ce:
            return {"ok": False, "pesan": f"Macro SetSilentTender tidak ditemukan/compile error: {ce}"}

        _log(f"Mengisi @ Master Data untuk {kode_tender}...")
        if row_data:
            _isi_master_data_dari_row(wb, row_data)
            try:
                xl.Run(
                    "ModDraftPaket.ParsaDanIsiDariPDF",
                    str(kode_tender),
                    str(row_data.get("kode_pokja") or ""),
                    str(row_data.get("bidang") or ""),
                    str(row_data.get("nama_tender") or ""),
                )
            except pywintypes.com_error as ce:
                return {"ok": False, "pesan": f"Macro parse PDF gagal: {ce}"}
        else:
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
        if own_xl and xl is not None:
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
