"""
Mode Pengadaan Langsung — Tab 0: Draft Paket PL
Input manual paket PL (JKK atau PK), simpan ke Supabase tabel draft_paket_pl.
"""

from datetime import datetime, timezone
from config import sb as _sb

SATKER_LIST = [
    "Dinas Perdagangan",
    "Dinas Pekerjaan Umum Dan Penataan Ruang (Bina Marga)",
    "Dinas Pekerjaan Umum Dan Penataan Ruang (PUPR)",
    "Kecamatan CLU",
    "Dinas Perizinan Terpadu Satu Pintu",
    "Lainnya",
]

STATUS_LIST = ["draft", "undangan", "evaluasi", "negosiasi", "selesai"]


def load_draft_pl() -> list[dict]:
    """Ambil semua baris draft_paket_pl, urut terbaru dulu."""
    try:
        return _sb().table("draft_paket_pl").select("*").order("diambil_pada", desc=True).execute().data or []
    except Exception as e:
        return []


def simpan_paket_pl(data: dict) -> dict:
    """
    Upsert satu paket PL ke draft_paket_pl.
    data harus memiliki key 'kode_paket'.
    Return: {"ok": True} atau {"ok": False, "error": str}
    """
    if not data.get("kode_paket"):
        return {"ok": False, "error": "kode_paket wajib diisi"}
    data.setdefault("diambil_pada", datetime.now(timezone.utc).isoformat())
    try:
        _sb().table("draft_paket_pl").upsert(data).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def hapus_paket_pl(kode_paket: str) -> dict:
    """Hapus satu baris dari draft_paket_pl berdasarkan kode_paket."""
    try:
        _sb().table("draft_paket_pl").delete().eq("kode_paket", kode_paket).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def update_status(kode_paket: str, status: str) -> dict:
    """Update kolom status paket PL."""
    try:
        _sb().table("draft_paket_pl").update({"status": status}).eq("kode_paket", kode_paket).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def tandai_folder_dibuat(kode_paket: str) -> dict:
    """Set folder_dibuat=True dan folder_dibuat_pada=now."""
    try:
        _sb().table("draft_paket_pl").update({
            "folder_dibuat": True,
            "folder_dibuat_pada": datetime.now(timezone.utc).isoformat(),
        }).eq("kode_paket", kode_paket).execute()
        return {"ok": True}
    except Exception as e:
        return {"ok": False, "error": str(e)}
