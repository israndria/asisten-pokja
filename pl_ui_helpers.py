"""Helper UI dan workbook Pengadaan Langsung."""

import os
import pathlib
import re
import json
import shutil
import subprocess
import uuid
from datetime import datetime
from functools import lru_cache

import pl_engine


_PL8_EVALUATION_CHECKBOX_KEYS = (
    "pl8_do_eval_admin",
    "pl8_do_eval_teknis",
    "pl8_do_eval_harga",
)
_PL8_EVALUATION_DEFAULTS_VERSION = 1


def ensure_pl_evaluation_checkbox_defaults(state) -> None:
    """Set tiga checklist evaluasi PL aktif sekali, lalu hormati pilihan user."""
    first_initialization = (
        state.get("_pl8_evaluation_defaults_version")
        != _PL8_EVALUATION_DEFAULTS_VERSION
    )
    for key in _PL8_EVALUATION_CHECKBOX_KEYS:
        if first_initialization:
            state[key] = True
        else:
            state.setdefault(key, True)
    state["_pl8_evaluation_defaults_version"] = _PL8_EVALUATION_DEFAULTS_VERSION


def _engine_for_jenis_pl(jenis_pl):
    """Pilih engine downloader/merger sesuai family paket.

    Bulk worker berjalan di helper module, sehingga assignment ``pl_engine``
    pada scope ``app.py`` tidak ikut berubah saat mode PK aktif. Tanpa resolver
    ini worker PK diam-diam memakai endpoint/cleanup engine JKK.
    """
    if str(jenis_pl or "").upper().strip() == "PK":
        import pl_engine_plpk
        return pl_engine_plpk
    return pl_engine


@lru_cache(maxsize=1)
def _core_workflow_config():
    """Muat registry dari procurement_core tanpa menabrak config UI lokal."""
    import importlib.util
    from config import V19_ROOT

    path = pathlib.Path(V19_ROOT) / "config.py"
    spec = importlib.util.spec_from_file_location("pokja_procurement_config", path)
    if not spec or not spec.loader:
        raise ImportError(f"config procurement_core tidak dapat dimuat: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _fmt_elapsed(seconds):
    seconds = int(seconds)
    m, sec = divmod(seconds, 60)
    h, m = divmod(m, 60)
    return f"{h}j {m}m {sec}s" if h else f"{m}m {sec}s"

def _fmt_step_seconds(seconds):
    return f"{seconds:.1f}s"


def _pl_output_dasar_valid(target_dir):
    """Validasi minimum output setup sebelum paket dianggap selesai."""
    if not os.path.isdir(target_dir):
        return False, "folder output tidak ditemukan"
    if not _cari_xlsm_pl(target_dir):
        return False, "workbook .xlsm tidak ditemukan"
    if not os.path.isfile(os.path.join(target_dir, ".template-meta.json")):
        return False, "metadata .template-meta.json tidak ditemukan"
    required_dirs = (
        "0. Draft Dokumen PPK",
        "1. KAK & Spesifikasi Teknis",
        "2. Rancangan Kontrak",
        "3. Uraian Singkat Pekerjaan",
        "4. Informasi Lainnya",
        "10. Revisi Uploadan PPK",
    )
    missing_dirs = [
        name for name in required_dirs
        if not os.path.isdir(os.path.join(target_dir, name))
    ]
    if missing_dirs:
        return False, "subfolder inti hilang: " + ", ".join(missing_dirs)
    return True, ""


def _local_hps_fallback(target_dir, kode_paket):
    """Ambil HPS terakhir yang sudah tersimpan lokal bila SPSE timeout."""
    import hps_engine

    candidates = sorted(
        pathlib.Path(target_dir).glob("_HPS_*.md"),
        key=lambda p: p.stat().st_mtime_ns,
        reverse=True,
    )
    for candidate in candidates:
        try:
            parsed = hps_engine.parse_hps_md(str(candidate), expected_kode=kode_paket)
        except Exception:
            continue
        if parsed.get("items"):
            return parsed, str(candidate)
    return None, ""


def _pl_io_success(res, download_requested):
    """Predikat murni status I/O, dapat diuji tanpa SPSE/network."""
    if not res.get("setup_ok") or not res.get("output_ok") or not res.get("hps_ok"):
        return False
    return not download_requested or bool(res.get("download_ok"))


def _pl_download_success(files_ok, errors):
    """Validasi download; Nota Dinas opsional karena diproses lewat email."""
    if not files_ok:
        return False
    return not any(
        not str(error or "").startswith("Nota Dinas PPK:")
        for error in (errors or [])
    )


def _copy_pl_evaluator_files(target_dir: str, pokja_root: str, jenis_pl: str) -> list[str]:
    """Copy SOP evaluator kanonik ke folder paket PL.

    SOP Isi Reviu berada di ``0. Draft Dokumen PPK`` agar langsung tersedia
    saat AI diminta membaca draft. Evaluator domain tetap berada di folder 5.
    File legacy pra-reviu sengaja tidak dipakai karena sudah tidak ada di
    master ``_SOP Evaluator``.
    """
    eval_root = os.path.join(pokja_root, "_SOP Evaluator")
    jenis = str(jenis_pl or "").upper().strip()
    if jenis == "JKK":
        reconciliation_sop = "SOP_REKONSILIASI_XML_DOKUMEN_PPK_PLJKK.md"
        evaluator_files = (
            "PROTOKOL_EVALUASI_AI.md",
            "EVALUATOR_KUALIFIKASI_PL_JKK_LUMSUM.md",
            "EVALUATOR_KUALIFIKASI_PL_JKK_ADMIN_TEKNIS.md",
        )
    elif jenis == "PK":
        reconciliation_sop = "SOP_REKONSILIASI_XML_DOKUMEN_PPK_PLPK.md"
        evaluator_files = (
            "PROTOKOL_EVALUASI_AI.md",
            "EVALUATOR_KUALIFIKASI_PL_PK.md",
        )
    else:
        # Jangan menebak domain XML untuk family yang tidak dikenal.
        reconciliation_sop = None
        evaluator_files = (
            "PROTOKOL_EVALUASI_AI.md",
            "EVALUATOR_E2E_TENDER_PK_PASCAKUALIFIKASI.md",
        )

    draft_files = (
        "SOP_ISI_REVIU_DPP_CORE.md",
        "SOP_ISI_REVIU_DPP_DOMAIN.md",
        "SOP_REKONSILIASI_XML_DOKUMEN_PPK_CORE.md",
    ) + ((reconciliation_sop,) if reconciliation_sop else ())

    copied = []
    destinations = (
        ("0. Draft Dokumen PPK", draft_files),
        ("5. Evaluator Kualifikasi & Teknis", evaluator_files),
    )
    for subfolder, filenames in destinations:
        destination_dir = os.path.join(target_dir, subfolder)
        os.makedirs(destination_dir, exist_ok=True)
        for filename in filenames:
            source = os.path.join(eval_root, filename)
            if os.path.isfile(source):
                shutil.copy2(source, os.path.join(destination_dir, filename))
                copied.append(filename)
    return copied


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
    import subprocess as _sp
    import parse_kak_pl as _pkpl
    import hps_engine as _hps_eng
    import time as _tm

    nama_folder = item["nama_folder"]
    kode = item["kode_paket"]
    out_base = item["out_base"]
    jenis_pl = item["jenis_pl"]
    _engine = _engine_for_jenis_pl(jenis_pl)
    target = _o.path.join(out_base, nama_folder)
    res = {"kode": kode, "nama_folder": nama_folder, "out_base": out_base,
           "jenis_pl": jenis_pl, "workflow": item.get("workflow", ""), "target": target, "template_dir": item.get("template_dir", ""),
           "ok": False, "setup_ok": False, "output_ok": False,
           "download_ok": not bool(cfg.get("dl_dokumen")), "hps_ok": False,
           "log": [], "files_ok": [], "hps_hasil": None}
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
        if item.get("workflow"):
            _cmd_setup += ["--workflow", item["workflow"]]
        if item.get("template_dir"):
            _cmd_setup += ["--template-dir", item["template_dir"]]
        _cmd_setup.append(nama_folder)
        r2 = _sp.run(
            _cmd_setup,
            capture_output=True, text=True, timeout=120, creationflags=cfg["no_win"],
        )
        if r2.returncode == 0:
            res["setup_ok"] = True
            res["output_ok"], _output_error = _pl_output_dasar_valid(target)
            if not res["output_ok"]:
                log(f"Validasi output gagal: {_output_error}")
                _emit("output dasar tidak valid")
                return res
        if r2.returncode != 0:
            log(f"❌ Gagal buat folder: rc={r2.returncode}\nout_base={out_base!r}\nfolder={nama_folder!r}\n{r2.stderr}")
            _emit("❌ gagal buat folder")
            return res
        log("✅ Folder dibuat")
        # Prompt audit HPS dibuat sejak folder berhasil dibuat, sehingga tetap
        # tersedia walau fetch HPS/SPSE pada fase berikutnya gagal.
        try:
            _prompt_hps = _hps_eng.tulis_prompt_audit_hps_agy(kode, target)
            log(f"📄 Prompt audit HPS Agy: {os.path.basename(_prompt_hps)}")
        except Exception as _prompt_e:
            log(f"⚠ Prompt audit HPS Agy: {_prompt_e}")
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
            _copied = _copy_pl_evaluator_files(
                target,
                cfg["pokja_root"],
                jenis_pl,
            )
            log(f"📄 Evaluator: {len(_copied)} file disalin" if _copied else "⚠ Evaluator: tidak ada file ditemukan di root POKJA")
            _step("evaluator", _t_step)
        except Exception as _ev_e:
            log(f"⚠ Evaluator copy: {_ev_e}")
            _step("evaluator", _t_step, " error")

        # Status DB ditandai setelah finalisasi di app.py.
        if cfg["dl_dokumen"] and kode:
            # 3. Download dokumen SPSE (cookie di-pass, merge ditunda → serial pasca-pool)
            if not cookie_str:
                log("❌ Download error: Cookie SPSE kosong — buka Brave SPSE dan login ulang.")
            else:
                try:
                    _emit("⬇️ mulai download")
                    _t_step = _tm.perf_counter()
                    _dl = _engine.download_dokumen_paket_pl(
                        kode, target, cookie_str=cookie_str, skip_merge=True,
                        force_clean=True,
                    )
                    res["files_ok"] = _dl.get("ok", [])
                    _download_errors = _dl.get("error", [])
                    res["download_ok"] = _pl_download_success(
                        res["files_ok"], _download_errors
                    )
                    log(f"📎 Download: ✅{len(_dl.get('ok', []))} file")
                    _step("download", _t_step)
                    _emit(f"✅ download {len(_dl.get('ok', []))} file")
                    for _e in _download_errors:
                        _optional_nd = str(_e or "").startswith("Nota Dinas PPK:")
                        log(f"  {'⚠️' if _optional_nd else '❌'} {_e}")
                except Exception as _dl_e:
                    log(f"❌ Download error: {_dl_e}")
                    _step("download", _t_step, " error")
            if not res["download_ok"]:
                log("Validasi download gagal: paket tetap retryable")
                _emit("download gagal")
                return res
            # 4. Parse KAK
            try:
                _t_step = _tm.perf_counter()
                _kak_p = _pkpl.cari_kak_di_folder(target)
                if _kak_p:
                    _kak_u = {k: v for k, v in _pkpl.parse_kak(_kak_p).items() if v}
                    # Untuk paket SPSE, lokasi dari /viewdraftpl adalah sumber
                    # otoritatif. KAK tetap dipakai untuk durasi/SBU/jabatan,
                    # tetapi hasil parsing lokasi tidak boleh menimpa format
                    # lokasi resmi SPSE (mis. "Kecamatan ... - Tapin (Kab.)").
                    _kak_u.pop("lokasi", None)
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
            # Lengkapi personel dari PDF/DOCX dan metadata parser sekarang,
            # sebelum macro Excel membaca row Supabase. Ini mencegah workbook
            # pertama kali dibuka dalam keadaan personel kosong.
            try:
                _t_step = _tm.perf_counter()
                _full_logs = []
                _full_res = _pkpl.serap_penyedia_pl(
                    kode_paket_filter=kode,
                    progress_cb=lambda _p, _m: _full_logs.append(_m),
                )
                if _full_res.get("errors"):
                    log(f"⚠ Parser lengkap: {_full_res['errors'][0]}")
                else:
                    log("👥 Parser lengkap: personel/metadata disinkronkan")
                _step("parser lengkap", _t_step)
            except Exception as _full_e:
                log(f"⚠ Parser lengkap: {_full_e}")
                _step("parser lengkap", _t_step, " error")
        # NOTE: Serap penyedia full SENGAJA tidak dijalankan di sini.
        # Personil 3-layer tetap di tahap "Download Dokumen Kualifikasi" (Tab 6).

        # 6. Scrape HPS + tulis _HPS_.md (tanpa COM)
        try:
            _t_step = _tm.perf_counter()
            _xlsm = _cari_xlsm_pl(target)
            _hps = _hps_eng.scrape_hps_pl(kode)
            if _hps and _hps.get("items") and _xlsm:
                _hps_eng._tulis_hps_ke_md(kode, _xlsm, _hps)
                res["hps_ok"] = True
                res["hps_hasil"] = _hps
                log(f"📄 HPS.md: {len(_hps['items'])} item")
                _emit(f"📄 HPS {len(_hps['items'])} item")
            else:
                _local_hps, _local_path = _local_hps_fallback(target, kode)
                if _local_hps:
                    res["hps_ok"] = True
                    res["hps_hasil"] = _local_hps
                    log(f"⚠ HPS live kosong; memakai fallback lokal: {os.path.basename(_local_path)}")
                else:
                    log("⚠ HPS.md: tidak ada item HPS")
            _step("HPS.md", _t_step)
        except Exception as _hps_e:
            _local_hps, _local_path = _local_hps_fallback(target, kode)
            if _local_hps:
                res["hps_ok"] = True
                res["hps_hasil"] = _local_hps
                log(f"⚠ HPS live gagal; memakai fallback lokal: {os.path.basename(_local_path)}")
            else:
                log(f"⚠ HPS.md: {_hps_e}")
            _step("HPS.md", _t_step, " error")

        res["ok"] = _pl_io_success(res, bool(cfg.get("dl_dokumen")))
        if not res["ok"]:
            log("I/O belum lengkap; paket tetap retryable")
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


def _pl_folder_number(row: dict) -> str:
    """Ambil nomor folder dari metadata/path bila nomor DB belum terisi."""
    candidates = (
        row.get("_folder_lokal"),
        row.get("folder_dibuat") if isinstance(row.get("folder_dibuat"), str) else None,
    )
    for candidate in candidates:
        name = os.path.basename(os.fspath(candidate)) if candidate else ""
        match = re.match(r"^\s*(\d+)\.", name)
        if match:
            return match.group(1)
    return ""


def _pl_label(row: dict) -> str:
    """Label tampilan paket PL yang konsisten di seluruh tab.

    Nomor urut hanya untuk display; nama_paket asli tetap dipakai untuk
    resolusi folder, payload SPSE, dan pencocokan database.
    """
    nama = str(row.get("nama_paket") or row.get("kode_paket") or "-").strip()
    nomor = (
        str(row.get("nomor_urut") or "").strip()
        or str(row.get("_display_nomor_urut") or "").strip()
        or _pl_folder_number(row)
    )
    if nomor and not nama.startswith(f"{nomor}."):
        nama = f"{nomor}. {nama}"
    return nama + _pl_hint_ulang(row)


def _pl_checkbox_label(row: dict) -> str:
    """Label checkbox Streamlit; lindungi nomor awal dari parser ordered list."""
    label = _pl_label(row)
    return re.sub(r"^(\d+)\.(\s+)", r"\1\\.\2", label, count=1)


_PL_FOLDER_RE = re.compile(
    r"^\s*(\d+)\.\s*PL(?:JKK|PK)\s*-\s*(.+?)\s*$",
    re.IGNORECASE,
)


def _pl_folder_name_key(value: str) -> str:
    """Normalisasi nama paket untuk pencocokan backup yang mungkin terpotong."""
    text = str(value or "").strip()
    text = re.sub(r"^\s*(?:\d+\.\s*)?PL(?:JKK|PK)\s*-\s*", "", text, flags=re.IGNORECASE)
    text = re.sub(r"\s*\(\s*PL\s*-\s*Ulang\s*\)\s*$", "", text, flags=re.IGNORECASE)
    text = re.sub(r"[^\w]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip().casefold()


def _pl_numbered_dirs(root: str, include_backup: bool = False) -> list[tuple[int, str]]:
    """Ambil folder bernomor langsung dari root; tidak scan karantina nested."""
    try:
        entries = os.listdir(root)
    except OSError:
        return []
    result = []
    for name in entries:
        if not include_backup and (name.casefold() == "backup" or name.startswith("_")):
            continue
        full = os.path.join(root, name)
        if not os.path.isdir(full):
            continue
        match = _PL_FOLDER_RE.match(name)
        if match:
            result.append((int(match.group(1)), name))
    return result


def _pl_backup_match(row: dict, output_base: str) -> tuple[int, str, float] | None:
    """Cari nomor lama dari folder backup tingkat pertama secara konservatif."""
    backup = os.path.join(output_base, "backup")
    expected_kind = str(row.get("jenis_pl") or "JKK").strip().upper()
    expected = _pl_folder_name_key(row.get("nama_paket") or "")
    if not expected or not os.path.isdir(backup):
        return None

    candidates = []
    try:
        names = os.listdir(backup)
    except OSError:
        return None
    for name in names:
        full = os.path.join(backup, name)
        if not os.path.isdir(full) or name.startswith("_"):
            continue
        match = _PL_FOLDER_RE.match(name)
        if not match:
            continue
        prefix_kind = re.search(r"PL(JKK|PK)", name, flags=re.IGNORECASE)
        if not prefix_kind or prefix_kind.group(1).upper() != expected_kind:
            continue
        physical = _pl_folder_name_key(name)
        if not physical:
            continue
        if physical == expected or physical.startswith(expected) or expected.startswith(physical):
            score = 1.0
        else:
            expected_words = set(expected.split())
            physical_words = set(physical.split())
            score = len(expected_words & physical_words) / max(len(expected_words), 1)
        if score >= 0.72:
            candidates.append((score, int(match.group(1)), name))

    if not candidates:
        return None
    candidates.sort(reverse=True)
    best = candidates[0]
    if len(candidates) > 1 and best[0] - candidates[1][0] < 0.03:
        return None
    return best[1], best[2], best[0]


def _pl_clean_pk_reset_root(root: str) -> bool:
    """True hanya saat root PK masih menyisakan paket canonical 28, 29, 30."""
    numbered = _pl_numbered_dirs(root)
    if len(numbered) != 3 or {number for number, _name in numbered} != {28, 29, 30}:
        return False
    return all(
        re.match(r"^\s*\d+\.\s*PLPK\s*-", name, flags=re.IGNORECASE)
        for _number, name in numbered
    )


def plan_nomor_folder_pl(
    rows: list[dict],
    output_bases: tuple[str, ...],
    *,
    use_backup: bool = True,
    use_database: bool = True,
    start_number: int | None = None,
    allocation_base: str | None = None,
) -> dict:
    """Rencanakan nomor folder PL tanpa mengubah filesystem/Database.

    Mode normal: backup canonical → nomor_urut DB → nomor baru.
    Mode reset bersih hanya aktif bila ``allocation_base`` masih tepat berisi
    folder PK 28, 29, 30. Mode ini mengabaikan backup/DB dan mulai dari
    ``start_number``. Begitu folder baru dibuat, guard mati dan mode normal
    otomatis dipakai lagi.
    """
    reset_requested = (
        not use_backup
        and not use_database
        and start_number is not None
        and bool(allocation_base)
    )
    reset_active = reset_requested and _pl_clean_pk_reset_root(allocation_base)
    if reset_requested and not reset_active:
        # Caller meminta reset, tetapi root sudah berubah; kembali ke allocator
        # normal agar retry tidak terus mengabaikan state baru.
        use_backup = True
        use_database = True

    active_numbers = {
        number
        for root in output_bases
        for number, _name in _pl_numbered_dirs(root)
    }
    backup_numbers = {
        number
        for root in output_bases
        for number, _name in _pl_numbered_dirs(os.path.join(root, "backup"))
    } if use_backup else set()

    records = []
    stable_numbers = set()
    for row in rows or []:
        code = str(row.get("kode_paket") or "").strip()
        kind = str(row.get("jenis_pl") or "JKK").strip().upper()
        backup_match = None
        if use_backup:
            for root in output_bases:
                if (kind == "JKK" and not root.casefold().endswith("jkk")) or (
                    kind == "PK" and not root.casefold().endswith("pk")
                ):
                    continue
                backup_match = _pl_backup_match(row, root)
                if backup_match:
                    break
        db_value = str(row.get("nomor_urut") or "").strip()
        db_number = int(db_value) if use_database and db_value.isdigit() else None
        if backup_match:
            number, source_name, score = backup_match
            source = "backup"
        elif db_number is not None:
            number, source_name, score = db_number, "database", 1.0
            source = "database"
        else:
            number, source_name, score = None, "nomor baru", 0.0
            source = "baru"
        if number is not None:
            stable_numbers.add(number)
        records.append({
            "kode_paket": code,
            "nomor_urut": number,
            "source": source,
            "source_name": source_name,
            "match_score": score,
        })

    used = set(active_numbers) | set(backup_numbers) | set(stable_numbers)
    assignments = {}
    conflicts = []
    assigned_numbers = {}
    for record in records:
        code = record["kode_paket"]
        number = record["nomor_urut"]
        if number is None:
            continue
        if number in active_numbers:
            conflicts.append(f"Nomor {number} masih dipakai folder aktif: {code or '-'}")
        previous = assigned_numbers.get(number)
        if previous and previous != code:
            conflicts.append(f"Nomor {number} dipetakan ke {previous} dan {code}")
        assigned_numbers[number] = code
        assignments[code] = record

    if reset_active:
        # Reset PK dimulai dari state root PK, bukan nomor tinggi JKK yang
        # kebetulan ada di output_bases. ``used`` tetap global agar collision
        # dengan folder aktif keluarga lain dihindari saat rentang bertemu.
        allocation_active_numbers = {
            number
            for number, _name in _pl_numbered_dirs(allocation_base)
        }
        next_number = max(
            int(start_number),
            max(allocation_active_numbers or {int(start_number) - 1}) + 1,
        )
    else:
        next_number = max(used or {0}) + 1
    for record in records:
        if record["nomor_urut"] is not None:
            continue
        while next_number in used:
            next_number += 1
        record["nomor_urut"] = next_number
        record["source"] = "baru"
        used.add(next_number)
        assignments[record["kode_paket"]] = record
        next_number += 1

    return {
        "assignments": assignments,
        "conflicts": list(dict.fromkeys(conflicts)),
        "active_numbers": sorted(active_numbers),
        "backup_numbers": sorted(backup_numbers),
    }

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


class _LocalDokpilFile:
    """Adaptor minimal agar PDF lokal kompatibel dengan UploadedFile Streamlit."""

    def __init__(self, path: str):
        self._path = str(path)
        self.name = os.path.basename(self._path)

    def getvalue(self) -> bytes:
        with open(self._path, "rb") as stream:
            return stream.read()


def _find_dokpil_pdf_root(folder_paket: str) -> dict:
    """Cari Dokpil PDF hanya pada root folder paket.

    Tidak recursive: subfolder sengaja diabaikan agar Dokpil paket lain atau
    dokumen pendukung di ``2. Rancangan Kontrak`` tidak ikut terpilih.
    Kandidat ambigu tidak ditebak dan diserahkan ke fallback manual UI.
    """
    if not folder_paket or not os.path.isdir(folder_paket):
        return {"status": "missing", "path": "", "candidates": []}

    candidates = []
    try:
        entries = os.scandir(folder_paket)
    except OSError:
        return {"status": "missing", "path": "", "candidates": []}

    with entries:
        for entry in entries:
            if not entry.is_file() or not entry.name.casefold().endswith(".pdf"):
                continue
            name = entry.name.casefold()
            if "dokpil" not in name and "dokumen pemilihan" not in name:
                continue
            if any(token in name for token in ("backup", ".tmp", "~$")):
                continue
            candidates.append(entry.path)

    candidates.sort(key=lambda path: os.path.basename(path).casefold())
    if len(candidates) == 1:
        return {"status": "found", "path": candidates[0], "candidates": candidates}
    if len(candidates) > 1:
        return {"status": "ambiguous", "path": "", "candidates": candidates}
    return {"status": "missing", "path": "", "candidates": []}


def _resolve_dokpil_file_root(row: dict, manual_file=None):
    """Pilih file manual bila ada, selain itu gunakan Dokpil PDF root otomatis."""
    if manual_file is not None:
        return manual_file
    detected = _find_dokpil_pdf_root(row.get("_folder_lokal") or "")
    if detected["status"] == "found":
        return _LocalDokpilFile(detected["path"])
    return None


def update_hps_paket_pl(kode_paket: str, hasil_engine, progress_cb=None) -> dict:
    """Refresh HPS live ke sheet ``5. HPS`` dengan backup workbook unik."""
    try:
        workbook = hasil_engine._find_xlsm(kode_paket)
    except Exception as exc:
        return {"ok": False, "pesan": f"Gagal mencari workbook: {exc}", "count": 0}

    if not workbook or not os.path.isfile(workbook):
        return {"ok": False, "pesan": "Workbook .xlsm tidak ditemukan", "count": 0}

    # Sediakan prompt audit bahkan bila backup atau fetch HPS berikutnya gagal.
    hps_prompt_path = ""
    try:
        import hps_engine as _hps_prompt_engine
        hps_prompt_path = _hps_prompt_engine.tulis_prompt_audit_hps_agy(
            kode_paket, workbook, mode="pl"
        )
    except Exception:
        pass

    source = pathlib.Path(workbook)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    # Backup workbook tidak boleh berada di root paket: resolver VBA/Word
    # dapat salah memilihnya sebagai workbook aktif. Simpan di subfolder
    # khusus yang selalu dikecualikan oleh resolver.
    backup_dir = source.parent / ".vba-backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_candidate = backup_dir / (
        f"{source.stem}.backup_{stamp}_{uuid.uuid4().hex[:8]}{source.suffix}"
    )
    try:
        # Folder paket PL dapat sudah mendekati batas MAX_PATH Windows. Pakai
        # resolver yang sama dengan archive dokumen PPK agar nama backup tidak
        # membuat copy2 gagal dengan WinError 3 sebelum writer HPS dijalankan.
        from dokumen_ppk_engine import _fit_local_destination
        backup_path, _ = _fit_local_destination(str(backup_candidate))
        backup = pathlib.Path(backup_path)
        shutil.copy2(source, backup)
    except Exception as exc:
        return {
            "ok": False,
            "pesan": f"Backup workbook gagal: {exc}",
            "count": 0,
            "hps_prompt_path": hps_prompt_path,
        }

    if progress_cb:
        progress_cb(f"Backup HPS: {backup.name}")

    try:
        import hps_engine
        result = hps_engine.scrape_hps_pl_ke_excel(
            kode_paket, str(source), progress_cb=progress_cb
        )
    except Exception as exc:
        result = {"ok": False, "pesan": str(exc), "count": 0}

    result = dict(result or {})
    result.setdefault("ok", False)
    result.setdefault("pesan", "Tidak ada respons dari writer HPS")
    result.setdefault("count", 0)
    result["backup_path"] = str(backup)
    if hps_prompt_path:
        result.setdefault("hps_prompt_path", hps_prompt_path)
    return result


def _open_excel_for_pl_action():
    """Buka instance Excel terisolasi untuk aksi workbook PL."""
    import pythoncom
    import pywintypes
    import win32com.client

    pythoncom.CoInitialize()
    try:
        excel = win32com.client.DispatchEx("Excel.Application")
    except Exception:
        pythoncom.CoUninitialize()
        raise
    excel.Visible = False
    excel.DisplayAlerts = False
    try:
        excel.AutomationSecurity = 1
    except Exception as exc:
        try:
            excel.Quit()
        finally:
            pythoncom.CoUninitialize()
        raise RuntimeError(
            "Excel AutomationSecurity gagal diatur ke macro-enabled; "
            "aksi workbook dibatalkan agar cache UDF tidak rusak."
        ) from exc
    # Macro tetap tersedia untuk UDF, tetapi Workbook_Open/SheetChange tidak
    # boleh menjadi side effect pada aksi Streamlit.
    excel.EnableEvents = False
    return pythoncom, pywintypes, excel


def _scan_pl_formula_errors(workbook, sheet_names=None):
    """Baca error formula cached tanpa memaksa full recalculation workbook."""
    error_tokens = {"#NAME?", "#VALUE!", "#REF!", "#DIV/0!", "#N/A", "#NUM!", "#NULL!"}
    names = sheet_names or ("satu_data", "@ Evaluasi", "5. HPS", "7.2 Dengan Nego")
    found = []
    for sheet_name in names:
        try:
            ws = workbook.Worksheets(sheet_name)
            used = ws.UsedRange
            row_count = min(int(used.Rows.Count), 1000)
            col_count = min(int(used.Columns.Count), 80)
            first_row = int(used.Row)
            first_col = int(used.Column)
            for row in range(first_row, first_row + row_count):
                for col in range(first_col, first_col + col_count):
                    text = str(ws.Cells(row, col).Text or "").strip().upper()
                    if text in error_tokens:
                        found.append(f"{sheet_name}!{ws.Cells(row, col).Address(False, False)}={text}")
                        if len(found) >= 20:
                            return found
        except Exception:
            continue
    return found


def refresh_evaluasi_pl_only(kode_paket: str, hasil_engine, progress_cb=None) -> dict:
    """Jalankan macro refresh ``@ Evaluasi`` tanpa mengisi ``@ Master Data``.

    Macro ``IsiEvaluasiPLStandalone`` membaca metadata workbook/Supabase lalu
    mengisi sheet ``@ Evaluasi``. Jalur ini sengaja tidak memanggil
    ``IsiDataPLByKode`` atau helper writer ``@ Master Data``.
    """
    def log(message):
        if progress_cb:
            progress_cb(message)

    try:
        workbook = hasil_engine._find_xlsm(kode_paket)
    except Exception as exc:
        return {"ok": False, "pesan": f"Gagal mencari workbook: {exc}", "workbook": ""}
    if not workbook or not os.path.isfile(workbook):
        return {"ok": False, "pesan": "Workbook .xlsm tidak ditemukan", "workbook": ""}

    pythoncom = None
    excel = None
    wb = None
    silent_set = False
    try:
        import pywintypes

        pythoncom, pywintypes, excel = _open_excel_for_pl_action()
        log(f"Membuka Excel: {os.path.basename(workbook)}")
        wb = excel.Workbooks.Open(
            os.path.abspath(workbook),
            UpdateLinks=0,
            ReadOnly=False,
            IgnoreReadOnlyRecommended=True,
            AddToMru=False,
        )
        if bool(wb.ReadOnly):
            return {
                "ok": False,
                "pesan": "Workbook terbuka ReadOnly; tutup Excel paket lalu ulangi.",
                "workbook": workbook,
            }

        try:
            excel.Run("ModDraftPaketPL.SetSilentPL", True)
            silent_set = True
        except pywintypes.com_error as exc:
            return {
                "ok": False,
                "pesan": f"Macro SetSilentPL tidak tersedia/compile error: {exc}",
                "workbook": workbook,
            }

        log("Menjalankan refresh sheet @ Evaluasi...")
        before_errors = _scan_pl_formula_errors(wb)
        if before_errors:
            return {
                "ok": False,
                "pesan": "Workbook sudah memiliki error formula; save dibatalkan: " + "; ".join(before_errors[:5]),
                "workbook": workbook,
            }
        excel.Run("ModDraftPaketPL.IsiEvaluasiPLStandalone")
        # Kalkulasi scoped saja. CalculateFull/CalculateUntilAsyncQueriesDone
        # pernah mengubah cache UDF tanggal menjadi #NAME? pada workbook PL.
        # Urutan wajib mengikuti dependensi: sumber -> nego -> evaluasi ->
        # mail-merge. Menghitung @ Evaluasi lebih dulu meninggalkan cache
        # lama (contoh total Rp8 juta, padahal 7.2 sudah Rp399 juta).
        for _sheet_name in (
            "5. HPS",
            "6. Penawaran",
            "6. Harga Penawaran",
            "7.2 Dengan Nego",
            "@ Evaluasi",
            "satu_data",
        ):
            try:
                wb.Worksheets(_sheet_name).Calculate()
            except Exception:
                pass
        after_errors = _scan_pl_formula_errors(wb)
        if after_errors:
            return {
                "ok": False,
                "pesan": "Refresh dibatalkan karena menghasilkan error formula: " + "; ".join(after_errors[:5]),
                "workbook": workbook,
            }
        excel.Run("ModDraftPaketPL.SetSilentPL", False)
        silent_set = False
        wb.Save()
        log("@ Evaluasi terisi dan workbook tersimpan.")
        return {
            "ok": True,
            "pesan": "@ Evaluasi berhasil diisi.",
            "workbook": workbook,
        }
    except pywintypes.com_error as exc:
        return {"ok": False, "pesan": f"Excel COM error: {exc}", "workbook": workbook}
    except Exception as exc:
        return {"ok": False, "pesan": str(exc), "workbook": workbook}
    finally:
        if wb is not None:
            if silent_set and excel is not None:
                try:
                    excel.Run("ModDraftPaketPL.SetSilentPL", False)
                except Exception:
                    pass
            try:
                wb.Close(SaveChanges=False)
            except Exception:
                pass
        if excel is not None:
            try:
                excel.Quit()
            except Exception:
                pass
        if pythoncom is not None:
            try:
                pythoncom.CoUninitialize()
            except Exception:
                pass


def _provider_master_cells(row: dict) -> tuple[str, str]:
    """Pilih cell identitas penyedia sesuai template workflow PL."""
    jenis = str(row.get("jenis_pl") or "").strip().upper()
    if jenis in {"PK", "PLPK", "KONSTRUKSI", "PL - KONSTRUKSI"}:
        return "C77", "C78"
    return "C51", "C52"


def _baca_identitas_penyedia_pl(row: dict) -> dict:
    """Baca identitas penyedia dari cell authoritative workbook secara read-only.

    Template PLJKK menyimpan identitas pada ``C51:C52``. Template PLPK
    menyimpan identitas pada ``C77:C78``; jangan memakai hasil parser PDF
    sebagai pengganti nilai workbook karena isi PDF dapat terbaca sebagai
    personil/peralatan (misalnya ``1 Unit``).
    """
    try:
        import parse_kak_pl as _pkl_id
        folder = row.get("_folder_lokal")
        if not folder:
            folder, _ = _pkl_id._resolve_folder_pl(
                row.get("nomor_urut"), row.get("nama_paket") or "",
                row.get("jenis_pl") or "JKK", is_ulang=bool(row.get("is_ulang")),
            )
        xlsm = (
            row.get("_xlsm_lokal") or _cari_xlsm_pl(folder)
            if folder else None
        )
        if not xlsm or not os.path.isfile(xlsm):
            return {}
        name_cell, npwp_cell = _provider_master_cells(row)
        stat = os.stat(xlsm)
        values = pl_engine.read_master_cells_cached(
            xlsm,
            stat.st_mtime_ns,
            stat.st_size,
            (name_cell, npwp_cell),
        )
        return {
            "nama_penyedia": values.get(name_cell, ""),
            "npwp_penyedia": values.get(npwp_cell, ""),
        }
    except Exception:
        return {}


def sinkronkan_identitas_penyedia_pl(row: dict, provider: dict, progress_cb=None) -> dict:
    """Persist identitas API SPSE ke Supabase dan Excel Master Data.

    API SPSE menjadi sumber authoritative setelah pemilihan berhasil. Supabase
    tetap disimpan untuk cache UI, sedangkan cell identitas workbook menjadi
    source-of-truth lokal generator (PLJKK ``C51:C52``; PLPK ``C77:C78``).
    """
    def log(message):
        if progress_cb:
            progress_cb(message)

    nama = str(provider.get("nama_penyedia") or provider.get("nama") or "").strip()
    npwp = str(
        provider.get("npwp_penyedia")
        or provider.get("rkn_npwp_16")
        or provider.get("rkn_npwp")
        or provider.get("npwp")
        or ""
    ).strip()
    if not nama and not npwp:
        return {"ok": False, "excel_ok": False, "db_ok": False, "pesan": "Response SPSE tidak membawa nama/NPWP."}

    excel_result = {"ok": False, "pesan": "Workbook tidak ditemukan."}
    try:
        from isi_master_data_pl import tulis_identitas_penyedia_ke_excel
        folder = row.get("_folder_lokal")
        xlsm = row.get("_xlsm_lokal")
        if not xlsm:
            import parse_kak_pl as _pkl_x
            folder, _ = _pkl_x._resolve_folder_pl(
                row.get("nomor_urut"), row.get("nama_paket") or "",
                row.get("jenis_pl") or "JKK", is_ulang=bool(row.get("is_ulang")),
            )
            xlsm = _cari_xlsm_pl(folder) if folder else None
        if xlsm:
            name_cell, npwp_cell = _provider_master_cells(row)
            excel_result = tulis_identitas_penyedia_ke_excel(
                xlsm,
                nama,
                npwp,
                name_cell=name_cell,
                npwp_cell=npwp_cell,
                progress_cb=log,
            )
    except Exception as exc:
        excel_result = {"ok": False, "pesan": str(exc)}

    db_ok = False
    db_message = ""
    try:
        from config import sb as _sb_provider
        payload = {"nama_penyedia": nama, "npwp_penyedia": npwp}
        _sb_provider().table("draft_paket_pl").update(payload).eq(
            "kode_paket", str(row.get("kode_paket") or "")
        ).execute()
        db_ok = True
    except Exception as exc:
        db_message = str(exc)

    excel_ok = bool(excel_result.get("ok"))
    name_cell, npwp_cell = _provider_master_cells(row)
    if excel_ok and db_ok:
        message = f"Nama/NPWP SPSE tersimpan ke Excel {name_cell}:{npwp_cell} dan Supabase."
    elif excel_ok:
        message = f"Excel tersimpan; Supabase gagal: {db_message}"
    elif db_ok:
        message = f"Supabase tersimpan; Excel gagal: {excel_result.get('pesan', '-') }"
    else:
        message = f"Excel gagal: {excel_result.get('pesan', '-')}; Supabase gagal: {db_message}"
    return {"ok": excel_ok and db_ok, "excel_ok": excel_ok, "db_ok": db_ok, "pesan": message}


# Compatibility alias: app.py memakai nama private lama, sedangkan helper
# canonical memakai nama public tanpa underscore. Jangan pecahkan startup
# lintas-PC hanya karena salah satu clone membawa salah satu nama.
_sinkronkan_identitas_penyedia_pl = sinkronkan_identitas_penyedia_pl

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


def _resolve_nomor_dokpil_excel_pl(row: dict) -> dict:
    """Resolve nomor Dokpil dari workbook paket, bukan cache/PDF/Supabase.

    ``@ Master Data!C20`` menjadi sumber tunggal. Nilai invalid dikembalikan
    sebagai kosong supaya caller tidak diam-diam jatuh ke generator legacy.
    """
    from upload_dokpil_pl import validate_nomor_dokpil

    master = _baca_master_data_pl(row)
    if not master:
        return {
            "ok": False,
            "nomor_dokpil": "",
            "master_data": {},
            "error": "workbook paket atau sheet @ Master Data tidak ditemukan",
        }
    raw = str(master.get("nomor_dokpil") or "").strip()
    ok, error = validate_nomor_dokpil(raw)
    return {
        "ok": ok,
        "nomor_dokpil": raw if ok else "",
        "master_data": master,
        "error": error,
    }

def _proses_excel_paket_pl(target_dir, kode_paket, jenis_pl, refresh_on,
                            template_dir_jkk, template_dir_pk, hps_hasil_preloaded=None,
                            tanggal_create=None):
    """Refresh template (jika on) -> resolve xlsm -> fetch HPS (no COM) ->
    1 sesi COM gabungan (HPS + Master Data). Return status terstruktur.
    Urutan BENAR: Refresh dulu (hapus xlsm lama, copy fresh), baru
    resolve xlsm (nama mungkin berubah), lalu tulis HPS + IsiDataPLByKode
    dalam 1x DispatchEx.
    """
    import hps_engine as _hps_eng2
    import isi_master_data_pl as _imd2
    logs = []
    result = {
        "ok": False, "refresh_ok": not refresh_on, "hps_ok": False,
        "master_data_ok": False, "logs": logs, "xlsm": "",
        "hps_source": "", "hps_sync_ok": False, "hps_prompt_path": "",
    }

    # 1. Refresh template DULU (hapus xlsm lama, copy fresh)
    if refresh_on:
        try:
            from refresh_template import refresh_template_paket as _rt_fn2
            from pathlib import Path as _rt_P2
            _rt_mode2 = "pl_jkk" if jenis_pl == "JKK" else "pl_pk"
            _rt_src2  = _rt_P2(template_dir_jkk if jenis_pl == "JKK" else template_dir_pk)
            _rt_fn2([_rt_P2(target_dir)], _rt_src2, _rt_mode2, auto_relink=True, dry_run=False)
            logs.append("Refresh Template: selesai")
            result["refresh_ok"] = True
        except Exception as _rt_e2:
            logs.append(f"WARN Refresh Template: {_rt_e2}")

    # 2. Resolve xlsm SETELAH refresh (nama file bisa berubah)
    xlsm = _cari_xlsm_pl(target_dir)
    if not xlsm:
        logs.append("WARN Excel dilewati -- tidak ada .xlsm setelah refresh")
        return result
    result["xlsm"] = xlsm

    # Jalur ini dapat dipanggil ulang tanpa worker I/O; pastikan prompt audit
    # tetap tersedia setiap kali bulk-create memproses workbook paket.
    try:
        result["hps_prompt_path"] = _hps_eng2.tulis_prompt_audit_hps_agy(
            kode_paket, target_dir, mode="pl"
        )
        logs.append("Prompt audit HPS Agy: tersedia")
    except Exception as _prompt_e2:
        logs.append(f"WARN Prompt audit HPS Agy: {_prompt_e2}")

    # 3. Gunakan hasil worker bila sudah tersedia; bila tidak, fetch live lalu
    # fallback ke _HPS_*.md yang identitas kodenya sudah diverifikasi.
    hps_hasil = hps_hasil_preloaded if (hps_hasil_preloaded or {}).get("items") else None
    if hps_hasil:
        result["hps_ok"] = True
        result["hps_source"] = hps_hasil.get("nilai_hps_source") or "worker_live"
        if result["hps_source"] == "local_hps_md_fallback":
            result["hps_sync_ok"] = True
            logs.append("HPS summary: dipertahankan dari fallback lokal")
        else:
            try:
                result["hps_sync_ok"] = bool(_hps_eng2._sync_pl_summary(kode_paket, hps_hasil))
                if not result["hps_sync_ok"]:
                    logs.append("WARN HPS summary: gagal sinkron ke Supabase")
            except Exception as _hps_sync_e:
                logs.append(f"WARN HPS summary: {_hps_sync_e}")
        logs.append(f"HPS: {len(hps_hasil['items'])} baris dari worker")
    else:
        try:
            hps_hasil = _hps_eng2.scrape_hps_pl(kode_paket)
            if not hps_hasil.get("items"):
                logs.append("WARN HPS: tidak ada item (fetch gagal/kosong)")
                hps_hasil, _local_path = _local_hps_fallback(target_dir, kode_paket)
                if hps_hasil:
                    result["hps_ok"] = True
                    result["hps_source"] = "local_hps_md_fallback"
                    result["hps_sync_ok"] = True
                    logs.append(f"HPS: fallback lokal {_local_path}")
            else:
                result["hps_ok"] = True
                result["hps_source"] = hps_hasil.get("nilai_hps_source", "")
                try:
                    result["hps_sync_ok"] = bool(_hps_eng2._sync_pl_summary(kode_paket, hps_hasil))
                    if not result["hps_sync_ok"]:
                        logs.append("WARN HPS summary: gagal sinkron ke Supabase")
                except Exception as _hps_sync_e:
                    logs.append(f"WARN HPS summary: {_hps_sync_e}")
        except Exception as _hps_e2:
            logs.append(f"WARN HPS fetch: {_hps_e2}")
            hps_hasil, _local_path = _local_hps_fallback(target_dir, kode_paket)
            if hps_hasil:
                result["hps_ok"] = True
                result["hps_source"] = "local_hps_md_fallback"
                result["hps_sync_ok"] = True
                logs.append(f"HPS: fallback lokal {_local_path}")

    # 4. 1 sesi COM: tulis HPS + IsiDataPLByKode
    try:
        _res2 = _imd2.proses_hps_dan_master_data(
            kode_paket,
            xlsm,
            hps_hasil,
            jenis_pl=jenis_pl,
            tanggal_create=tanggal_create,
        )
        _hps_r2 = _res2.get("hps", {})
        _md_r2  = _res2.get("md", {})
        if hps_hasil:
            result["hps_ok"] = bool(_hps_r2.get("ok") and _hps_r2.get("count", 0) > 0)
        if _hps_r2.get("ok") and _hps_r2.get("count", 0) > 0:
            source = result.get("hps_source") or "tidak diketahui"
            logs.append(f"HPS: {_hps_r2['count']} baris -> Excel ({source})")
        elif hps_hasil:
            logs.append(f"WARN HPS tulis: {_hps_r2.get('pesan','-')}")
        if _md_r2.get("ok"):
            result["master_data_ok"] = True
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

    result["ok"] = bool(
        result["refresh_ok"]
        and result["hps_ok"]
        and result["hps_sync_ok"]
        and result["master_data_ok"]
    )
    return result

def _template_dir_pl_jkk(row, default_dir):
    # V2: pilih donor berdasarkan subjenis paket, bukan hanya JKK/PK.
    # Profil header instansi ditentukan saat output Word/PDF dibuat.
    try:
        _cfg_core = _core_workflow_config()
        workflow = _cfg_core.detect_pl_workflow(row, row.get("jenis_pl"))
        resolved = _cfg_core.pl_workflow_template_dir(workflow)
        if os.path.isdir(resolved):
            return resolved
    except Exception:
        pass
    # Kompatibilitas donor lama, termasuk folder Disdag.
    satker = " ".join(str(row.get(k) or "") for k in ("satker", "nama_satker", "nama_dinas"))
    if re.search(r"perdagangan|disdag", satker, re.IGNORECASE):
        return str(pathlib.Path(default_dir).with_name("Development - PL - JKK - Disdag"))
    return default_dir


def _pl_workflow(row):
    """Public resolver workflow V2 untuk UI dan setup subprocess."""
    return _core_workflow_config().detect_pl_workflow(row, row.get("jenis_pl"))


def _read_template_meta(package_dir):
    path = pathlib.Path(package_dir) / ".template-meta.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def _write_template_meta(package_dir, data):
    path = pathlib.Path(package_dir) / ".template-meta.json"
    tmp = path.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(path)


def mark_workflow_applied(package_dir, workflow, family):
    """Simpan workflow aktif setelah setup/isi Excel selesai."""
    meta = _read_template_meta(package_dir)
    meta.update({
        "workflow": workflow,
        "workflow_applied": workflow,
        "workflow_target": workflow,
        "mode_family": str(family or "").upper(),
        "setup_completed_at": datetime.now().isoformat(timespec="seconds"),
    })
    _write_template_meta(package_dir, meta)
    return meta


def _template_output_name(name, package_dir):
    """Nama file hasil setup: hilangkan label domain agar tidak dobel."""
    folder = pathlib.Path(package_dir).name
    match = re.search(r"PL(?:JKK|PK)\s+-\s+(.+)$", folder, re.IGNORECASE)
    suffix = match.group(1).strip() if match else ""
    if not suffix or "Template" not in name:
        return name
    return re.sub(
        r"Template(?:\s+(?:Perencanaan|Pengawasan|Konstruksi))?",
        suffix,
        name,
        count=1,
        flags=re.IGNORECASE,
    )


def migrate_pl_workflow(package_dir, row, expected_family="JKK"):
    """Migrasikan template Word PLJKK setelah jenis kontrak berubah.

    Workbook existing sengaja dipertahankan agar data Excel tidak tertimpa.
    Hanya template Word domain yang diganti, dibackup, lalu direlink ke
    workbook yang sama. PLPK/JKK mismatch diblokir keras.
    """
    package_dir = pathlib.Path(package_dir)
    expected_family = str(expected_family or "JKK").upper()
    row_kind = str(row.get("jenis_pl") or expected_family).upper()
    if row_kind != expected_family:
        return {"ok": False, "status": "FAMILY_MISMATCH", "message": f"Data paket {row_kind} tidak cocok mode {expected_family}."}

    core = _core_workflow_config()
    target = core.detect_pl_workflow(row, row_kind)
    target_cfg = core.pl_workflow_config(target)
    if target_cfg["jenis_pl"] != expected_family:
        return {"ok": False, "status": "FAMILY_MISMATCH", "message": f"Target {target} bukan workflow {expected_family}."}

    meta = _read_template_meta(package_dir)
    applied = str(meta.get("workflow_applied") or meta.get("workflow") or "").upper()
    if not applied:
        return {"ok": False, "status": "UNKNOWN", "target": target, "message": "Workflow aktif tidak tercatat di metadata; migrasi otomatis diblokir."}
    if applied == target:
        return {"ok": True, "status": "UNCHANGED", "target": target, "message": f"Template sudah sesuai: {target}."}
    applied_cfg = core.pl_workflow_config(applied)
    if applied_cfg["jenis_pl"] != expected_family:
        return {"ok": False, "status": "FAMILY_MISMATCH", "message": f"Folder pernah dibuat sebagai {applied}; tidak disentuh otomatis."}

    workbook = _cari_xlsm_pl(str(package_dir))
    if not workbook or "BAPLJKK" not in pathlib.Path(workbook).name.upper():
        return {"ok": False, "status": "FAMILY_MISMATCH", "message": "Workbook folder bukan BAPLJKK; migrasi JKK diblokir."}

    source_dir = pathlib.Path(core.pl_workflow_template_dir(target))
    backup_dir = package_dir / ".workflow-backups" / datetime.now().strftime("%Y%m%d-%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    moved = []
    copied = []
    try:
        # Hanya file Word domain yang diganti. Workbook package tetap aman.
        for source_name, _sheet in target_cfg["word_map"]:
            source = source_dir / source_name
            if not source.is_file():
                raise FileNotFoundError(f"Donor tidak ditemukan: {source}")
            destination_name = _template_output_name(source_name, package_dir)
            destination = package_dir / destination_name
            prefix = re.match(r"^(\d+)\.\s+", destination_name)
            candidates = []
            if prefix:
                candidates = [
                    p for p in package_dir.iterdir()
                    if p.is_file()
                    and p.suffix.lower() == source.suffix.lower()
                    and re.match(rf"^{prefix.group(1)}\.\s+", p.name)
                    and "(merged)" not in p.name.lower()
                    and ".bak" not in p.name.lower()
                ]
            for old in candidates:
                target_backup = backup_dir / old.name
                shutil.move(str(old), str(target_backup))
                moved.append(old.name)
            shutil.copy2(source, destination)
            copied.append(destination.name)

        relink = pathlib.Path(core.BASE_DIR) / "relink_pl.py"
        result = subprocess.run(
            [str(core.PYTHON_EXE), str(relink), str(workbook)],
            capture_output=True, text=True, timeout=90, creationflags=0x08000000,
        )
        if result.returncode != 0:
            raise RuntimeError(f"Relink gagal: {(result.stderr or result.stdout).strip()[:500]}")

        meta.update({
            "workflow": target,
            "workflow_applied": target,
            "workflow_target": target,
            "workflow_previous": applied,
            "workflow_migrated_at": datetime.now().isoformat(timespec="seconds"),
            "workflow_backup": str(backup_dir),
            "workbook_preserved": True,
        })
        _write_template_meta(package_dir, meta)
        return {"ok": True, "status": "MIGRATED", "target": target, "backup": str(backup_dir), "copied": copied, "moved": moved, "message": f"Migrasi {applied} → {target} selesai."}
    except Exception as exc:
        # Rollback jika copy/relink gagal di tengah jalan.
        for name in copied:
            try:
                (package_dir / name).unlink(missing_ok=True)
            except Exception:
                pass
        for name in moved:
            try:
                backup_file = backup_dir / name
                if backup_file.exists() and not (package_dir / name).exists():
                    shutil.move(str(backup_file), str(package_dir / name))
            except Exception:
                pass
        return {"ok": False, "status": "ERROR", "target": target, "backup": str(backup_dir), "message": str(exc), "moved": moved, "copied": copied}
