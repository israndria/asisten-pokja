"""Pure candidate filtering for the Tender workflow UI.

This module deliberately does not call SPSE, Supabase, Streamlit, or mutate
package/status data.  It only decides which already-loaded rows may be shown
for each Tender tab.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable, Mapping


_STAGE_RANKS = {
    "draft": 0,
    "undangan": 1,
    "jadwal": 2,
    "setup": 3,
    "pemberian_penjelasan": 4,
    "pemasukan_penawaran": 5,
    "pembukaan_penawaran": 6,
    "evaluasi": 7,
    "pembuktian_kualifikasi": 8,
    "klarifikasi_negosiasi": 9,
    "masa_sanggah": 10,
    "penetapan_pemenang": 11,
    "kontrak": 12,
    "selesai": 13,
}

_STAGE_ALIASES = (
    ("pemberian_penjelasan", ("pemberian penjelasan", "aanwijzing", "penjelasan")),
    ("pemasukan_penawaran", ("pemasukan dokumen penawaran", "pemasukan penawaran", "masa pemasukan")),
    ("pembukaan_penawaran", ("pembukaan dokumen penawaran", "pembukaan penawaran", "pembukaan")),
    ("pembuktian_kualifikasi", ("pembuktian kualifikasi", "pembuktian")),
    ("klarifikasi_negosiasi", ("klarifikasi dan negosiasi", "klarifikasi/negosiasi", "klarifikasi", "negosiasi")),
    ("masa_sanggah", ("masa sanggah", "sanggah")),
    ("penetapan_pemenang", ("penetapan pemenang", "penetapan", "pemenang")),
    ("kontrak", ("penunjukan penyedia", "surat penunjukan", "penandatanganan kontrak", "penandatanganan")),
    ("selesai", ("tender sudah selesai", "paket sudah selesai", "selesai")),
    ("evaluasi", ("evaluasi administrasi", "evaluasi kualifikasi", "evaluasi teknis", "evaluasi harga", "evaluasi")),
    ("jadwal", ("buat jadwal", "penyusunan jadwal", "jadwal tender")),
    ("undangan", ("kirim undangan", "undangan dpp", "undangan")),
    ("setup", ("setup paket", "persiapan paket")),
    ("draft", ("draft",)),
)

# Tab 4 is allowed through the current Pemberian Penjelasan stage.  Later
# tabs use the earliest stage at which their action is meaningful.  Terminal
# stages are excluded for every active tab.
_TAB_STAGE_LIMITS = {
    4: (None, "pemberian_penjelasan"),
    5: ("evaluasi", "pembuktian_kualifikasi"),
    6: ("pembukaan_penawaran", "penetapan_pemenang"),
    7: ("pembukaan_penawaran", "penetapan_pemenang"),
    8: ("evaluasi", "penetapan_pemenang"),
}


def normalize_stage(value: object) -> str:
    """Normalize SPSE labels for case/punctuation/diacritic-tolerant matching."""
    text = unicodedata.normalize("NFKD", str(value or ""))
    text = "".join(ch for ch in text if not unicodedata.combining(ch))
    text = re.sub(r"[^a-z0-9]+", " ", text.casefold())
    return " ".join(text.split())


def package_code(row: Mapping[str, object]) -> str:
    return str(
        row.get("kode")
        or row.get("kode_tender")
        or row.get("id_lelang")
        or row.get("kode_paket")
        or ""
    ).strip()


def is_draft(
    row: Mapping[str, object],
    draft_kodes: Iterable[str] = (),
    tahap_map: Mapping[str, object] | None = None,
) -> bool:
    code = package_code(row)
    known_draft = {str(value).strip() for value in draft_kodes if str(value).strip()}
    if code and code in known_draft:
        return True
    source = normalize_stage(row.get("_tender_source"))
    if source == "draft":
        return True
    tahap_map = tahap_map or {}
    status = normalize_stage(
        " ".join(
            str(row.get(key) or "")
            for key in ("status", "status_paket", "status_tender", "status_tahap")
        )
        + " "
        + str(tahap_map.get(code) or "")
    )
    return bool(re.search(r"\bdraft\b", status))


def stage_rank(row: Mapping[str, object], tahap_map: Mapping[str, object] | None = None) -> int | None:
    """Resolve current Tender stage, preferring live session map over row cache."""
    tahap_map = tahap_map or {}
    code = package_code(row)
    raw = tahap_map.get(code)
    if raw in (None, ""):
        raw = next((row.get(key) for key in ("status_tahap", "tahap_tender", "tahap_spse", "status") if row.get(key)), "")
    normalized = normalize_stage(raw)
    if not normalized:
        return None
    # Long/specific labels must win over generic words such as "penawaran".
    for key, aliases in _STAGE_ALIASES:
        if any(alias in normalized for alias in aliases):
            return _STAGE_RANKS[key]
    return None


def is_terminal(row: Mapping[str, object], tahap_map: Mapping[str, object] | None = None) -> bool:
    rank = stage_rank(row, tahap_map)
    return rank is not None and rank >= _STAGE_RANKS["kontrak"]


def _within_tab_stage(tab: int, rank: int | None) -> bool:
    limits = _TAB_STAGE_LIMITS.get(int(tab))
    if limits is None or rank is None:
        return False
    minimum, maximum = limits
    min_rank = _STAGE_RANKS[minimum] if minimum else 0
    return min_rank <= rank <= _STAGE_RANKS[maximum]


def filter_tender_candidates(
    rows: Iterable[Mapping[str, object]],
    tab: int,
    *,
    tahap_map: Mapping[str, object] | None = None,
    draft_kodes: Iterable[str] = (),
) -> list[dict]:
    """Return UI-only candidates for Tender tab 1..8.

    Tabs 1-3 are Draft-only. Tabs 4-8 require an active/tayang package and a
    recognized stage gate. Input rows are copied; no source object is mutated.
    """
    tab = int(tab)
    result = []
    for row in rows:
        copied = dict(row)
        draft = is_draft(copied, draft_kodes, tahap_map)
        if tab in (1, 2, 3):
            if draft:
                result.append(copied)
            continue
        if tab not in _TAB_STAGE_LIMITS or draft:
            continue
        rank = stage_rank(copied, tahap_map)
        if is_terminal(copied, tahap_map) or not _within_tab_stage(tab, rank):
            continue
        result.append(copied)
    return result


def stale_selection_keys(keys: Iterable[str], prefix: str, valid_codes: Iterable[str]) -> list[str]:
    """Pure helper: identify old widget keys for rows no longer candidates."""
    valid = {str(code).strip() for code in valid_codes}
    return [key for key in keys if key.startswith(prefix) and key[len(prefix):] not in valid]
