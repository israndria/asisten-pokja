"""
Conflict detection engine — personil & alat lintas paket.

Flow:
1. sync_from_supabase(kode_tender)  — ambil peserta_identitas, upsert ke paket_personil + paket_alat
2. sync_from_pdf(kode_tender, peserta_id, personel_list, peralatan_list)  — dari kualifikasi_parser
3. get_konflik_personil()  — query: nama muncul di >1 kode_tender dari draft_paket
4. get_konflik_alat()      — sama untuk alat
"""

import re
from config import sb as _sb


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


def _upsert_alat_batch(rows: list[dict]) -> None:
    if not rows:
        return
    _sb().table("paket_alat").upsert(rows, on_conflict="kode_tender,peserta_id,nama_alat").execute()


def sync_from_supabase(kode_tender: str, log=print) -> dict:
    """
    Ambil semua peserta_identitas untuk kode_tender,
    upsert personil dan alat ke paket_personil + paket_alat.
    Sumber = 'supabase'.
    """
    rows_p = _sb().table("peserta_identitas")\
        .select("peserta_id,nama_perusahaan,personel_1,personel_2,alat_1,alat_2,alat_3,alat_4,alat_5,alat_6")\
        .eq("kode_tender", kode_tender).execute().data or []

    upsert_p, upsert_a = [], []
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
        for key in ("alat_1", "alat_2", "alat_3", "alat_4", "alat_5", "alat_6"):
            raw = row.get(key, "")
            if not raw:
                continue
            upsert_a.append({
                "kode_tender":  kode_tender,
                "peserta_id":   pid,
                "nama_penyedia": nama_penyedia,
                "nama_alat":    raw.strip(),
                "posisi":       key.replace("_", " ").title(),
                "sumber":       "supabase",
            })

    _upsert_personil_batch(upsert_p)
    _upsert_alat_batch(upsert_a)
    log(f"sync_from_supabase {kode_tender}: {len(upsert_p)} personil, {len(upsert_a)} alat")
    return {"personil": len(upsert_p), "alat": len(upsert_a)}


def sync_from_pdf(
    kode_tender: str,
    peserta_id: str,
    nama_penyedia: str,
    personel_list: list[str],
    peralatan_list: list[str],
    log=print,
) -> dict:
    """
    Upsert personil dan alat dari hasil kualifikasi_parser (PDF).
    Sumber = 'pdf'. Menimpa entri 'supabase' lama jika ada.
    """
    upsert_p = [
        {
            "kode_tender":  kode_tender,
            "peserta_id":   peserta_id,
            "nama_penyedia": nama_penyedia,
            "nama_personil": _parse_nama(raw),
            "posisi":        _parse_posisi(raw) or f"Personel {i+1}",
            "sumber":        "pdf",
        }
        for i, raw in enumerate(personel_list)
        if raw and _parse_nama(raw)
    ]
    upsert_a = [
        {
            "kode_tender":  kode_tender,
            "peserta_id":   peserta_id,
            "nama_penyedia": nama_penyedia,
            "nama_alat":    raw.strip(),
            "posisi":       f"Alat {i+1}",
            "sumber":       "pdf",
        }
        for i, raw in enumerate(peralatan_list)
        if raw and raw.strip()
    ]

    _upsert_personil_batch(upsert_p)
    _upsert_alat_batch(upsert_a)
    log(f"sync_from_pdf {kode_tender} {peserta_id}: {len(upsert_p)} personil, {len(upsert_a)} alat")
    return {"personil": len(upsert_p), "alat": len(upsert_a)}


def _get_aktif_kode_tender() -> list[str]:
    """Semua kode_tender di draft_paket = paket aktif."""
    rows = _sb().table("draft_paket").select("kode_tender").execute().data or []
    return [r["kode_tender"] for r in rows if r.get("kode_tender")]


def get_konflik_personil(kode_tender_target: str | None = None) -> list[dict]:
    """
    Return list personil yang muncul di >1 paket aktif.
    Jika kode_tender_target diisi, filter hanya konflik yang melibatkan paket itu.

    Return: [{"nama_personil": ..., "paket": [{"kode_tender":..., "nama_penyedia":..., "peserta_id":...}]}]
    """
    aktif = _get_aktif_kode_tender()
    if not aktif:
        return []

    rows = _sb().table("paket_personil")\
        .select("kode_tender,peserta_id,nama_penyedia,nama_personil")\
        .in_("kode_tender", aktif).execute().data or []

    # Group by nama_personil
    from collections import defaultdict
    grouped: dict[str, list] = defaultdict(list)
    for r in rows:
        grouped[r["nama_personil"]].append(r)

    konflik = []
    for nama, entries in grouped.items():
        kode_set = {e["kode_tender"] for e in entries}
        if len(kode_set) <= 1:
            continue
        if kode_tender_target and kode_tender_target not in kode_set:
            continue
        konflik.append({"nama_personil": nama, "paket": entries})

    return konflik


def get_konflik_alat(kode_tender_target: str | None = None) -> list[dict]:
    """
    Return list alat yang muncul di >1 paket aktif.
    """
    aktif = _get_aktif_kode_tender()
    if not aktif:
        return []

    rows = _sb().table("paket_alat")\
        .select("kode_tender,peserta_id,nama_penyedia,nama_alat")\
        .in_("kode_tender", aktif).execute().data or []

    from collections import defaultdict
    grouped: dict[str, list] = defaultdict(list)
    for r in rows:
        grouped[r["nama_alat"]].append(r)

    konflik = []
    for nama, entries in grouped.items():
        kode_set = {e["kode_tender"] for e in entries}
        if len(kode_set) <= 1:
            continue
        if kode_tender_target and kode_tender_target not in kode_set:
            continue
        konflik.append({"nama_alat": nama, "paket": entries})

    return konflik
