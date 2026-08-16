"""
Conflict detection engine — personil lintas paket.

Flow:
1. sync_from_supabase(kode_tender)  — ambil peserta_identitas, upsert ke paket_personil
2. sync_from_pdf(kode_tender, peserta_id, personel_list)  — dari kualifikasi_parser
3. get_konflik_personil()  — query: nama muncul di >1 kode_tender dari draft_paket
"""

import re
from datetime import date, timedelta
from config import sb as _sb

# ------------------------------------------------------------------
# Normalisasi nama personil
# ------------------------------------------------------------------

_RE_GELAR = re.compile(
    r"\b(Ir|Dr|H|Hj|S\.T|S\.E|S\.H|S\.Kom|A\.Md|M\.T|M\.Si|M\.M|Ph\.D|ST|AMd|SE|SH|MT)\.?\b",
    re.IGNORECASE,
)
_RE_NONALPHA = re.compile(r"[^a-z\s]")
def _normalize_nama(raw: str) -> str:
    """Lowercase + strip gelar Indonesia + hapus tanda baca + normalisasi spasi."""
    if not raw:
        return ""
    s = raw.lower()
    s = _RE_GELAR.sub("", s)
    s = _RE_NONALPHA.sub("", s)
    # Hapus spasi berlebih
    s = " ".join(s.split())
    return s


# ------------------------------------------------------------------
# Jadwal pelaksanaan paket
# ------------------------------------------------------------------

def _parse_hari_jangka(jangka_waktu: str) -> int | None:
    """Ambil angka pertama dari string jangka_waktu, asumsikan hari."""
    if not jangka_waktu:
        return None
    m = re.search(r"(\d+)", jangka_waktu)
    return int(m.group(1)) if m else None


def _get_jadwal_paket(kode_tender: str) -> tuple:
    """
    Return (tgl_mulai, tgl_selesai) sebagai date, atau (None, None).
    Cek draft_paket_pl dulu (kode_paket = kode_tender), lalu draft_paket.
    """
    # Coba PL dulu
    rows_pl = _sb().table("draft_paket_pl")\
        .select("tgl_penetapan,jangka_waktu")\
        .eq("kode_paket", kode_tender)\
        .limit(1).execute().data or []
    if rows_pl:
        r = rows_pl[0]
        tgl_str = r.get("tgl_penetapan")
        hari = _parse_hari_jangka(r.get("jangka_waktu", ""))
        if tgl_str and hari:
            try:
                tgl_mulai = date.fromisoformat(tgl_str)
                tgl_selesai = tgl_mulai + timedelta(days=hari)
                return (tgl_mulai, tgl_selesai)
            except ValueError:
                pass
        return (None, None)

    # Tender reguler — tidak ada kolom pelaksanaan, return None
    return (None, None)


def _parse_nama(raw: str) -> str:
    """Ambil nama saja dari string 'Nama (Jabatan)' atau 'Nama'."""
    if not raw:
        return ""
    m = re.match(r"^(.+?)\s*\(", raw.strip())
    return m.group(1).strip() if m else raw.strip()


def _parse_posisi(raw: str) -> str:
    """Ambil posisi/jabatan dari string 'Nama (Jabatan)'."""
    if not raw:
        return ""
    m = re.search(r"\((.+?)\)", raw.strip())
    return m.group(1).strip() if m else ""


def _upsert_personil_batch(rows: list[dict]) -> None:
    if not rows:
        return
    _sb().table("paket_personil").upsert(rows, on_conflict="kode_tender,peserta_id,nama_personil").execute()


def sync_from_supabase(kode_tender: str, log=print) -> dict:
    """
    Ambil semua peserta_identitas untuk kode_tender,
    upsert personil ke paket_personil.
    Sumber = 'supabase'.
    """
    rows_p = _sb().table("peserta_identitas")\
        .select("peserta_id,nama_perusahaan,personel_1,personel_2")\
        .eq("kode_tender", kode_tender).execute().data or []

    upsert_p = []
    for row in rows_p:
        pid   = row["peserta_id"]
        nama_penyedia = row.get("nama_perusahaan", "")
        for key in ("personel_1", "personel_2"):
            raw = row.get(key, "")
            if not raw:
                continue
            upsert_p.append({
                "kode_tender":  kode_tender,
                "peserta_id":   pid,
                "nama_penyedia": nama_penyedia,
                "nama_personil": _parse_nama(raw),
                "posisi":        key.replace("_", " ").title(),
                "sumber":        "supabase",
            })
    _upsert_personil_batch(upsert_p)
    log(f"sync_from_supabase {kode_tender}: {len(upsert_p)} personil")
    return {"personil": len(upsert_p)}


def sync_from_pdf(
    kode_tender: str,
    peserta_id: str,
    nama_penyedia: str,
    personel_list: list[str],
    log=print,
) -> dict:
    """
    Ganti data personil peserta dari hasil kualifikasi_parser (PDF).
    Sumber = 'pdf'. Penggantian mencegah personil stale tetap dianggap aktif.
    """
    if not str(peserta_id or "").strip():
        log(f"sync_from_pdf {kode_tender}: peserta_id kosong, skip personil")
        return {"personil": 0}
    if not personel_list:
        log(f"sync_from_pdf {kode_tender} {peserta_id}: personil kosong, data lama dipertahankan")
        return {"personil": 0}

    upsert_p = []
    seen = set()
    for i, raw in enumerate(personel_list):
        nama = _parse_nama(raw)
        norm = _normalize_nama(nama)
        if not norm or norm in seen:
            continue
        seen.add(norm)
        upsert_p.append({
            "kode_tender":  kode_tender,
            "peserta_id":   peserta_id,
            "nama_penyedia": nama_penyedia,
            "nama_personil": nama,
            "posisi":        _parse_posisi(raw) or f"Personel {i+1}",
            "sumber":        "pdf",
        })

    if not upsert_p:
        log(f"sync_from_pdf {kode_tender} {peserta_id}: personil tidak valid, data lama dipertahankan")
        return {"personil": 0}

    _sb().table("paket_personil")\
        .delete()\
        .eq("kode_tender", kode_tender)\
        .eq("peserta_id", peserta_id)\
        .execute()
    _upsert_personil_batch(upsert_p)
    log(f"sync_from_pdf {kode_tender} {peserta_id}: {len(upsert_p)} personil")
    return {"personil": len(upsert_p)}


def _resolve_folder_paket(kode_pokja: str) -> str | None:
    """Cari folder paket di TENDER_ROOT yang mengandung 'Pokja {kode_pokja zero-padded}'."""
    from config import TENDER_ROOT
    if not kode_pokja:
        return None
    import os
    _pokja_digits = re.sub(r"\D", "", str(kode_pokja or ""))
    _pokja_base = _pokja_digits.lstrip("0") or "0"
    label_re = re.compile(
        rf"Pokja\s*[-]?\s*0*{re.escape(_pokja_base)}(?!\d)",
        re.IGNORECASE,
    )
    try:
        for d in os.listdir(TENDER_ROOT):
            full = os.path.join(TENDER_ROOT, d)
            if os.path.isdir(full) and label_re.search(d):
                return full
    except Exception:
        pass
    return None


def sync_from_doktek_folder(kode_tender: str, log=print) -> dict:
    """
    Fallback: peserta yang personel_1 masih kosong di peserta_identitas
    → cari DoktekFull_*.pdf di folder paket lokal → parse personil
    → ganti data paket_personil via sync_from_pdf().
    """
    import os
    import glob

    # Ambil peserta yang personil atau alat belum lengkap
    rows = _sb().table("peserta_identitas")\
        .select("peserta_id,nama_perusahaan")\
        .eq("kode_tender", kode_tender)\
        .execute().data or []

    synced_peserta = {
        r.get("peserta_id")
        for r in (_sb().table("paket_personil")
                  .select("peserta_id")
                  .eq("kode_tender", kode_tender)
                  .execute().data or [])
        if r.get("peserta_id")
    }
    kosong = [
        r for r in rows
        if r.get("peserta_id") and r["peserta_id"] not in synced_peserta
    ]
    if not kosong:
        log(f"sync_from_doktek_folder {kode_tender}: personil sudah lengkap, skip")
        return {"personil": 0}

    # Ambil kode_pokja dari draft_paket (satu paket, satu kode_pokja)
    dp_rows = _sb().table("draft_paket")\
        .select("kode_pokja")\
        .eq("kode_tender", kode_tender)\
        .limit(1).execute().data or []
    kode_pokja = (dp_rows[0].get("kode_pokja") or "") if dp_rows else ""

    folder_paket = _resolve_folder_paket(kode_pokja)
    if not folder_paket:
        log(f"sync_from_doktek_folder {kode_tender}: folder paket Pokja {kode_pokja} tidak ditemukan")
        return {"personil": 0}

    total_p = 0
    for row in kosong:
        pid = row["peserta_id"]
        nama_penyedia = row.get("nama_perusahaan", "")

        # Cari DoktekFull_*.pdf: coba subfolder "1. Dokumen Penawaran\*nama*" dulu, lalu glob recursive
        pdf_path = None
        # Subfolder dokumen penawaran — coba match nama perusahaan (substring case-insensitive)
        dok_dir = os.path.join(folder_paket, "1. Dokumen Penawaran")
        if os.path.isdir(dok_dir):
            nama_lower = nama_penyedia.lower()
            for sub in os.listdir(dok_dir):
                sub_full = os.path.join(dok_dir, sub)
                if os.path.isdir(sub_full) and nama_lower[:6] in sub.lower():
                    # Cari DoktekFull_*.pdf di subfolder ini
                    hits = glob.glob(os.path.join(sub_full, "*DoktekFull_*.pdf"))
                    if hits:
                        pdf_path = hits[0]
                        break

        # Fallback: glob recursive seluruh folder paket
        if not pdf_path:
            hits = glob.glob(os.path.join(folder_paket, "**", "*DoktekFull_*.pdf"), recursive=True)
            # Jika banyak, coba match nama perusahaan via path
            if len(hits) > 1:
                nama_lower = nama_penyedia.lower()
                matched = [h for h in hits if nama_lower[:6] in h.lower()]
                hits = matched if matched else hits
            if hits:
                pdf_path = hits[0]

        if not pdf_path:
            log(f"  [{nama_penyedia}] DoktekFull_*.pdf tidak ditemukan, skip")
            continue

        log(f"  [{nama_penyedia}] parse dari {os.path.basename(pdf_path)}")
        try:
            # Lazy import hindari circular
            from dokumen_teknis_engine import parse_personel
            personel_list  = parse_personel(pdf_path)
        except Exception as e:
            log(f"  [{nama_penyedia}] parse error: {e}")
            continue

        res = sync_from_pdf(kode_tender, pid, nama_penyedia, personel_list, log=log)
        total_p += res["personil"]

    log(f"sync_from_doktek_folder {kode_tender}: {total_p} personil (dari {len(kosong)} peserta kosong)")
    return {"personil": total_p}


def _get_aktif_kode_tender() -> list[str]:
    """Semua kode_tender di draft_paket = paket aktif."""
    rows = _sb().table("draft_paket").select("kode_tender").execute().data or []
    return [
        r["kode_tender"] for r in rows
        if r.get("kode_tender") and str(r["kode_tender"]) != "10096884000"
    ]


def sync_new_paket(log=print) -> dict:
    """
    Hanya sync paket yang belum ada di paket_personil sama sekali.
    Jauh lebih cepat dari loop semua paket aktif.
    """
    aktif = set(_get_aktif_kode_tender())
    if not aktif:
        return {"synced": 0}

    # Paket dianggap tersync jika data personilnya sudah tersedia.
    tersync_p = set(
        r["kode_tender"]
        for r in (_sb().table("paket_personil").select("kode_tender").execute().data or [])
    )

    belum = aktif - tersync_p
    if not belum:
        log("sync_new_paket: semua paket sudah tersync, skip")
        return {"synced": 0}

    log(f"sync_new_paket: {len(belum)} paket belum tersync → {sorted(belum)}")
    total = 0
    for kt in belum:
        r = sync_from_doktek_folder(kt, log=log)
        total += r.get("personil", 0)
    return {"synced": len(belum), "personil": total}


def get_sync_coverage() -> dict:
    """Ringkasan coverage data konflik tanpa membaca PDF."""
    aktif = set(_get_aktif_kode_tender())
    p = {
        r["kode_tender"]
        for r in (_sb().table("paket_personil").select("kode_tender").execute().data or [])
    }
    return {
        "aktif": len(aktif),
        "personil": len(aktif & p),
        "lengkap": len(aktif & p),
        "belum_lengkap": len(aktif - p),
    }


def _overlap(mulai_a, selesai_a, mulai_b, selesai_b) -> bool:
    """True jika dua range tanggal overlap, atau salah satu None (konservatif)."""
    if mulai_a is None or selesai_a is None or mulai_b is None or selesai_b is None:
        return True  # data tidak lengkap = asumsi overlap
    return max(mulai_a, mulai_b) <= min(selesai_a, selesai_b)


def get_konflik_personil(kode_tender_target: str | None = None) -> list[dict]:
    """
    Return list personil yang muncul di >1 paket aktif dengan jadwal overlap.
    Jika kode_tender_target diisi, filter hanya konflik yang melibatkan paket itu.

    Return: [{
        "nama_personil": str (normalized),
        "nama_personil_display": str (nama asli pertama),
        "paket": [{"kode_tender":..., "nama_penyedia":..., "peserta_id":...,
                   "tgl_mulai": date|None, "tgl_selesai": date|None}]
    }]
    """
    aktif = _get_aktif_kode_tender()
    if not aktif:
        return []

    rows = _sb().table("paket_personil")\
        .select("kode_tender,peserta_id,nama_penyedia,nama_personil")\
        .in_("kode_tender", aktif).execute().data or []

    # Cache jadwal per kode_tender (lazy)
    _jadwal_cache: dict[str, tuple] = {}

    def _jadwal(kt: str) -> tuple:
        if kt not in _jadwal_cache:
            _jadwal_cache[kt] = _get_jadwal_paket(kt)
        return _jadwal_cache[kt]

    # Group by nama_personil NORMALIZED, simpan display name pertama
    from collections import defaultdict
    grouped: dict[str, list] = defaultdict(list)
    display_map: dict[str, str] = {}  # normalized → nama asli pertama
    for r in rows:
        nama_raw = r["nama_personil"] or ""
        norm = _normalize_nama(nama_raw)
        if not norm:
            continue
        if norm not in display_map:
            display_map[norm] = nama_raw
        # Tambah info jadwal ke entry
        mulai, selesai = _jadwal(r["kode_tender"])
        grouped[norm].append({
            "kode_tender": r["kode_tender"],
            "nama_penyedia": r["nama_penyedia"],
            "peserta_id": r["peserta_id"],
            "tgl_mulai": mulai,
            "tgl_selesai": selesai,
        })

    konflik = []
    for norm, entries in grouped.items():
        # Deduplikasi per kode_tender (ambil entry pertama per kode)
        seen_kt: dict[str, dict] = {}
        for e in entries:
            if e["kode_tender"] not in seen_kt:
                seen_kt[e["kode_tender"]] = e
        unique_entries = list(seen_kt.values())
        if len(unique_entries) <= 1:
            continue
        if kode_tender_target and kode_tender_target not in seen_kt:
            continue

        # Cek overlap jadwal antar semua kombinasi paket
        ada_overlap = False
        kt_list = unique_entries
        for i in range(len(kt_list)):
            for j in range(i + 1, len(kt_list)):
                ea, eb = kt_list[i], kt_list[j]
                if _overlap(ea["tgl_mulai"], ea["tgl_selesai"], eb["tgl_mulai"], eb["tgl_selesai"]):
                    ada_overlap = True
                    break
            if ada_overlap:
                break

        if not ada_overlap:
            continue

        # Satu baris per paket; variasi posisi/nama lama dalam paket yang sama
        # tidak boleh membuat konflik tampil berulang.
        konflik.append({
            "nama_personil": norm,
            "nama_personil_display": display_map[norm],
            "paket": unique_entries,
        })

    return konflik
