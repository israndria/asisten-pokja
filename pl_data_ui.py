"""Loader/cache data PL untuk UI Streamlit.

Memisahkan I/O read-only dari renderer mode agar rerun widget tidak mengulang
query SPSE/Supabase dan supaya JKK/PK memiliki cache key yang eksplisit.
"""

from __future__ import annotations

import os
import time
from datetime import datetime

import streamlit as st

_LOCAL_DRAFT_CACHE_VERSION = "folder-identity-v3-family-gate"
_PL_UMUMKAN_STATUS_KEY = "pl_umumkan_status"
_PUBLISH_DONE_MARKERS = (
    "sudah diumumkan",
    "diumumkan",
    "pengumuman",
    "berjalan",
    "aktif",
    "published",
)
_PUBLISH_NEGATIVE_MARKERS = (
    "belum",
    "draft",
    "gagal",
    "ditolak",
    "batal",
    "ditarik",
    "tidak aktif",
    "nonaktif",
)
_PUBLISH_PRESTART_STAGE = "paket belum dilaksanakan"


def _publish_status_text_is_done(value) -> bool:
    """True jika teks status menunjukkan paket sudah melewati tahap draft."""
    text = str(value or "").strip().lower()
    if not text or any(marker in text for marker in _PUBLISH_NEGATIVE_MARKERS):
        return False
    return any(marker in text for marker in _PUBLISH_DONE_MARKERS)


def get_paket_umumkan_status() -> dict:
    """Ambil status pengumuman lokal tanpa memicu I/O."""
    status = st.session_state.get(_PL_UMUMKAN_STATUS_KEY, {})
    return status if isinstance(status, dict) else {}


def mark_paket_sudah_diumumkan(kode_paket: str, result: dict | None = None) -> None:
    """Simpan bukti POST pengumuman sukses untuk rerun Streamlit saat ini."""
    kode = str(kode_paket or "").strip()
    if not kode:
        return
    status = dict(get_paket_umumkan_status())
    entry = {"status": "sudah diumumkan"}
    if isinstance(result, dict):
        for key in ("status_code", "location"):
            if result.get(key) not in (None, ""):
                entry[key] = result[key]
    status[kode] = entry
    st.session_state[_PL_UMUMKAN_STATUS_KEY] = status


def mark_tahap_spse_sudah_diumumkan(tahap_map: dict) -> int:
    """Salin batch tahap aktif SPSE ke session sebagai status sudah diumumkan."""
    status = dict(get_paket_umumkan_status())
    jumlah = 0
    for kode_paket, tahap in (tahap_map or {}).items():
        kode = str(kode_paket or "").strip()
        tahap_text = str(tahap or "").strip()
        if not kode or not tahap_text:
            continue
        status[kode] = {
            "status": "sudah diumumkan",
            "tahap_spse": tahap_text,
        }
        jumlah += 1
    if jumlah:
        st.session_state[_PL_UMUMKAN_STATUS_KEY] = status
    return jumlah


def format_pl_announce_log(
    results: list[dict],
    *,
    family: str = "PL",
    started_at: datetime | None = None,
) -> list[str]:
    """Buat log announce yang terstruktur, persisten, dan mudah dicopy."""
    rows = list(results or [])
    started = started_at if isinstance(started_at, datetime) else datetime.now()
    ok_count = sum(bool(row.get("ok")) for row in rows)
    lines = [
        "LOG PENGUMUMAN PAKET PL",
        f"Mulai : {started.strftime('%d-%m-%Y %H:%M:%S')}",
        f"Family: {str(family or 'PL').upper()}",
        f"Total : {len(rows)} paket | Berhasil: {ok_count} | Gagal: {len(rows) - ok_count}",
        "",
    ]
    for index, row in enumerate(rows, 1):
        code = str(row.get("kode_paket") or "-").strip()
        package = str(row.get("paket") or row.get("nama") or code).strip()
        message = str(
            row.get("error") or row.get("pesan") or row.get("body") or "-"
        ).strip().replace("\r", " ").replace("\n", " ")
        status = row.get("status_code", row.get("status", "-"))
        status_text = str(status if status not in (None, "") else "-")
        stage = str(row.get("stage") or "").strip()
        if not stage:
            lower = message.casefold()
            stage = (
                f"GET /nontender/{code}/edit + CSRF"
                if "get edit" in lower or status_text in {"0", "404"}
                else f"POST /nontender/{code}/pengumumanpp"
            )
        outcome = "BERHASIL" if row.get("ok") else "GAGAL"
        lines.extend(
            [
                f"[{index}] {package}",
                f"     Kode  : {code}",
                f"     Tahap : {stage}",
                f"     HTTP  : {status_text}",
                f"     Hasil : {outcome}",
                f"     Detail: {message[:1000]}",
                "",
            ]
        )
    return lines


def overlay_live_tahap_spse(rows: list[dict]) -> list[dict]:
    """Timpa tahap lokal dengan tahap live SPSE yang sudah disinkronkan."""
    status = get_paket_umumkan_status()
    if not status:
        return rows or []

    result = []
    for row in rows or []:
        current = dict(row)
        marker = status.get(str(current.get("kode_paket") or "").strip())
        if isinstance(marker, dict) and marker.get("tahap_spse"):
            current["tahap_spse"] = marker["tahap_spse"]
        result.append(current)
    return result


def get_live_tahap_map(state_key: str) -> dict:
    """Ambil snapshot tahap live yang berhasil diverifikasi untuk ``state_key``."""
    tahap_map = st.session_state.get(f"{state_key}:tahap_map", {})
    return tahap_map if isinstance(tahap_map, dict) else {}


def filter_paket_draft_live(
    rows: list[dict],
    live_tahap_map: dict | None,
    *,
    live_status_ok: bool,
    session_status: dict | None = None,
) -> list[dict]:
    """Kembalikan kandidat Draft setelah diverifikasi terhadap status live SPSE.

    Endpoint ``dt/pengadaan-pp?status=1`` hanya mengembalikan paket yang sudah
    melewati Draft. Karena itu row lokal berstatus Draft dipakai sebagai
    kandidat, sedangkan setiap kode yang muncul pada map live (termasuk tahap
    ``Paket Belum Dilaksanakan``) menjadi veto. Jika verifikasi live gagal,
    jangan mengambil keputusan dari cache lokal: hasil harus kosong.
    """
    if live_status_ok is not True:
        return []

    from pl_engine import is_paket_draft

    active_codes = {
        str(kode or "").strip()
        for kode in (live_tahap_map or {})
        if str(kode or "").strip()
    }
    session_status = (
        session_status if isinstance(session_status, dict) else get_paket_umumkan_status()
    )
    result = []
    for row in rows or []:
        code = str(row.get("kode_paket") or "").strip()
        if not code or code in active_codes or not is_paket_draft(row):
            continue
        # Marker POST lokal tetap menjadi pengaman untuk rerun sebelum daftar
        # live SPSE menampilkan tahap paket yang baru diumumkan.
        if code in session_status and is_paket_sudah_diumumkan(
            {"kode_paket": code, "status": "draft", "tahap_spse": ""},
            session_status,
        ):
            continue
        result.append(row)
    return result


def is_paket_sudah_diumumkan(row: dict, session_status: dict | None = None) -> bool:
    """Deteksi paket yang sudah diumumkan dari session atau field SPSE."""
    row = row or {}
    kode = str(row.get("kode_paket") or "").strip()
    session_status = session_status if isinstance(session_status, dict) else get_paket_umumkan_status()
    if kode and kode in session_status:
        marker = session_status[kode]
        if marker is True:
            return True
        if isinstance(marker, dict):
            if marker.get("ok") is True:
                return True
            marker = marker.get("status") or marker.get("tahap_spse") or marker.get("pesan")
        if _publish_status_text_is_done(marker):
            return True

    tahap = str(row.get("tahap_spse") or "").strip().lower()
    if tahap == _PUBLISH_PRESTART_STAGE:
        # SPSE memakai label ini untuk paket yang sudah diumumkan/disetujui,
        # tetapi jadwal mulai belum tercapai.
        return True
    if tahap and not any(marker in tahap for marker in _PUBLISH_NEGATIVE_MARKERS):
        # Tahap berikutnya (mis. Upload Dokumen Penawaran) berarti Draft sudah
        # dilewati walau label tahap tidak memuat kata "Pengumuman".
        return True
    return _publish_status_text_is_done(row.get("status"))


def filter_paket_siap_dijadwalkan(
    rows: list[dict], session_status: dict | None = None
) -> list[dict]:
    """Ambil paket Draft yang belum tayang untuk dibuat jadwal.

    Status lokal Draft tetap diperlukan sebagai kandidat awal, tetapi tidak
    dipercaya sendirian: setiap tahap live SPSE atau bukti pengumuman dari
    session berarti paket sudah tayang dan harus dikeluarkan dari daftar ini.
    Dengan begitu Draft PLPK/JKK yang belum tayang tetap muncul, sementara
    Draft stale yang sudah tayang tidak bocor ke selector.
    """
    hasil = []
    for row in rows or []:
        if not row.get("kode_paket"):
            continue
        tahap = str(row.get("tahap_spse") or "").strip().casefold()
        if tahap:
            continue
        status = str(row.get("status") or "").strip().casefold()
        if status != "draft":
            continue
        if is_paket_sudah_diumumkan(row, session_status):
            continue
        hasil.append(row)
    return hasil


def filter_paket_kirim_undangan_dpp(
    rows: list[dict], session_status: dict | None = None,
    *, live_status_ok: bool | None = None,
) -> list[dict]:
    """Ambil hanya Draft yang belum tayang untuk Tab Kirim Undangan DPP.

    Status lokal Draft tidak cukup: tahap live SPSE/session menjadi veto.
    Fail-closed untuk tahap/status non-Draft agar paket yang sudah tayang tidak
    muncul lagi walau cache Supabase belum ikut berubah.
    """
    # Status lokal Draft tidak boleh menjadi fallback ketika verifikasi live
    # gagal. Jika endpoint SPSE timeout/error, lebih aman menampilkan nol
    # kandidat daripada membiarkan paket tayang masuk kembali.
    if live_status_ok is False:
        return []

    hasil = []
    for row in rows or []:
        if not row.get("kode_paket"):
            continue
        if is_paket_sudah_diumumkan(row, session_status):
            continue
        if str(row.get("status") or "").strip().casefold() != "draft":
            continue
        if str(row.get("tahap_spse") or "").strip():
            continue
        hasil.append(row)
    return hasil


def get_reviu_full_pdf_path(row: dict):
    """Resolve bukti lokal Isi Reviu Full secara ketat.

    Hanya nama canonical yang cocok dengan nomor folder dan family paket yang
    diterima; file PDF lain/duplikat tidak boleh menjadi bukti selesai.
    """
    from pathlib import Path
    import re

    folder = Path(str((row or {}).get("_folder_lokal") or ""))
    if not folder.is_dir():
        return None
    match = re.match(r"^\s*(\d+)\.", folder.name)
    if not match:
        return None
    family = str((row or {}).get("jenis_pl") or "").strip().upper()
    prefix = "PLPK" if family in {"PK", "PLPK"} else "PLJKK" if family in {"JKK", "PLJKK"} else ""
    if not prefix:
        return None
    candidate = folder / "6. BA Reviu Lengkap" / f"2. Isi Reviu Fix Full - {prefix}{match.group(1)}.pdf"
    try:
        if candidate.is_file() and candidate.stat().st_size > 0:
            with candidate.open("rb") as stream:
                if stream.read(5) == b"%PDF-":
                    return candidate
    except OSError:
        pass
    return None


def sync_live_paket_umumkan_status(state_key: str, ttl_seconds: float = 60.0) -> dict:
    """Sinkronkan tahap tayang live SPSE secara read-only dengan TTL singkat."""
    now = time.monotonic()
    last_sync = st.session_state.get(state_key)
    cached_result = st.session_state.get(f"{state_key}:result")
    live_map_key = f"{state_key}:tahap_map"
    if isinstance(last_sync, (int, float)) and now - last_sync < ttl_seconds:
        if isinstance(cached_result, dict) and isinstance(
            st.session_state.get(live_map_key), dict
        ):
            return {**cached_result, "cached": True, "count": 0}
        return {
            "ok": False,
            "cached": True,
            "count": 0,
            "error": "Status live belum pernah berhasil diverifikasi",
        }

    st.session_state[state_key] = now
    try:
        import spse_browser
        from config import SPSE_BASE_URL
        import pl_engine as _live_pl_engine

        cookie = spse_browser.get_spse_cookies()
        if not cookie:
            st.session_state.pop(live_map_key, None)
            return {"ok": False, "cached": False, "count": 0, "error": "Cookie SPSE kosong"}
        tahap_map = _live_pl_engine._fetch_tahap_spse(
            cookie, SPSE_BASE_URL, strict=True
        )
        st.session_state[live_map_key] = {
            str(kode).strip(): str(tahap or "").strip()
            for kode, tahap in (tahap_map or {}).items()
            if str(kode or "").strip()
        }
        count = mark_tahap_spse_sudah_diumumkan(tahap_map)
        result = {"ok": True, "cached": False, "count": count}
        st.session_state[f"{state_key}:result"] = result
        return result
    except Exception as exc:
        st.session_state.pop(live_map_key, None)
        result = {"ok": False, "cached": False, "count": 0, "error": str(exc)}
        st.session_state[f"{state_key}:result"] = result
        return result


def _filter_pl_family(rows: list[dict], engine_kind: str) -> list[dict]:
    """Batasi row ke family yang diminta; family tidak dikenal ditolak.

    Query Supabase tetap menjadi filter pertama di masing-masing engine, tetapi
    boundary ini wajib ada di loader UI juga. Dengan begitu row JKK yang
    terselip akibat cache/query lama tidak pernah masuk ke mode PK, dan row
    tanpa klasifikasi tidak diasumsikan sebagai salah satu family.
    """
    kind = str(engine_kind or "JKK").strip().upper()
    if kind in {"PK", "PLPK", "KONSTRUKSI", "PL - KONSTRUKSI"}:
        expected = "PK"
    elif kind in {"JKK", "PLJKK", "KONSULTANSI", "PL - KONSULTANSI"}:
        expected = "JKK"
    else:
        return []

    return [
        row for row in (rows or [])
        if str(row.get("jenis_pl") or "").strip().upper() == expected
    ]


@st.cache_data(ttl=300, show_spinner=False)
def fetch_status_semua_paket_cached(kode_tuple: tuple) -> dict:
    """Ambil status peserta PL secara batch; cache 5 menit."""
    try:
        import peserta_monitor_pl
        return peserta_monitor_pl.fetch_status_semua_paket(list(kode_tuple))
    except Exception:
        return {}


def load_status_peserta_on_demand(
    kode_tuple: tuple,
    state_key: str,
    button_key: str,
) -> dict:
    """Muat badge peserta hanya setelah diminta user.

    Tab 1 tidak boleh memblokir perpindahan mode dengan puluhan request SPSE.
    Hasil disimpan di session state agar rerun widget berikutnya tetap ringan;
    tombol sengaja mengosongkan cache supaya refresh benar-benar mengambil data
    terbaru.
    """
    kode = tuple(str(k) for k in kode_tuple if k)
    if not kode:
        return {}

    status = st.session_state.get(state_key)
    if not isinstance(status, dict):
        status = {}

    if st.button("🔄 Muat status peserta", key=button_key, help="Ambil jumlah peserta dari SPSE"):
        fetch_status_semua_paket_cached.clear()
        status = fetch_status_semua_paket_cached(kode)
        st.session_state[state_key] = status
    return status


@st.cache_data(ttl=120, show_spinner=False)
def fetch_status_pilih_penyedia_cached(
    provider_items: tuple[tuple[str, str, str], ...],
) -> dict:
    """Baca status provider terpilih dari SPSE untuk daftar paket.

    ``provider_items`` berisi ``(kode_paket, nama_penyedia, npwp)``. Cache
    hanya 2 menit agar tombol refresh tetap murah, tetapi status tidak stale
    terlalu lama setelah user memilih penyedia manual di SPSE.
    """
    try:
        import spse_browser
        from config import SPSE_BASE_URL

        cookie = spse_browser.get_spse_cookies()
        result = {}
        for kode, nama, npwp in provider_items or ():
            kode = str(kode or "").strip()
            if not kode:
                continue
            try:
                result[kode] = spse_browser.cek_status_pilih_penyedia_via_api(
                    kode,
                    SPSE_BASE_URL,
                    npwp=str(npwp or ""),
                    nama_penyedia=str(nama or ""),
                    cookie_str=cookie,
                )
            except Exception as exc:
                result[kode] = {
                    "ok": False,
                    "status": "gagal",
                    "pesan": str(exc),
                }
        return result
    except Exception as exc:
        return {
            str(kode): {"ok": False, "status": "gagal", "pesan": str(exc)}
            for kode, _nama, _npwp in provider_items or ()
            if str(kode or "").strip()
        }


def load_status_pilih_penyedia_on_demand(
    provider_items: tuple[tuple[str, str, str], ...],
    state_key: str,
    button_key: str,
    *,
    auto_sync: bool = True,
) -> dict:
    """Muat status pilihan provider sekali saat daftar paket pertama dirender.

    Status tetap read-only dan disimpan berdasarkan signature daftar paket.
    Tombol refresh memaksa pembacaan ulang untuk menangkap perubahan manual di
    SPSE tanpa menunggu TTL cache. ``auto_sync=False`` dipertahankan sebagai
    escape hatch untuk render yang memang tidak boleh melakukan request.
    """
    normalized = tuple(
        (
            str(kode or "").strip(),
            str(nama or "").strip(),
            str(npwp or "").strip(),
        )
        for kode, nama, npwp in provider_items or ()
        if str(kode or "").strip()
    )
    signature_key = f"{state_key}_signature"
    status = st.session_state.get(state_key)
    if st.session_state.get(signature_key) != normalized:
        status = {}

    refresh_clicked = st.button(
        "🔄 Refresh status pilihan penyedia di SPSE",
        key=button_key,
        help=(
            "Status otomatis dibaca sekali saat daftar paket pertama tampil. "
            "Klik untuk memaksa refresh live dari tabel Daftar Penyedia SPSE."
        ),
    )
    signature_matches = st.session_state.get(signature_key) == normalized
    should_sync = bool(normalized) and (
        refresh_clicked or (auto_sync and not signature_matches)
    )
    if should_sync:
        if refresh_clicked:
            fetch_status_pilih_penyedia_cached.clear()
        with st.spinner("Membaca status penyedia terpilih dari SPSE..."):
            status = fetch_status_pilih_penyedia_cached(normalized)
        st.session_state[state_key] = status
        st.session_state[signature_key] = normalized
    return status if isinstance(status, dict) else {}


def filter_local_pl_rows(rows: list[dict]) -> list[dict]:
    """Kembalikan hanya paket yang benar-benar siap di disk lokal.

    ``folder_dibuat`` di Supabase adalah status workflow, bukan bukti bahwa
    folder masih ada di komputer aktif. Tab operasi tidak boleh menampilkan
    row yang statusnya stale, foldernya hilang, atau workbook utama belum ada.
    Bukti lokal (folder + workbook) menjadi sumber gate; status Supabase boleh
    stale atau belum tersimpan tanpa membuat paket fisik yang valid menghilang.
    Tab 1 sengaja dapat memanggil loader dengan ``only_local=False`` agar paket
    baru tetap bisa dipilih untuk proses Create Folder.
    """
    from parse_kak_pl import _resolve_folder_pl
    from pl_ui_helpers import _cari_xlsm_pl

    result = []
    for row in rows or []:
        if not row.get("kode_paket"):
            continue
        try:
            folder, _ = _resolve_folder_pl(
                row.get("nomor_urut"),
                row.get("nama_paket") or "",
                row.get("jenis_pl") or "JKK",
                is_ulang=bool(row.get("is_ulang")),
                strict_name=True,
            )
            xlsm = _cari_xlsm_pl(folder) if folder and os.path.isdir(folder) else None
            if not xlsm or not os.path.isfile(xlsm):
                continue
            enriched = dict(row)
            enriched["_folder_lokal"] = folder
            enriched["_xlsm_lokal"] = xlsm
            result.append(enriched)
        except (OSError, TypeError, ValueError):
            continue
    return result


def select_rows_by_checkbox_state(
    rows: list[dict], state: dict, key_prefix: str
) -> list[dict]:
    """Pilih row berdasarkan checkbox tanpa mengubah urutan daftar sumber."""
    selected = []
    for row in rows:
        kode = str(row.get("kode_paket") or "").strip()
        if kode and bool(state.get(f"{key_prefix}{kode}", False)):
            selected.append(row)
    return selected


def get_manual_ba_date(jenis_key: str, tanggal_evaluasi, tanggal_pemilihan):
    """Ambil tanggal manual sesuai jenis BA yang sedang diproses."""
    key = str(jenis_key or "").strip().lower()
    if key == "evaluasi":
        return tanggal_evaluasi
    if key == "hasil":
        return tanggal_pemilihan
    return None


def _hydrate_provider_from_excel(rows: list[dict]) -> list[dict]:
    """Gunakan cell identitas Excel sebagai nilai authoritative lokal.

    Nilai Excel sengaja menimpa cache Supabase bila tersedia. Ini mencegah
    hasil parser PDF yang keliru (contoh: ``1 Unit``) tampil atau dikirim
    kembali ke SPSE pada Tab 4.
    """
    from pl_ui_helpers import _baca_identitas_penyedia_pl

    result = []
    for row in rows or []:
        current = dict(row)
        identity = _baca_identitas_penyedia_pl(current)
        for key in ("nama_penyedia", "npwp_penyedia"):
            if identity.get(key):
                current[key] = identity[key]
        result.append(current)
    return result


def _hydrate_dokpil_from_excel(rows: list[dict]) -> list[dict]:
    """Timpa metadata Dokpil dari workbook lokal tiap paket.

    Ini menutup cache Supabase lama yang pernah menyimpan nomor hasil parser
    PDF, termasuk nomor dengan tanda ``?``. Jika C20 kosong/invalid, nomor
    dikosongkan dan error disimpan untuk ditampilkan/menahan upload.
    """
    from pl_ui_helpers import _resolve_nomor_dokpil_excel_pl

    result = []
    for row in rows or []:
        current = dict(row)
        resolved = _resolve_nomor_dokpil_excel_pl(current)
        master = resolved.get("master_data") or {}
        if master:
            current["kode_unik"] = str(master.get("kode_unik") or "").strip()
            current["nomor_dokpil"] = resolved.get("nomor_dokpil", "")
            current["tgl_dokpil"] = master.get("tgl_dokpil") or ""
        current["_nomor_dokpil_excel_ok"] = bool(resolved.get("ok"))
        current["_nomor_dokpil_excel_error"] = resolved.get("error", "")
        result.append(current)
    return result


@st.cache_data(ttl=60, show_spinner=False)
def load_draft_pl_cached(
    engine_kind: str = "JKK",
    only_local: bool = True,
    cache_version: str = _LOCAL_DRAFT_CACHE_VERSION,
) -> list:
    """Load draft PL; cache terpisah dan gate disk untuk tab operasional.

    ``cache_version`` dinaikkan saat aturan identitas folder berubah agar hasil
    lama tidak menahan paket yang baru berhasil di-resolve.
    """
    _ = cache_version
    if str(engine_kind).upper() == "PK":
        import pl_engine_plpk as engine
    else:
        import pl_engine as engine
    rows = engine.load_draft_pl()
    # Defense-in-depth: jangan percaya query engine/cache sebagai satu-satunya
    # boundary family. Ini mencegah paket konsultan bocor ke mode konstruksi.
    rows = _filter_pl_family(rows, engine_kind)
    # PK engine tidak mendefinisikan helper display ini; gunakan helper shared
    # agar label/nomor folder tetap identik dengan workflow JKK.
    from pl_engine import _hydrate_nomor_urut_folder
    hydrate = _hydrate_nomor_urut_folder
    rows = hydrate(rows) if hydrate and any(not r.get("nomor_urut") for r in rows) else rows
    if only_local:
        rows = filter_local_pl_rows(rows)
    rows = _hydrate_dokpil_from_excel(rows)
    if only_local:
        rows = _hydrate_provider_from_excel(rows)
    return rows


def clear_draft_pl_cache() -> None:
    """Invalidasi daftar PL setelah serap/update data."""
    load_draft_pl_cached.clear()


@st.cache_data(ttl=300, show_spinner=False)
def fetch_peserta_pl_cached(kode_nontender: str) -> int:
    try:
        import peserta_monitor_pl
        return (peserta_monitor_pl.fetch_jumlah_peserta_pl(kode_nontender) or {}).get("jumlah", 0)
    except Exception:
        return -1


@st.cache_data(ttl=300, show_spinner=False)
def parse_jadwal_pl_cached(kode_paket: str) -> list:
    try:
        import gcal_pl_helper
        return gcal_pl_helper.parse_jadwal_pl_dari_spse(kode_paket) or []
    except Exception:
        return []


@st.cache_data(ttl=60, show_spinner=False)
def load_verifikasi_pl_rows_cached(engine_kind: str = "JKK") -> tuple[list[dict], str]:
    try:
        engine = __import__("pl_engine_plpk" if str(engine_kind).upper() == "PK" else "pl_engine")
        rows = engine._sb().table("draft_paket_pl").select(
            "kode_paket, id_nontender, nama_paket, kode_unik, nama_penyedia, "
            "npwp_penyedia, tgl_negosiasi, tgl_undangan_verifikasi, "
            "status_undangan_verifikasi, is_ulang, jenis_pl, tahap_spse, "
            "folder_dibuat, nomor_urut"
        ).order("kode_paket").execute().data or []
        rows = _filter_pl_family(rows, engine_kind)
        rows = filter_local_pl_rows(rows)
        return _hydrate_provider_from_excel(rows), ""
    except Exception as exc:
        return [], str(exc)
