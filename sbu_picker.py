"""
sbu_picker.py — Helper SBU dropdown 2-tahap (klasifikasi → kode_baru → padanan_lama).

Cache: 1 jam (data jarang berubah).

Public API:
  - list_klasifikasi() -> list[str]
  - list_sbu_baru_by_klasifikasi(klasifikasi) -> list[dict]  # {kode, nama_full, nama_singkat}
  - list_sbu_lama_padanan(kode_baru) -> list[dict]           # {kode, nama_full, nama_singkat}
  - get_sbu_baru_by_kode(kode) -> dict
  - get_sbu_lama_by_kode(kode) -> dict
  - format_for_ldk_jkk(sbu_baru_full, sbu_lama_full) -> str  # 'a) X atau; b) Y.'
"""
import time
from config import sb

_CACHE = {"data": None, "ts": 0}
_TTL = 3600


def _load_all() -> dict:
    """Load semua data v_sbu_complete sekali, cache 1 jam."""
    now = time.time()
    if _CACHE["data"] and (now - _CACHE["ts"]) < _TTL:
        return _CACHE["data"]

    client = sb()
    # SBU baru lengkap
    baru_rows = client.table("master_sbu_baru").select("*").order("klasifikasi,kode").execute().data
    lama_rows = client.table("master_sbu_lama").select("*").order("kode").execute().data
    map_rows = client.table("sbu_mapping").select("kode_baru,kode_lama").execute().data

    by_baru = {r["kode"]: r for r in baru_rows}
    by_lama = {r["kode"]: r for r in lama_rows}
    mapping = {}  # kode_baru -> [kode_lama]
    for m in map_rows:
        mapping.setdefault(m["kode_baru"], []).append(m["kode_lama"])

    klasifikasi_set = sorted({r["klasifikasi"] for r in baru_rows if r.get("klasifikasi")})

    data = {
        "by_baru":      by_baru,
        "by_lama":      by_lama,
        "mapping":      mapping,
        "klasifikasi":  klasifikasi_set,
        "baru_rows":    baru_rows,
    }
    _CACHE["data"] = data
    _CACHE["ts"] = now
    return data


def clear_cache():
    _CACHE["data"] = None
    _CACHE["ts"] = 0


def list_klasifikasi() -> list[str]:
    return _load_all()["klasifikasi"]


def list_sbu_baru_by_klasifikasi(klasifikasi: str) -> list[dict]:
    d = _load_all()
    return [r for r in d["baru_rows"] if r.get("klasifikasi") == klasifikasi]


def list_sbu_lama_padanan(kode_baru: str) -> list[dict]:
    """Return list dict SBU lama yg jadi padanan kode_baru."""
    d = _load_all()
    lama_kodes = d["mapping"].get(kode_baru, [])
    return [d["by_lama"][k] for k in lama_kodes if k in d["by_lama"]]


def get_sbu_baru_by_kode(kode: str) -> dict:
    return _load_all()["by_baru"].get(kode, {})


def get_sbu_lama_by_kode(kode: str) -> dict:
    return _load_all()["by_lama"].get(kode, {})


def format_for_ldk_jkk(sbu_baru_full: str, sbu_lama_full: str = "") -> str:
    """
    Format SBU sesuai layout LDK JKK:
    - baru + lama: 'a) <baru> atau; b) <lama>.'
    - baru saja  : '<baru>.'
    """
    if sbu_baru_full and sbu_lama_full:
        return f"a) {sbu_baru_full} atau; b) {sbu_lama_full}."
    elif sbu_baru_full:
        return f"{sbu_baru_full}."
    elif sbu_lama_full:
        return f"{sbu_lama_full}."
    return ""


def detect_from_draft(draft_sbu_baru: str, draft_sbu_lama: str) -> dict:
    """
    Detect kode SBU dari string draft_paket_pl (hasil parse_kak_pl).
    Return {kode_baru, kode_lama} jika cocok di master_sbu_*, else {}.
    """
    import re
    out = {}
    if draft_sbu_baru:
        m = re.search(r"\b([A-Z]{2}\d{3})\b", draft_sbu_baru)
        if m:
            kb = m.group(1).upper()
            if kb in _load_all()["by_baru"]:
                out["kode_baru"] = kb
    if draft_sbu_lama:
        m = re.search(r"\b([A-Z]{2}\d{3})\b", draft_sbu_lama)
        if m:
            kl = m.group(1).upper()
            if kl in _load_all()["by_lama"]:
                out["kode_lama"] = kl
    return out
