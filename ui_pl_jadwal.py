"""Renderer UI ubah jadwal Pengadaan Langsung."""

from datetime import datetime, timedelta

import streamlit as st

import jadwal_engine_pl
import pl_engine
from pl_ui_helpers import _pl_label


# Naikkan saat bentuk/semantik hasil scan berubah. Session Streamlit dapat
# bertahan melewati hot-reload, sehingga hasil scan dari kode lama tidak boleh
# ditampilkan atau dipakai lagi.
_LATE_UPLOAD_SCAN_SCHEMA_VERSION = 2


def is_late_upload_scan_current(scan: dict | None) -> bool:
    """True jika hasil scan bulk masih kompatibel dengan renderer saat ini."""
    return (
        isinstance(scan, dict)
        and scan.get("schema_version") == _LATE_UPLOAD_SCAN_SCHEMA_VERSION
    )


def _validasi_perubahan_jadwal(current: list[dict], proposed: list[dict]) -> list[str]:
    """Validasi perubahan tanpa memblokir overlap lama yang tidak diperparah.

    Beberapa jadwal PL yang sudah tersimpan di SPSE memang memiliki tahap
    evaluasi dan klarifikasi yang berjalan tumpang tindih. Ubah jadwal existing
    harus tetap bisa mengubah satu field (misalnya selesai T4) tanpa dipaksa
    membetulkan seluruh histori jadwal sekaligus. Overlap baru atau overlap yang
    makin besar tetap ditolak sebelum POST.
    """
    errors = []
    for i, row in enumerate(proposed):
        if row["mulai"] >= row["selesai"]:
            errors.append(f"T{i + 1}: waktu mulai harus sebelum selesai")

    for i in range(min(len(current), len(proposed)) - 1):
        current_overlap = current[i]["selesai"] - current[i + 1]["mulai"]
        proposed_overlap = proposed[i]["selesai"] - proposed[i + 1]["mulai"]
        if proposed_overlap <= timedelta(0):
            continue
        # Jadwal lama valid tetapi usulan membuat overlap baru.
        if current_overlap <= timedelta(0):
            errors.append(f"T{i + 1}–T{i + 2}: overlap baru")
        # Jadwal lama sudah overlap; hanya izinkan jika tidak makin besar.
        elif proposed_overlap > current_overlap:
            errors.append(f"T{i + 1}–T{i + 2}: overlap makin besar")
    return errors


def render_custom_jadwal_pl(
    *,
    prefix: str,
    default_start: datetime | None = None,
    title: str = "Jadwal Custom",
) -> list[dict]:
    """Render input tanggal/jam bebas T1–T5 dan kembalikan nilai mentahnya.

    Nilai awal hanya seed agar form langsung terisi valid; setelah user
    mengubahnya, setiap tahap berdiri sendiri dan tidak saling menghitung.
    """
    if not isinstance(default_start, datetime):
        default_start = datetime.now().replace(second=0, microsecond=0)
    else:
        default_start = default_start.replace(second=0, microsecond=0)
    seed = jadwal_engine_pl.hitung_jadwal_pl(default_start)

    st.markdown(f"#### {title}")
    st.caption(
        "Tentukan tanggal dan jam mulai/selesai tiap tahap secara bebas. "
        "Nilai awal hanya contoh; perubahan satu tahap tidak mengubah tahap lain."
    )
    hasil = []
    for index, nama in enumerate(jadwal_engine_pl.NAMA_TAHAP_PL):
        row_seed = seed[index]
        st.markdown(f"**{nama}**")
        st.caption("Mulai")
        c1, c2 = st.columns([3, 2])
        with c1:
            mulai_tanggal = st.date_input(
                "Mulai — tanggal",
                value=row_seed["mulai"].date(),
                format="DD/MM/YYYY",
                key=f"{prefix}_mulai_tanggal_{index}",
            )
        with c2:
            mulai_jam = st.time_input(
                "Mulai — jam",
                value=row_seed["mulai"].time(),
                key=f"{prefix}_mulai_jam_{index}",
            )
        st.caption("Selesai")
        c3, c4 = st.columns([3, 2])
        with c3:
            selesai_tanggal = st.date_input(
                "Selesai — tanggal",
                value=row_seed["selesai"].date(),
                format="DD/MM/YYYY",
                key=f"{prefix}_selesai_tanggal_{index}",
            )
        with c4:
            selesai_jam = st.time_input(
                "Selesai — jam",
                value=row_seed["selesai"].time(),
                key=f"{prefix}_selesai_jam_{index}",
            )
        hasil.append({
            "nama": nama,
            "mulai": datetime.combine(mulai_tanggal, mulai_jam),
            "selesai": datetime.combine(selesai_tanggal, selesai_jam),
        })
    return hasil


def filter_paket_sudah_tayang(
    rows: list[dict], session_status: dict | None = None
) -> list[dict]:
    """Ambil semua paket yang sudah tayang dan belum terminal.

    Daftar ini sengaja independen dari daftar Draft pada Seksi 1. Paket yang
    sudah masuk ``Paket Belum Dilaksanakan`` tetap termasuk karena sudah
    diumumkan, sedangkan ``Paket Sudah Selesai``/ditarik tidak lagi dapat
    diubah. Pembacaan jadwal T1-T5 dilakukan setelah user memilih paket.
    """
    from pl_data_ui import is_paket_sudah_diumumkan

    terminal_markers = (
        "paket sudah selesai",
        "sudah selesai",
        "ditarik",
        "withdrawn",
        "retired",
    )
    hasil = []
    for row in rows or []:
        text = " ".join(
            str(row.get(field) or "").strip().casefold()
            for field in ("tahap_spse", "status")
        )
        if any(marker in text for marker in terminal_markers):
            continue
        if is_paket_sudah_diumumkan(row, session_status):
            hasil.append(row)
    return hasil


def _jadwal_datetime(value) -> datetime | None:
    """Normalisasi nilai tanggal jadwal dari parser live/test fixture."""
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo is not None else value
    if not isinstance(value, str) or not value.strip():
        return None
    raw = value.strip()
    for parser in (
        lambda text: datetime.fromisoformat(text.replace("Z", "+00:00")),
        lambda text: datetime.strptime(text, "%d-%m-%Y %H:%M"),
    ):
        try:
            parsed = parser(raw)
            return parsed.replace(tzinfo=None) if parsed.tzinfo is not None else parsed
        except (TypeError, ValueError):
            continue
    return None


def _jumlah_peserta(value) -> int | None:
    """Ambil jumlah peserta non-negatif; ``None`` berarti data invalid."""
    if isinstance(value, bool):
        return None
    try:
        jumlah = int(value)
    except (TypeError, ValueError):
        return None
    return jumlah if jumlah >= 0 else None


def filter_paket_upload_terlambat(
    rows: list[dict],
    participant_status: dict,
    schedules: dict,
    *,
    now: datetime | None = None,
) -> list[dict]:
    """Pilih paket tayang dengan peserta valid 0 dan deadline T1 terlewati.

    ``rows`` harus sudah berasal dari ``filter_paket_sudah_tayang``. Status
    peserta/jadwal yang hilang atau error ditolak (fail-closed), karena angka
    nol hasil timeout tidak boleh dianggap sebagai paket tanpa peserta.
    Jadwal harus lengkap T1-T5 agar hasil aman langsung dipakai form perubahan.
    """
    anchor = now or datetime.now()
    if anchor.tzinfo is not None:
        anchor = anchor.replace(tzinfo=None)
    result = []
    for row in rows or []:
        code = str(row.get("kode_paket") or "").strip()
        status = (participant_status or {}).get(code)
        if not code or not isinstance(status, dict) or status.get("error"):
            continue
        jumlah = _jumlah_peserta(status.get("jumlah"))
        if jumlah is None:
            continue
        if jumlah != 0:
            continue
        jadwal = (schedules or {}).get(code)
        if not isinstance(jadwal, list) or len(jadwal) != 5:
            continue
        deadline = _jadwal_datetime(jadwal[0].get("selesai"))
        if deadline is None or deadline >= anchor:
            continue
        enriched = dict(row)
        enriched["_jumlah_peserta"] = jumlah
        enriched["_upload_deadline"] = deadline
        enriched["_jadwal_live"] = jadwal
        result.append(enriched)
    return result


def filter_paket_penandatanganan_kontrak(
    rows: list[dict],
    *,
    schedule_loader=None,
    now: datetime | None = None,
    window_hours: float = 6,
) -> list[dict]:
    """Ambil paket kontrak yang T5-nya berada dalam jendela tindak lanjut.

    Tanpa ``schedule_loader`` fungsi tetap menjadi filter tahap/status untuk
    kompatibilitas caller lama. Jika loader diberikan, hanya T5 mulai dalam
    rentang ``now - window`` sampai ``now + window`` yang dikembalikan. Jadwal
    yang gagal dibaca tidak ditebak dan tidak boleh masuk selector.
    """
    marker = "penandatanganan kontrak"
    anchor = now or datetime.now()
    if anchor.tzinfo is not None:
        anchor = anchor.replace(tzinfo=None)
    window = timedelta(hours=max(0, float(window_hours)))
    hasil = []
    for row in rows or []:
        if not any(
            marker in str(row.get(field) or "").strip().casefold()
            for field in ("tahap_spse", "status")
        ):
            continue
        if schedule_loader is None:
            hasil.append(row)
            continue
        try:
            jadwal = schedule_loader(str(row.get("kode_paket") or "").strip())
            t5 = jadwal[4].get("mulai") if len(jadwal or []) > 4 else None
            if isinstance(t5, str):
                t5 = datetime.fromisoformat(t5.replace("Z", "+00:00"))
            if isinstance(t5, datetime) and t5.tzinfo is not None:
                t5 = t5.replace(tzinfo=None)
        except Exception:
            continue
        if isinstance(t5, datetime) and anchor - window <= t5 <= anchor + window:
            hasil.append(row)
    return hasil


def _render_ubah_jadwal_pl(rows: list[dict], engine, prefix: str):
    """Bulk edit jadwal semua paket tayang dengan lima tahap lengkap."""
    st.markdown("### 3. Perubahan Jadwal")
    st.caption(
        "Daftar independen dari Seksi 1: semua paket yang sudah tayang. "
        "Trace dan ubah T1–T5; tahap yang tidak dipilih tetap memakai jadwal live masing-masing."
    )
    if not rows:
        st.info("Belum ada paket tayang yang dapat diperiksa.")
        return

    by_code = {str(p.get("kode_paket")): p for p in rows}
    scan_key = f"{prefix}_late_upload_scan"
    scan_button_key = f"{prefix}_late_upload_scan_button"
    with st.expander(
        "⚠️ Bulk Perpanjang Upload Penawaran — peserta 0 & deadline lewat",
        expanded=False,
    ):
        st.caption(
            "Scan live SPSE hanya memasukkan paket tayang dengan jumlah peserta "
            "valid 0 dan batas akhir T1 sudah lewat. Paket dengan timeout/error "
            "tidak dimasukkan. Hasil dapat dimuat ke form perubahan di bawah."
        )
        if st.button(
            "🔎 Scan peserta + deadline upload",
            key=scan_button_key,
            use_container_width=True,
        ):
            from pl_data_ui import fetch_status_semua_paket_cached

            codes_to_scan = tuple(by_code)
            with st.spinner(
                f"Membaca status peserta dan jadwal {len(codes_to_scan)} paket..."
            ):
                fetch_status_semua_paket_cached.clear()
                participant_status = fetch_status_semua_paket_cached(codes_to_scan)
                schedules = {}
                scan_errors = {}
                monitor_rows = []
                loaded = {}
                scan_now = datetime.now()
                for code in codes_to_scan:
                    package = by_code[code]
                    status = participant_status.get(code)
                    if not isinstance(status, dict):
                        reason = "Status peserta tidak dikembalikan."
                        scan_errors[code] = reason
                        monitor_rows.append({
                            "Paket": _pl_label(package),
                            "Peserta": "?",
                            "Batas akhir Upload": "-",
                            "Status": f"Tidak terverifikasi: {reason}",
                        })
                        continue
                    if status.get("error"):
                        reason = str(status["error"])
                        scan_errors[code] = reason
                        monitor_rows.append({
                            "Paket": _pl_label(package),
                            "Peserta": "?",
                            "Batas akhir Upload": "-",
                            "Status": f"Tidak terverifikasi: {reason}",
                        })
                        continue
                    jumlah = _jumlah_peserta(status.get("jumlah"))
                    if jumlah is None:
                        reason = "Jumlah peserta tidak valid."
                        scan_errors[code] = reason
                        monitor_rows.append({
                            "Paket": _pl_label(package),
                            "Peserta": "?",
                            "Batas akhir Upload": "-",
                            "Status": f"Tidak terverifikasi: {reason}",
                        })
                        continue
                    if jumlah != 0:
                        monitor_rows.append({
                            "Paket": _pl_label(package),
                            "Peserta": jumlah,
                            "Batas akhir Upload": "-",
                            "Status": "Sudah ada penawaran",
                        })
                        continue
                    try:
                        scraped = engine.scrap_hidden_fields_pl(code)
                        jadwal = engine.parse_jadwal_aktual_pl(scraped)
                        if len(jadwal) != 5:
                            raise ValueError(
                                f"SPSE mengembalikan {len(jadwal)}/5 tahap."
                            )
                        schedules[code] = jadwal
                        loaded[code] = {"scraped": scraped, "jadwal": jadwal}
                        deadline = _jadwal_datetime(jadwal[0].get("selesai"))
                        if deadline is None:
                            raise ValueError("deadline T1 tidak terbaca")
                        monitor_rows.append({
                            "Paket": _pl_label(package),
                            "Peserta": jumlah,
                            "Batas akhir Upload": deadline.strftime("%d-%m-%Y %H:%M"),
                            "Status": (
                                "Siap diperpanjang"
                                if deadline < scan_now
                                else "Deadline belum lewat"
                            ),
                        })
                    except Exception as exc:
                        reason = f"Jadwal live gagal dibaca: {exc}"
                        scan_errors[code] = reason
                        monitor_rows.append({
                            "Paket": _pl_label(package),
                            "Peserta": jumlah,
                            "Batas akhir Upload": "-",
                            "Status": f"Tidak terverifikasi: {reason}",
                        })
                eligible = filter_paket_upload_terlambat(
                    rows,
                    participant_status,
                    schedules,
                    now=scan_now,
                )
                st.session_state[scan_key] = {
                    "schema_version": _LATE_UPLOAD_SCAN_SCHEMA_VERSION,
                    "eligible": eligible,
                    "errors": scan_errors,
                    "monitor": monitor_rows,
                    "scanned_at": datetime.now(),
                }
                st.session_state[f"{prefix}_loaded"] = loaded
            st.rerun()

        scan = st.session_state.get(scan_key)
        if scan is not None and not is_late_upload_scan_current(scan):
            # Hasil lama bisa berisi exception dari implementasi sebelum retry.
            # Hapus diam-diam agar UI tidak menampilkan 404 stale sebagai hasil
            # scan live terbaru.
            st.session_state.pop(scan_key, None)
            scan = None
        if isinstance(scan, dict):
            eligible = scan.get("eligible") or []
            errors = scan.get("errors") or {}
            monitor = scan.get("monitor") or []
            if monitor:
                import pandas as _pd_monitor

                st.markdown("#### Monitoring status peserta")
                st.dataframe(
                    _pd_monitor.DataFrame(monitor),
                    use_container_width=True,
                    hide_index=True,
                )
            if eligible:
                st.success(
                    f"{len(eligible)} paket memenuhi kriteria peserta 0 + deadline terlewati."
                )
                import pandas as _pd_late

                st.dataframe(
                    _pd_late.DataFrame([
                        {
                            "Paket": _pl_label(item),
                            "Peserta": item.get("_jumlah_peserta", 0),
                            "Batas akhir Upload": item["_upload_deadline"].strftime(
                                "%d-%m-%Y %H:%M"
                            ),
                        }
                        for item in eligible
                    ]),
                    use_container_width=True,
                    hide_index=True,
                )
                eligible_codes = [str(item["kode_paket"]) for item in eligible]
                selected_late = st.multiselect(
                    "Paket hasil scan yang dimasukkan ke form perubahan",
                    eligible_codes,
                    format_func=lambda code: _pl_label(by_code.get(code, {"kode_paket": code})),
                    key=f"{prefix}_late_upload_codes",
                )
                if st.button(
                    f"➡️ Gunakan paket terpilih ({len(selected_late)}) di form perubahan",
                    key=f"{prefix}_late_upload_apply",
                    disabled=not selected_late,
                    use_container_width=True,
                ):
                    st.session_state[f"{prefix}_codes"] = list(selected_late)
                    st.rerun()
            else:
                st.info("Tidak ada paket yang memenuhi kriteria saat scan terakhir.")
            if errors:
                st.warning(
                    f"⚠️ {len(errors)} paket ditahan karena gagal diverifikasi; "
                    "detail ditampilkan di bawah."
                )
                st.code(
                    "\n".join(
                        f"{_pl_label(by_code.get(code, {'kode_paket': code}))}: {message}"
                        for code, message in errors.items()
                    ),
                    language=None,
                )

    codes = st.multiselect(
        "Paket yang diubah (semua paket tayang)",
        list(by_code),
        # Kode paket tidak diperlukan untuk identifikasi visual; nomor folder
        # sudah menjadi prefix pada _pl_label(). Jangan potong nama paket.
        format_func=lambda k: _pl_label(by_code[k]),
        key=f"{prefix}_codes",
    )
    if not codes:
        st.info("Pilih satu atau beberapa paket.")
        return

    if st.button(f"🔄 Ambil Jadwal Live ({len(codes)} paket)", key=f"{prefix}_fetch", use_container_width=True):
        _loaded = {}
        with st.spinner("Mengambil jadwal live..."):
            for code in codes:
                try:
                    scraped = engine.scrap_hidden_fields_pl(code)
                    jadwal = engine.parse_jadwal_aktual_pl(scraped)
                    if len(jadwal) != 5:
                        raise ValueError(
                            f"SPSE mengembalikan {len(jadwal)}/5 tahap; "
                            "perubahan ditahan sampai T1–T5 lengkap."
                        )
                    _loaded[code] = {"scraped": scraped, "jadwal": jadwal}
                except Exception as e:
                    _loaded[code] = {"error": str(e)}
        st.session_state[f"{prefix}_loaded"] = _loaded
        st.rerun()

    loaded = st.session_state.get(f"{prefix}_loaded", {})
    if any(c not in loaded for c in codes):
        st.info("Klik **Ambil Jadwal Live** setelah memilih paket.")
        return
    load_errors = {
        code: str(loaded[code].get("error") or "gagal membaca jadwal")
        for code in codes
        if loaded[code].get("error")
    }
    if load_errors:
        for code, error in load_errors.items():
            st.error(f"{code}: {error}")
        return

    tahap = ["T1 Upload", "T2 Pembukaan", "T3 Evaluasi", "T4 Klarifikasi+Nego", "T5 Kontrak"]
    selected_tahap = st.multiselect("Tahap yang diubah", tahap, key=f"{prefix}_stages")
    idx_tahap = {x: i for i, x in enumerate(tahap)}
    if not selected_tahap:
        st.info("Pilih minimal satu tahap yang diubah.")
        return

    mode = st.radio(
        "Metode perubahan",
        ["Set waktu absolut sama", "Geser relatif"],
        index=0,
        horizontal=True,
        key=f"{prefix}_mode_v2",
    )
    perubahan = {}
    if mode == "Geser relatif":
        c1, c2 = st.columns(2)
        with c1:
            hari = st.number_input("Geser hari", min_value=-365, max_value=365, value=0, step=1, key=f"{prefix}_days")
        with c2:
            jam = st.number_input("Geser jam", min_value=-23, max_value=23, value=0, step=1, key=f"{prefix}_hours")
        delta = timedelta(days=hari, hours=jam)
    else:
        for label in selected_tahap:
            i = idx_tahap[label]
            c1, c2, c3, c4 = st.columns([2, 1, 2, 1])
            sample = next(iter(loaded.values()))["jadwal"][i]
            with c1:
                d1 = st.date_input(f"{label} mulai", value=sample["mulai"].date(), format="DD/MM/YYYY", key=f"{prefix}_abs_sd_{i}")
            with c2:
                t1 = st.time_input("Jam", value=sample["mulai"].time(), key=f"{prefix}_abs_td_{i}")
            with c3:
                d2 = st.date_input(f"{label} selesai", value=sample["selesai"].date(), format="DD/MM/YYYY", key=f"{prefix}_abs_ss_{i}")
            with c4:
                t2 = st.time_input("Jam", value=sample["selesai"].time(), key=f"{prefix}_abs_ts_{i}")
            perubahan[i] = (datetime.combine(d1, t1), datetime.combine(d2, t2))

    semua_usulan = {}
    preview = []
    for code in codes:
        usulan = []
        for i, current in enumerate(loaded[code]["jadwal"]):
            mulai, selesai = current["mulai"], current["selesai"]
            if tahap[i] in selected_tahap:
                if mode == "Geser relatif":
                    mulai, selesai = mulai + delta, selesai + delta
                else:
                    mulai, selesai = perubahan[i]
            usulan.append({"nama": i + 1, "mulai": mulai, "selesai": selesai})
            preview.append({"Paket": _pl_label(by_code[code]), "Tahap": tahap[i], "Mulai": mulai.strftime("%d-%m-%Y %H:%M"), "Selesai": selesai.strftime("%d-%m-%Y %H:%M")})
        semua_usulan[code] = usulan

    import pandas as _pd_edit
    st.dataframe(_pd_edit.DataFrame(preview), use_container_width=True, hide_index=True)
    for code in codes:
        existing_schedule = loaded[code]["jadwal"]
        if any(
            existing_schedule[i]["selesai"] > existing_schedule[i + 1]["mulai"]
            for i in range(len(existing_schedule) - 1)
        ):
            st.warning(
                f"{code}: terdapat overlap jadwal lama di SPSE. "
                "Overlap ini dipertahankan selama perubahan tidak memperbesarnya."
            )
    alasan = st.text_area("Alasan Perubahan (minimal 30 karakter)", key=f"{prefix}_alasan")
    konfirmasi = st.checkbox("Saya sudah memeriksa preview dan menyetujui perubahan semua paket.", key=f"{prefix}_confirm")

    if st.button(f"🚀 Simpan Perubahan ({len(codes)} paket)", type="primary", key=f"{prefix}_submit", use_container_width=True):
        if not konfirmasi:
            st.error("Centang konfirmasi terlebih dahulu.")
            return
        if len(alasan.strip()) < 30:
            st.error("Alasan perubahan minimal 30 karakter.")
            return
        hasil = []
        for code in codes:
            usulan = semua_usulan[code]
            validasi = _validasi_perubahan_jadwal(
                loaded[code]["jadwal"], usulan
            )
            if validasi:
                hasil.append((
                    code,
                    False,
                    "Urutan waktu antar tahap tidak valid: " + "; ".join(validasi),
                ))
                continue
            try:
                result = engine.submit_perubahan_jadwal_pl(code, usulan, alasan)
                sub = result["submit_result"]
                if sub["ok"]:
                    try:
                        pl_engine.simpan_paket_pl({
                            "kode_paket": code,
                            "tgl_batas_penawaran": usulan[0]["selesai"].strftime("%Y-%m-%d"),
                            "tgl_buka_penawaran": usulan[1]["mulai"].strftime("%Y-%m-%d"),
                            "tgl_evaluasi": usulan[2]["selesai"].strftime("%Y-%m-%d"),
                            "tgl_negosiasi": usulan[3]["mulai"].strftime("%Y-%m-%d"),
                            "tgl_penetapan": usulan[4]["mulai"].strftime("%Y-%m-%d"),
                        })
                    except Exception:
                        pass
                    try:
                        import gcal_pl_helper as _gcal_edit
                        _gcal_edit.push_jadwal_pl_ke_gcal(code, by_code[code].get("nama_paket", ""), usulan)
                    except Exception:
                        pass
                    hasil.append((code, True, f"HTTP {sub['status']}"))
                else:
                    hasil.append((code, False, f"HTTP {sub['status']}: {sub['body'][:180]}"))
            except Exception as e:
                hasil.append((code, False, str(e)[:180]))
        for code, ok, msg in hasil:
            st.success(f"✅ {code} — {msg}") if ok else st.error(f"❌ {code} — {msg}")
