"""Helper UI dan workbook Pengadaan Langsung."""

import os
import pathlib
import re
from functools import lru_cache

import pl_engine


def _fmt_elapsed(seconds):
    seconds = int(seconds)
    m, sec = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}j {m}m {sec}d" if h else f"{m}m {sec}d"

def _fmt_step_seconds(seconds):
    return f"{seconds:.1f}s"

def _pl_proses_io_satu_paket(item, cookie_str, cfg):
    """Fase I/O murni per paket PL (thread-safe, TANPA st.* dan TANPA COM).

    Dipanggil di ThreadPoolExecutor untuk paralel antar-paket. COM (merge PDF,
    Excel Master Data) + OCR extract teks dilakukan SERIAL di main thread setelah
    pool selesai (lihat return['files_ok'] + flag 'ok').

    cfg dict berisi: py, script, no_win, pokja_root (semua string/int dari scope tab).
    Return dict: {kode, nama_folder, out_base, jenis_pl, target, ok, log[], files_ok[]}.
    """
    import os as _o
    import re as _re
    import shutil as _sh
    import subprocess as _sp
    import parse_kak_pl as _pkpl
    import hps_engine as _hps_eng
    import time as _tm

    nama_folder = item["nama_folder"]
    kode = item["kode_paket"]
    out_base = item["out_base"]
    jenis_pl = item["jenis_pl"]
    target = _o.path.join(out_base, nama_folder)
    res = {"kode": kode, "nama_folder": nama_folder, "out_base": out_base,
           "jenis_pl": jenis_pl, "target": target, "template_dir": item.get("template_dir", ""),
           "ok": False, "log": [], "files_ok": []}
    log = res["log"].append

    def _step(label, t0, suffix=""):
        log(f"⏱ {label}: {_fmt_step_seconds(_tm.perf_counter() - t0)}{suffix}")

    def _emit(msg):
        q = cfg.get("event_q")
        if q:
            q.put(f"{nama_folder[:55]} — {msg}")

    try:
        _emit("🚀 START worker")
        # 1. Buat folder fisik via subprocess setup_paket_baru.py
        _t_step = _tm.perf_counter()
        _cmd_setup = [cfg["py"], cfg["script"], "--mode", "pl", "--output-dir", out_base]
        if item.get("template_dir"):
            _cmd_setup += ["--template-dir", item["template_dir"]]
        _cmd_setup.append(nama_folder)
        r2 = _sp.run(
            _cmd_setup,
            capture_output=True, text=True, timeout=120, creationflags=cfg["no_win"],
        )
        if r2.returncode != 0:
            log(f"❌ Gagal buat folder: rc={r2.returncode}\nout_base={out_base!r}\nfolder={nama_folder!r}\n{r2.stderr}")
            _emit("❌ gagal buat folder")
            return res
        log("✅ Folder dibuat")
        _step("folder", _t_step)
        _emit("📁 folder dibuat")

        # Auto-simpan nomor_urut ke Supabase
        try:
            _t_step = _tm.perf_counter()
            _m_nu = _re.match(r'^\d+', nama_folder)
            _nomor_auto = _m_nu.group(0) if _m_nu else ""
            if _nomor_auto and kode:
                import config as _cfg
                _cfg.sb().table("draft_paket_pl").update({"nomor_urut": _nomor_auto}).eq("kode_paket", kode).execute()
                log(f"🔢 nomor_urut={_nomor_auto} tersimpan")
            _step("nomor_urut", _t_step)
        except Exception as _nu_e:
            log(f"⚠ nomor_urut: {_nu_e}")
            _step("nomor_urut", _t_step, " error")

        # 2. Copy file evaluator AI
        try:
            _t_step = _tm.perf_counter()
            _eval_root = _o.path.join(cfg["pokja_root"], "_SOP Evaluator")
            _prareviu = ["PROTOKOL_PRA_REVIU.md", "EVALUATOR_PRA_REVIU_DPP.md"]
            if jenis_pl == "JKK":
                _eval_base = ["PROTOKOL_EVALUASI_AI.md", "EVALUATOR_KUALIFIKASI_PL_JKK_LUMSUM.md", "EVALUATOR_KUALIFIKASI_PL_JKK_ADMIN_TEKNIS.md"]
            elif jenis_pl == "PK":
                _eval_base = ["PROTOKOL_EVALUASI_AI.md", "EVALUATOR_KUALIFIKASI_PL_PK.md"]
            else:
                _eval_base = ["PROTOKOL_EVALUASI_AI.md", "EVALUATOR_KUALIFIKASI_TENDER_PK_PASCAKUALIFIKASI.md"]
            _copied = []
            _ppk_dir = _o.path.join(target, "0. Draft Dokumen PPK")
            _o.makedirs(_ppk_dir, exist_ok=True)
            for _ef in _prareviu:
                _src = _o.path.join(_eval_root, _ef)
                if _o.path.isfile(_src):
                    _sh.copy2(_src, _o.path.join(_ppk_dir, _ef)); _copied.append(_ef)
            _eval_dir = _o.path.join(target, "5. Evaluator Kualifikasi & Teknis")
            _o.makedirs(_eval_dir, exist_ok=True)
            for _ef in _eval_base:
                _src = _o.path.join(_eval_root, _ef)
                if _o.path.isfile(_src):
                    _sh.copy2(_src, _o.path.join(_eval_dir, _ef)); _copied.append(_ef)
            log(f"📄 Evaluator: {len(_copied)} file disalin (0.+5.)" if _copied else "⚠ Evaluator: tidak ada file ditemukan di root POKJA")
            _step("evaluator", _t_step)
        except Exception as _ev_e:
            log(f"⚠ Evaluator copy: {_ev_e}")
            _step("evaluator", _t_step, " error")

        # tandai folder dibuat
        try:
            pl_engine.tandai_folder_dibuat(kode)
        except Exception as _e_upd:
            log(f"⚠ tandai_folder_dibuat: {_e_upd}")

        if cfg["dl_dokumen"] and kode:
            # 3. Download dokumen SPSE (cookie di-pass, merge ditunda → serial pasca-pool)
            if not cookie_str:
                log("❌ Download error: Cookie SPSE kosong — buka Chrome SPSE dan login ulang.")
            else:
                try:
                    _emit("⬇️ mulai download")
                    _t_step = _tm.perf_counter()
                    _dl = pl_engine.download_dokumen_paket_pl(
                        kode, target, cookie_str=cookie_str, skip_merge=True,
                    )
                    res["files_ok"] = _dl.get("ok", [])
                    log(f"📎 Download: ✅{len(_dl.get('ok', []))} file")
                    _step("download", _t_step)
                    _emit(f"✅ download {len(_dl.get('ok', []))} file")
                    for _e in _dl.get("error", []):
                        log(f"  ❌ {_e}")
                except Exception as _dl_e:
                    log(f"❌ Download error: {_dl_e}")
                    _step("download", _t_step, " error")
            # 4. Parse KAK
            try:
                _t_step = _tm.perf_counter()
                _kak_p = _pkpl.cari_kak_di_folder(target)
                if _kak_p:
                    _kak_u = {k: v for k, v in _pkpl.parse_kak(_kak_p).items() if v}
                    if _kak_u:
                        pl_engine.simpan_paket_pl({"kode_paket": kode, **_kak_u})
                        log(f"📋 KAK: {','.join(_kak_u.keys())}")
                _step("KAK", _t_step)
            except Exception as _kak_e:
                log(f"⚠ KAK parse: {_kak_e}")
                _step("KAK", _t_step, " error")
            # 5. Serap identitas ringan dari Nota Dinas (tanpa ekstrak personil)
            try:
                _t_step = _tm.perf_counter()
                _id_logs = []
                _id_res = _pkpl.serap_identitas_penyedia_pl(
                    kode_paket_filter=kode,
                    progress_cb=lambda _p, _m: _id_logs.append(_m),
                )
                for _m in _id_logs[-2:]:
                    log(f"👤 {_m}")
                if not _id_logs and not _id_res.get("updated"):
                    log("👤 Identitas penyedia: Nota Dinas tidak ditemukan")
                _step("identitas", _t_step)
            except Exception as _id_e:
                log(f"⚠ Identitas penyedia: {_id_e}")
                _step("identitas", _t_step, " error")
        # NOTE: Serap penyedia full SENGAJA tidak dijalankan di sini.
        # Personil 3-layer tetap di tahap "Download Dokumen Kualifikasi" (Tab 6).

        # 6. Scrape HPS + tulis _HPS_.md (tanpa COM)
        try:
            _t_step = _tm.perf_counter()
            _xlsm = _cari_xlsm_pl(target)
            _hps = _hps_eng.scrape_hps_pl(kode)
            if _hps and _hps.get("items") and _xlsm:
                _hps_eng._tulis_hps_ke_md(kode, _xlsm, _hps)
                log(f"📄 HPS.md: {len(_hps['items'])} item")
                _emit(f"📄 HPS {len(_hps['items'])} item")
            else:
                log("⚠ HPS.md: tidak ada item HPS")
            _step("HPS.md", _t_step)
        except Exception as _hps_e:
            log(f"⚠ HPS.md: {_hps_e}")
            _step("HPS.md", _t_step, " error")

        res["ok"] = True
        _emit("🏁 selesai I/O")
    except _sp.TimeoutExpired:
        log("❌ Timeout buat folder")
    except Exception as _e_x:
        import traceback as _tb
        log(f"❌ EXC {type(_e_x).__name__}: {_e_x}")
        log(_tb.format_exc()[-300:])
    return res

@lru_cache(maxsize=16)
def _pl_ulang_folder_words(root: str, root_mtime_ns: int) -> tuple[frozenset[str], ...]:
    """Index folder PL-Ulang sekali per perubahan direktori root."""
    result = []
    try:
        for folder_name in os.listdir(root):
            folder_lower = folder_name.lower()
            if "(pl - ulang)" not in folder_lower:
                continue
            folder_path = os.path.join(root, folder_name)
            if os.path.isdir(folder_path):
                result.append(frozenset(folder_lower.split()))
    except OSError:
        pass
    return tuple(result)


def _pl_paket_ulang(row: dict) -> bool:
    """True jika ADA folder paket PL bersuffix '(PL - Ulang)' untuk paket ini.
    Scan root langsung (bukan _resolve_folder_pl) agar tak salah resolve ke folder lama
    saat folder lama + ulang dua-duanya ada di disk → nomor dokumen pakai /PLU/.
    """
    try:
        from config import OUTPUT_DIR_PL_JKK, OUTPUT_DIR_PL_PK, sanitasi_nama_folder
        jenis = (row.get("jenis_pl") or "JKK").upper()
        root = OUTPUT_DIR_PL_JKK if jenis == "JKK" else OUTPUT_DIR_PL_PK
        if not os.path.isdir(root):
            return False
        words = set(sanitasi_nama_folder(row.get("nama_paket") or "").lower().split())
        if not words:
            return False
        root_mtime_ns = os.stat(root).st_mtime_ns
        return any(words <= folder_words for folder_words in _pl_ulang_folder_words(root, root_mtime_ns))
    except Exception:
        return False

def _pl_hint_ulang(row: dict) -> str:
    """Return ' (PL - Ulang)' bila paket ini paket ulang, else ''.
    Sumber utama: kolom is_ulang (badge SPSE, di-scrape). Fallback: scan folder disk
    (untuk row lama yg belum re-serap is_ulang).
    """
    if row.get("is_ulang"):
        return " (PL - Ulang)"
    return " (PL - Ulang)" if _pl_paket_ulang(row) else ""


def _pl_label(row: dict) -> str:
    """Label tampilan paket PL yang konsisten di seluruh tab.

    Nomor urut hanya untuk display; nama_paket asli tetap dipakai untuk
    resolusi folder, payload SPSE, dan pencocokan database.
    """
    nama = str(row.get("nama_paket") or row.get("kode_paket") or "-").strip()
    nomor = str(row.get("nomor_urut") or "").strip()
    if nomor and not nama.startswith(f"{nomor}."):
        nama = f"{nomor}. {nama}"
    return nama + _pl_hint_ulang(row)

def _cari_xlsm_pl(folder):
    """Cari .xlsm utama di folder paket PL (prefix '0. BA', skip Backup)."""
    try:
        xs = [f for f in os.listdir(folder)
              if f.lower().endswith(".xlsm") and "backup" not in f.lower()]
    except Exception:
        return None
    if not xs:
        return None
    xs.sort(key=lambda f: (not f.lower().startswith("0. ba"), f))
    return os.path.join(folder, xs[0])

def _baca_master_data_pl(row: dict) -> dict:
    """Baca field authoritative workbook PL tanpa pernah menyimpan .xlsm."""
    try:
        import parse_kak_pl as _pkl_md
        folder, _ = _pkl_md._resolve_folder_pl(
            row.get("nomor_urut"), row.get("nama_paket") or "",
            row.get("jenis_pl") or "JKK", is_ulang=bool(row.get("is_ulang")),
        )
        xlsm = _cari_xlsm_pl(folder) if folder else None
        if not xlsm:
            return {}
        stat = os.stat(xlsm)
        kode_unik, nomor_dokpil, tgl_dokpil = pl_engine.read_master_data_cached(
            xlsm, stat.st_mtime_ns, stat.st_size
        )
        return {
            "kode_unik": kode_unik,
            "nomor_dokpil": nomor_dokpil,
            "tgl_dokpil": tgl_dokpil,
        }
    except Exception:
        return {}

def _proses_excel_paket_pl(target_dir, kode_paket, jenis_pl, refresh_on,
                            template_dir_jkk, template_dir_pk):
    """Refresh template (jika on) -> resolve xlsm -> fetch HPS (no COM) ->
    1 sesi COM gabungan (HPS + Master Data). Return list[str] log lines.
    Urutan BENAR: Refresh dulu (hapus xlsm lama, copy fresh), baru
    resolve xlsm (nama mungkin berubah), lalu tulis HPS + IsiDataPLByKode
    dalam 1x DispatchEx.
    """
    import hps_engine as _hps_eng2
    import isi_master_data_pl as _imd2
    logs = []

    # 1. Refresh template DULU (hapus xlsm lama, copy fresh)
    if refresh_on:
        try:
            from refresh_template import refresh_template_paket as _rt_fn2
            from pathlib import Path as _rt_P2
            _rt_mode2 = "pl_jkk" if jenis_pl == "JKK" else "pl_pk"
            _rt_src2  = _rt_P2(template_dir_jkk if jenis_pl == "JKK" else template_dir_pk)
            _rt_fn2([_rt_P2(target_dir)], _rt_src2, _rt_mode2, auto_relink=True, dry_run=False)
            logs.append("Refresh Template: selesai")
        except Exception as _rt_e2:
            logs.append(f"WARN Refresh Template: {_rt_e2}")

    # 2. Resolve xlsm SETELAH refresh (nama file bisa berubah)
    xlsm = _cari_xlsm_pl(target_dir)
    if not xlsm:
        logs.append("WARN Excel dilewati -- tidak ada .xlsm setelah refresh")
        return logs

    # 3. Fetch HPS dict (tanpa COM) via scrape_hps_pl
    hps_hasil = None
    try:
        hps_hasil = _hps_eng2.scrape_hps_pl(kode_paket)
        if not hps_hasil.get("items"):
            logs.append("WARN HPS: tidak ada item (fetch gagal/kosong)")
            hps_hasil = None
    except Exception as _hps_e2:
        logs.append(f"WARN HPS fetch: {_hps_e2}")

    # 4. 1 sesi COM: tulis HPS + IsiDataPLByKode
    try:
        _res2 = _imd2.proses_hps_dan_master_data(kode_paket, xlsm, hps_hasil)
        _hps_r2 = _res2.get("hps", {})
        _md_r2  = _res2.get("md", {})
        if _hps_r2.get("ok") and _hps_r2.get("count", 0) > 0:
            logs.append(f"HPS: {_hps_r2['count']} baris -> Excel")
        elif hps_hasil:
            logs.append(f"WARN HPS tulis: {_hps_r2.get('pesan','-')}")
        if _md_r2.get("ok"):
            logs.append("Master Data: terisi")
        else:
            logs.append(f"WARN Master Data: {_md_r2.get('pesan','-')}")
    except Exception as _com_e2:
        logs.append(f"WARN COM gabungan: {_com_e2}")

    # 5. Generate MD file HPS (no COM) jika hps_hasil ada
    if hps_hasil and hps_hasil.get("items"):
        try:
            _hps_eng2._tulis_hps_ke_md(kode_paket, xlsm, hps_hasil)
        except Exception as _md_e2:
            logs.append(f"WARN HPS MD: {_md_e2}")

    return logs

def _template_dir_pl_jkk(row, default_dir):
    satker = " ".join(str(row.get(k) or "") for k in ("satker", "nama_satker", "nama_dinas"))
    if re.search(r"perdagangan|disdag", satker, re.IGNORECASE):
        return str(pathlib.Path(default_dir).with_name("Development - PL - JKK - Disdag"))
    return default_dir
