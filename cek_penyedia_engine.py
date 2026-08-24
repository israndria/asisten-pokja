"""Cek penyedia lintas Tender/Non-Tender untuk gate SKP PL PK.

Sumber data sama dengan SPSE Scraper V3: ``tender_peserta``, ``tender`` dan
``non_tender``. Peserta tender ditampilkan sebagai konteks, tetapi hanya row
yang benar-benar pemenang dan masih berjalan yang masuk hitungan SKP.
"""

from __future__ import annotations

import re
from collections import defaultdict
from datetime import date, datetime
from typing import Callable


SKP_LIMIT = 5
SKP_HEURISTIC_COMPLETION_DAYS = 30
_TERMINAL_STAGE_MARKERS = (
    "selesai",
    "dibatalkan",
    "batal",
    "gagal",
    "tidak ada jadwal",
)
_DEFAULT_PROVIDER_NAMES = {"", "belum ada pemenang", "belum ada kontrak", "-", "nan", "none"}
_INDONESIAN_MONTHS = {
    "januari": 1,
    "februari": 2,
    "maret": 3,
    "april": 4,
    "mei": 5,
    "juni": 6,
    "juli": 7,
    "agustus": 8,
    "september": 9,
    "oktober": 10,
    "november": 11,
    "desember": 12,
}


def _sb_default():
    from config import sb

    return sb()


def _text(value) -> str:
    return str(value or "").strip()


def _query_pattern(query: str) -> str:
    # Jangan izinkan wildcard input memperlebar pencarian tanpa sengaja.
    return f"%{re.sub(r'[%_]', '', _text(query))}%"


def _is_pemenang(value) -> bool:
    if value is None:
        return False
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "t", "yes", "y"}
    return bool(value)


def _is_real_provider(value) -> bool:
    return _text(value).lower() not in _DEFAULT_PROVIDER_NAMES


def _is_contract_holder(provider_name: str, contract_name: str) -> bool:
    """True bila SPSE sudah mencatat penyedia sebagai pemenang berkontrak."""
    if not _is_real_provider(contract_name):
        return False
    return _provider_key(provider_name)[1] == _provider_key(contract_name)[1]


def _today() -> date:
    return date.today()


def _parse_kontrak_selesai(value) -> date | None:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    raw = _text(value)
    if not raw:
        return None
    iso_value = raw.replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(iso_value).date()
    except ValueError:
        pass
    for fmt in ("%d/%m/%Y", "%d-%m-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            pass
    match = re.fullmatch(r"(\d{1,2})\s+([A-Za-z]+)\s+(\d{4})", raw.lower())
    if match:
        month = _INDONESIAN_MONTHS.get(match.group(2))
        if month:
            try:
                return date(int(match.group(3)), month, int(match.group(1)))
            except ValueError:
                pass
    return None


def _classify_contract_completion(value, *, today: date | None = None) -> tuple[date | None, int | None, bool]:
    parsed = _parse_kontrak_selesai(value)
    if parsed is None:
        return None, None, False
    age_days = (today or _today()) - parsed
    return parsed, age_days.days, age_days.days > SKP_HEURISTIC_COMPLETION_DAYS


def is_paket_berjalan(tahapan) -> bool:
    """True bila tahap proses SPSE belum terminal.

    Ini hanya proxy tahap pengadaan, bukan bukti PHO atau selesai fisik.
    """
    tahap = _text(tahapan).lower()
    return bool(tahap) and not any(marker in tahap for marker in _TERMINAL_STAGE_MARKERS)


def is_pekerjaan_konstruksi(jenis_pengadaan) -> bool:
    value = _text(jenis_pengadaan).lower()
    return value.startswith("pekerjaan konstruksi") or value == "konstruksi"


def _provider_key(name: str, npwp: str = "") -> tuple[str, str]:
    digits = re.sub(r"\D", "", _text(npwp))
    if digits and len(set(digits)) > 1:
        return ("npwp", digits)
    compact_name = re.sub(r"[^a-z0-9]+", " ", _text(name).lower()).strip()
    return ("nama", compact_name)


def status_skp(jumlah: int, limit: int = SKP_LIMIT) -> str:
    if jumlah < limit:
        return f"Aman — {jumlah}/{limit} pekerjaan berjalan"
    if jumlah == limit:
        return f"Batas tercapai — {jumlah}/{limit} pekerjaan berjalan"
    return f"Melebihi batas — {jumlah}/{limit} pekerjaan berjalan"


def _skp_row_status(row: dict) -> str:
    if not row.get("is_pemenang"):
        return "Tidak — peserta bukan pemenang"
    if not row.get("is_berkontrak"):
        return "Tidak — pemenang belum berkontrak"
    if row.get("kontrak_selesai_heuristik"):
        return "Tidak — kontrak selesai (heuristik)"
    if row.get("is_pemenang_berjalan"):
        return "Ya — berkontrak, aktif ≤30 hari dari tanggal selesai"
    if row.get("is_berjalan"):
        return "Ya — berkontrak, tahap SPSE aktif"
    return "Perlu verifikasi — kontrak ada, status selesai fisik belum terbukti"


def _provider_row_key(row: dict) -> tuple:
    return (
        _text(row.get("source")),
        _text(row.get("kode_tender")),
        _text(row.get("urutan")),
        _text(row.get("nama_peserta")).lower(),
    )


def _package_info(sb, source: str, codes: set[str]) -> dict[tuple[str, str], dict]:
    if not codes:
        return {}
    table = "tender" if source == "Tender" else "non_tender"
    select = (
        "kode_tender,nama_paket,instansi,tahapan,jenis_pengadaan,"
        "nama_pemenang,pemenang_berkontrak,kontrak_mulai,kontrak_selesai,link_detail"
    )
    rows = (
        sb.table(table)
        .select(select)
        .in_("kode_tender", sorted(codes))
        .execute()
        .data
        or []
    )
    return {(source, _text(row.get("kode_tender"))): dict(row) for row in rows}


def search_provider(
    query: str,
    sb_factory: Callable | None = None,
    include_non_construction: bool = False,
) -> dict:
    """Cari keterlibatan penyedia dan kembalikan row pemenang/peserta."""
    query = _text(query)
    if len(query) < 3:
        return {"ok": False, "rows": [], "error": "Pencarian minimal 3 karakter."}

    sb = (sb_factory or _sb_default)()
    pattern = _query_pattern(query)
    peserta_select = (
        "kode_tender,urutan,nama_peserta,npwp,harga_penawaran,harga_negosiasi,"
        "skor_akhir,alasan_gugur,is_pemenang"
    )
    collected: list[dict] = []
    seen: set[tuple] = set()
    seen_non_tender_codes: set[str] = set()

    for field in ("nama_peserta", "npwp"):
        rows = (
            sb.table("tender_peserta")
            .select(peserta_select)
            .ilike(field, pattern)
            .limit(200)
            .execute()
            .data
            or []
        )
        for raw in rows:
            row = dict(raw)
            row["source"] = "Tender"
            row["is_pemenang"] = _is_pemenang(row.get("is_pemenang"))
            key = _provider_row_key(row)
            if key not in seen:
                seen.add(key)
                collected.append(row)

    nt_select = (
        "kode_tender,nama_paket,instansi,tahapan,jenis_pengadaan,"
        "nama_pemenang,pemenang_berkontrak,kontrak_mulai,kontrak_selesai,"
        "link_detail,harga_kontrak"
    )
    for field in ("nama_pemenang", "pemenang_berkontrak"):
        rows = (
            sb.table("non_tender")
            .select(nt_select)
            .ilike(field, pattern)
            .limit(200)
            .execute()
            .data
            or []
        )
        for raw in rows:
            provider = _text(raw.get(field))
            if provider.lower() in _DEFAULT_PROVIDER_NAMES:
                continue
            row = {
                "source": "Non Tender",
                "kode_tender": raw.get("kode_tender"),
                "urutan": 0,
                "nama_peserta": provider,
                "npwp": "-",
                "harga_penawaran": raw.get("harga_kontrak", "0"),
                "harga_negosiasi": "-",
                "skor_akhir": "-",
                "alasan_gugur": "",
                "is_pemenang": True,
            }
            # Non-Tender hanya memiliki satu pemenang per paket. Nama pada
            # `nama_pemenang` dan `pemenang_berkontrak` bisa beda format;
            # jangan hitung satu paket dua kali.
            nt_code = _text(row.get("kode_tender"))
            if not nt_code:
                continue
            if nt_code in seen_non_tender_codes:
                continue
            seen_non_tender_codes.add(nt_code)
            key = _provider_row_key(row)
            if key not in seen:
                seen.add(key)
                collected.append(row)

    by_source: dict[str, set[str]] = defaultdict(set)
    for row in collected:
        by_source[row["source"]].add(_text(row.get("kode_tender")))

    info: dict[tuple[str, str], dict] = {}
    for source, codes in by_source.items():
        info.update(_package_info(sb, source, codes))

    result = []
    for row in collected:
        source = row["source"]
        package = info.get((source, _text(row.get("kode_tender"))), {})
        if not include_non_construction and not is_pekerjaan_konstruksi(
            package.get("jenis_pengadaan")
        ):
            continue
        item = {**row, **package}
        item["is_pemenang"] = _is_pemenang(item.get("is_pemenang"))
        item["is_berjalan"] = is_paket_berjalan(item.get("tahapan"))
        item["is_berkontrak"] = _is_contract_holder(
            item.get("nama_peserta"), item.get("pemenang_berkontrak")
        )
        (
            item["kontrak_selesai_parsed"],
            item["kontrak_selesai_umur_hari"],
            item["kontrak_selesai_heuristik"],
        ) = _classify_contract_completion(item.get("kontrak_selesai"))
        if item["kontrak_selesai_parsed"] is not None:
            item["is_pemenang_berjalan"] = (
                item["is_pemenang"]
                and item["is_berkontrak"]
                and not item["kontrak_selesai_heuristik"]
            )
            item["skp_perlu_verifikasi"] = False
        else:
            item["is_pemenang_berjalan"] = (
                item["is_pemenang"] and item["is_berjalan"] and item["is_berkontrak"]
            )
            item["skp_perlu_verifikasi"] = (
                item["is_pemenang"] and item["is_berkontrak"] and not item["is_berjalan"]
            )
        item["skp_status"] = _skp_row_status(item)
        item["status_peran"] = "Pemenang" if item["is_pemenang"] else "Peserta — bukan pemenang"
        result.append(item)

    return {"ok": True, "rows": result, "error": ""}


def summarize_provider_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows or []:
        # V20 menampilkan satu kartu per nama penyedia. Ini juga menyatukan
        # row Tender ber-NPWP dengan row Non-Tender yang NPWP-nya kosong.
        name = _text(row.get("nama_peserta"))
        if name and name.lower() not in _DEFAULT_PROVIDER_NAMES:
            key = _provider_key(name)
        else:
            key = _provider_key(name, row.get("npwp"))
        grouped[key].append(row)

    summaries = []
    for key, items in grouped.items():
        winners = [row for row in items if row.get("is_pemenang")]
        winner_running = [row for row in winners if row.get("is_pemenang_berjalan")]
        winner_review = [row for row in winners if row.get("skp_perlu_verifikasi")]
        status = status_skp(len(winner_running))
        if winner_review:
            status = (
                f"Perlu verifikasi — {len(winner_running)}/{SKP_LIMIT} aktif terverifikasi; "
                f"{len(winner_review)} kontrak belum terbukti selesai"
            )
        summaries.append({
            "provider_key": key,
            "nama_penyedia": _text(items[0].get("nama_peserta")) or "-",
            "npwp": next((_text(row.get("npwp")) for row in items if _text(row.get("npwp")) not in {"", "-"}), "-"),
            "total_keterlibatan": len(items),
            "paket_dimenangkan": len(winners),
            "peserta_bukan_pemenang": len(items) - len(winners),
            "paket_berjalan": sum(bool(row.get("is_berjalan")) for row in items),
            "skp_berjalan": len(winner_running),
            "skp_perlu_verifikasi": len(winner_review),
            "skp_konservatif": len(winner_running) + len(winner_review),
            "status": status,
            "rows": items,
        })
    return sorted(summaries, key=lambda row: row["nama_penyedia"].lower())


def check_selected_providers(
    selected_rows: list[dict],
    sb_factory: Callable | None = None,
    include_non_construction: bool = False,
) -> dict:
    """Cek provider dari Excel terpilih dan proyeksikan batch yang akan dipilih."""
    candidates: dict[tuple[str, str], dict] = {}
    for row in selected_rows or []:
        name = _text(row.get("nama_penyedia"))
        npwp = _text(row.get("npwp_penyedia"))
        if not name and not npwp:
            continue
        key = _provider_key(name, npwp)
        candidate = candidates.setdefault(
            key,
            {"nama_penyedia": name or "-", "npwp": npwp or "-", "kode_paket": set(), "queries": []},
        )
        if row.get("kode_paket"):
            candidate["kode_paket"].add(_text(row["kode_paket"]))
        for query in (name, npwp):
            if len(query) >= 3 and query not in candidate["queries"]:
                candidate["queries"].append(query)

    if not candidates:
        return {"ok": False, "providers": [], "rows": [], "errors": ["Identitas penyedia belum lengkap."]}

    all_rows: list[dict] = []
    providers = []
    errors = []
    for candidate in candidates.values():
        merged: dict[tuple, dict] = {}
        for query in candidate["queries"]:
            found = search_provider(
                query,
                sb_factory=sb_factory,
                include_non_construction=include_non_construction,
            )
            if not found.get("ok"):
                errors.append(f"{candidate['nama_penyedia']}: {found.get('error', 'query gagal')}")
                continue
            for item in found.get("rows", []):
                merged[_provider_row_key(item)] = item
        candidate_name_key = _provider_key(candidate["nama_penyedia"], "")[1]
        candidate_npwp = re.sub(r"\D", "", candidate["npwp"])
        provider_rows = [
            item
            for item in merged.values()
            if (
                candidate_npwp
                and re.sub(r"\D", "", _text(item.get("npwp"))) == candidate_npwp
            )
            or (
                item.get("source") == "Non Tender"
                and _provider_key(item.get("nama_peserta"), "")[1] == candidate_name_key
            )
            or (
                not candidate_npwp
                and _provider_key(item.get("nama_peserta"), "")[1] == candidate_name_key
            )
        ]
        all_rows.extend(provider_rows)
        summary = summarize_provider_rows(provider_rows)
        if summary:
            item = summary[0]
            # Satu provider dapat muncul sebagai NPWP di Tender dan tanpa
            # NPWP di Non-Tender. Setelah kandidat difilter, gabungkan semua
            # varian identitas agar hitungan SKP tidak mengecil.
            for extra in summary[1:]:
                for field in (
                    "total_keterlibatan",
                    "paket_dimenangkan",
                    "peserta_bukan_pemenang",
                    "paket_berjalan",
                    "skp_berjalan",
                    "skp_perlu_verifikasi",
                    "skp_konservatif",
                ):
                    item[field] += extra[field]
                item["rows"] = item.get("rows", []) + extra.get("rows", [])
            item["status"] = status_skp(item["skp_berjalan"])
            if item["skp_perlu_verifikasi"]:
                item["status"] = (
                    f"Perlu verifikasi — {item['skp_berjalan']}/{SKP_LIMIT} aktif terverifikasi; "
                    f"{item['skp_perlu_verifikasi']} kontrak belum terbukti selesai"
                )
        else:
            item = {
                "provider_key": _provider_key(candidate["nama_penyedia"], candidate["npwp"]),
                "nama_penyedia": candidate["nama_penyedia"],
                "npwp": candidate["npwp"],
                "total_keterlibatan": 0,
                "paket_dimenangkan": 0,
                "peserta_bukan_pemenang": 0,
                "paket_berjalan": 0,
                "skp_berjalan": 0,
                "skp_perlu_verifikasi": 0,
                "skp_konservatif": 0,
                "status": status_skp(0),
                "rows": [],
            }
        candidate_count = len(candidate["kode_paket"])
        item = dict(item)
        item["paket_baru_dicek"] = candidate_count
        item["skp_proyeksi"] = item["skp_berjalan"] + candidate_count
        item["skp_proyeksi_konservatif"] = item["skp_konservatif"] + candidate_count
        item["status_proyeksi"] = status_skp(item["skp_proyeksi"])
        item["boleh_submit"] = (
            item["skp_proyeksi"] <= SKP_LIMIT and not item["skp_perlu_verifikasi"]
        )
        providers.append(item)

    return {
        "ok": not errors,
        "providers": providers,
        "rows": all_rows,
        "errors": errors,
    }
