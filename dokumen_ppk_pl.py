"""Monitor upload dokumen PPK pada paket Pengadaan Langsung."""

from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urljoin

import requests
from bs4 import BeautifulSoup

from config import SPSE_BASE_URL, sb as _sb


BASE_URL = SPSE_BASE_URL.rstrip("/")
SNAPSHOT_NAMESPACE = "_dokumen_ppk_pl"
DOCUMENT_TYPES = {
    "spek": "KAK & Spesifikasi Teknis",
    "docsskk": "Rancangan Kontrak",
    "docuraian": "Uraian Singkat Pekerjaan",
    "lainnya": "Informasi Lainnya",
    "nota_dinas": "Nota Dinas PPK",
}
_ORIGIN = "https://spse.inaproc.id"
_LOGIN_MARKERS = (
    'name="username"',
    'id="username"',
    "silakan login",
    "session expired",
)


class DokumenPpkPlError(RuntimeError):
    """Error terstruktur agar UI dapat membedakan sesi invalid dari dokumen kosong."""

    def __init__(self, message: str, *, kind: str = "request"):
        super().__init__(message)
        self.kind = kind


def _headers(referer: str, cookie_str: str) -> dict[str, str]:
    return {
        "Cookie": cookie_str,
        "Referer": referer or BASE_URL,
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }


def _get_cookies() -> str:
    from spse_browser import get_spse_cookies

    return get_spse_cookies()


def _get_html(url: str, cookie_str: str) -> tuple[str, str]:
    """GET halaman SPSE dengan retry singkat untuk gangguan transient."""
    last_error = None
    for attempt, delay in enumerate((0.0, 1.5, 4.0), start=1):
        if delay:
            time.sleep(delay)
        try:
            response = requests.get(
                url,
                headers=_headers(url, cookie_str),
                timeout=20,
                allow_redirects=True,
            )
            final_url = str(getattr(response, "url", url) or url)
            if response.status_code in (401, 403):
                raise DokumenPpkPlError(
                    f"HTTP {response.status_code}: sesi SPSE tidak valid",
                    kind="session",
                )
            if response.status_code in (429, 500, 502, 503, 504):
                last_error = f"HTTP {response.status_code}"
                if attempt < 3:
                    continue
                raise DokumenPpkPlError(
                    f"SPSE gagal merespons ({last_error})",
                    kind="server",
                )
            if response.status_code != 200:
                raise DokumenPpkPlError(
                    f"HTTP {response.status_code} saat membaca {url}",
                    kind="request",
                )
            text = response.text or ""
            lowered = text.lower()
            final_path = final_url.lower().rstrip("/")
            if final_path.endswith("/login") or any(marker in lowered for marker in _LOGIN_MARKERS):
                raise DokumenPpkPlError(
                    "Sesi SPSE tidak valid — server mengembalikan halaman login",
                    kind="session",
                )
            return text, final_url
        except DokumenPpkPlError:
            raise
        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as exc:
            last_error = str(exc)
            if attempt >= 3:
                raise DokumenPpkPlError(
                    f"Koneksi SPSE gagal setelah 3 percobaan: {last_error}",
                    kind="network",
                ) from exc
    raise DokumenPpkPlError(f"Gagal membaca SPSE: {last_error or 'unknown error'}")


def _clean_name(value: str) -> str:
    value = re.sub(r"\s*[-–—]\s*\d+\s*[KkMm][Bb]\s*$", "", str(value or "")).strip()
    return value or "dokumen"


def _parse_file_table(html: str) -> list[dict[str, str]]:
    """Ambil nama, tanggal, dan href download dari tabel #files."""
    soup = BeautifulSoup(html, "html.parser")
    table = soup.find("table", id="files")
    rows = table.select("tbody tr") if table else []
    if not rows:
        rows = soup.select("table tr")

    result = []
    seen = set()
    for row in rows:
        link = row.find("a", href=re.compile(r"/dl/"))
        if not link:
            continue
        href = str(link.get("href") or "").strip()
        if not href:
            continue
        href = urljoin(_ORIGIN, href)
        name = _clean_name(link.get_text(" ", strip=True))
        cells = row.find_all("td")
        tanggal = cells[1].get_text(" ", strip=True) if len(cells) > 1 else ""
        key = (name.casefold(), tanggal, href)
        if key in seen:
            continue
        seen.add(key)
        result.append({"nama": name, "tanggal": tanggal, "url_dl": href})
    return result


def _canonical_category_urls(kode_paket: str, edit_html: str) -> dict[str, str]:
    """Gunakan href kategori dari halaman edit; fallback hanya bila tidak tersedia."""
    urls = {
        kind: f"{BASE_URL}/dokumennontender/{kode_paket}/{kind}"
        for kind in ("spek", "docsskk", "docuraian", "lainnya")
    }
    for link in BeautifulSoup(edit_html, "html.parser").find_all("a", href=True):
        href = str(link.get("href") or "")
        match = re.search(
            r"/dokumennontender/([^/]+)/(spek|docsskk|docuraian|lainnya)(?:[/?#]|$)",
            href,
            re.IGNORECASE,
        )
        if match:
            urls[match.group(2).lower()] = urljoin(_ORIGIN, href)
    return urls


def fetch_live_snapshot(kode_paket: str, cookie_str: str | None = None) -> dict[str, list[dict[str, str]]]:
    """Fetch seluruh daftar dokumen PPK PL tanpa mengunduh isi file."""
    kode = str(kode_paket or "").strip()
    if not kode:
        raise DokumenPpkPlError("Kode paket kosong", kind="input")
    cookie = cookie_str if cookie_str is not None else _get_cookies()
    if not cookie:
        raise DokumenPpkPlError(
            "Cookie SPSE kosong — buka Brave SPSE dan login sebagai PP.",
            kind="session",
        )

    edit_url = f"{BASE_URL}/nontender/{kode}/edit"
    edit_html, _ = _get_html(edit_url, cookie)
    category_urls = _canonical_category_urls(kode, edit_html)

    snapshot = {
        "spek": [],
        "docsskk": [],
        "docuraian": [],
        "lainnya": [],
        "nota_dinas": _parse_file_table(edit_html),
    }
    for kind in ("spek", "docsskk", "docuraian", "lainnya"):
        html, _ = _get_html(category_urls[kind], cookie)
        snapshot[kind] = _parse_file_table(html)
    return snapshot


def _name_key(name: str) -> tuple[str, str]:
    stem, ext = str(name or "").strip().lower().rsplit(".", 1) if "." in str(name or "") else (str(name or ""), "")
    stem = re.sub(r"[\W_]+", " ", stem, flags=re.UNICODE)
    return " ".join(stem.split()), f".{ext}" if ext else ""


def _semantic_name(name: str) -> str:
    stem, _ = _name_key(name)
    return "".join(char for char in stem if char.isalnum())


def _similar_name(old_name: str, new_name: str) -> float:
    old_key = _semantic_name(old_name)
    new_key = _semantic_name(new_name)
    if not old_key or not new_key:
        return 0.0
    old_ext = _name_key(old_name)[1]
    new_ext = _name_key(new_name)[1]
    if old_ext != new_ext:
        return 0.0
    return SequenceMatcher(None, old_key, new_key).ratio()


def compare_snapshots(
    snapshot_lama: dict | None,
    snapshot_baru: dict | None,
) -> dict[str, list[dict]]:
    """Bandingkan nama + tanggal; rename mirip ditahan untuk verifikasi manual."""
    old = snapshot_lama if isinstance(snapshot_lama, dict) else {}
    new = snapshot_baru if isinstance(snapshot_baru, dict) else {}
    changed: list[dict] = []
    added: list[dict] = []
    missing: list[dict] = []
    verify: list[dict] = []

    for kind, label in DOCUMENT_TYPES.items():
        old_items = [dict(item) for item in (old.get(kind) or []) if isinstance(item, dict)]
        new_items = [dict(item) for item in (new.get(kind) or []) if isinstance(item, dict)]
        unmatched_old = list(old_items)
        unmatched_new = list(new_items)

        for old_item in old_items:
            old_key = _name_key(old_item.get("nama", ""))
            match_index = next(
                (
                    index
                    for index, item in enumerate(unmatched_new)
                    if _name_key(item.get("nama", "")) == old_key
                ),
                None,
            )
            if match_index is None:
                continue
            new_item = unmatched_new.pop(match_index)
            unmatched_old.remove(old_item)
            if str(old_item.get("tanggal") or "") != str(new_item.get("tanggal") or ""):
                changed.append({
                    "jenis": label,
                    "kode_jenis": kind,
                    "nama_lama": old_item.get("nama", ""),
                    "nama_baru": new_item.get("nama", ""),
                    "tanggal_lama": old_item.get("tanggal", ""),
                    "tanggal_baru": new_item.get("tanggal", ""),
                    "url_dl": new_item.get("url_dl", ""),
                })

        for old_item in list(unmatched_old):
            candidates = [
                (index, _similar_name(old_item.get("nama", ""), item.get("nama", "")))
                for index, item in enumerate(unmatched_new)
            ]
            candidates = sorted(candidates, key=lambda pair: pair[1], reverse=True)
            if candidates and candidates[0][1] >= 0.72:
                best_index, score = candidates[0]
                second_score = candidates[1][1] if len(candidates) > 1 else 0.0
                if score - second_score >= 0.04:
                    new_item = unmatched_new.pop(best_index)
                    unmatched_old.remove(old_item)
                    verify.append({
                        "jenis": label,
                        "kode_jenis": kind,
                        "nama_lama": old_item.get("nama", ""),
                        "nama_baru": new_item.get("nama", ""),
                        "tanggal_lama": old_item.get("tanggal", ""),
                        "tanggal_baru": new_item.get("tanggal", ""),
                        "url_dl": new_item.get("url_dl", ""),
                        "alasan": "nama mirip tetapi tidak identik; verifikasi manual diperlukan",
                    })

        added.extend(
            {
                "jenis": label,
                "kode_jenis": kind,
                "nama": item.get("nama", ""),
                "tanggal": item.get("tanggal", ""),
                "url_dl": item.get("url_dl", ""),
            }
            for item in unmatched_new
        )
        missing.extend(
            {
                "jenis": label,
                "kode_jenis": kind,
                "nama": item.get("nama", ""),
                "tanggal": item.get("tanggal", ""),
            }
            for item in unmatched_old
        )

    return {
        "berubah": changed,
        "baru": added,
        "perlu_verifikasi": verify,
        "hilang": missing,
    }


def _as_dict(value) -> dict:
    if isinstance(value, dict):
        return dict(value)
    if isinstance(value, str) and value.strip():
        try:
            decoded = json.loads(value)
            return dict(decoded) if isinstance(decoded, dict) else {}
        except (TypeError, ValueError):
            return {}
    return {}


def _read_data_snapshot(kode_paket: str) -> dict:
    result = (
        _sb()
        .table("draft_paket_pl")
        .select("data_snapshot")
        .eq("kode_paket", str(kode_paket))
        .limit(1)
        .execute()
    )
    rows = getattr(result, "data", None) or []
    return _as_dict(rows[0].get("data_snapshot")) if rows else {}


def load_saved_snapshot(kode_paket: str, jenis_pl: str) -> tuple[dict, bool]:
    """Ambil snapshot monitor tanpa membuang namespace data_snapshot lain."""
    data = _read_data_snapshot(kode_paket)
    namespace = _as_dict(data.get(SNAPSHOT_NAMESPACE))
    packages = _as_dict(namespace.get("paket"))
    entry = _as_dict(packages.get(str(kode_paket)))
    if str(entry.get("jenis_pl") or "").upper() != str(jenis_pl or "").upper():
        return {}, False
    files = entry.get("files")
    return (_as_dict(files), bool(entry.get("captured_at"))) if isinstance(files, dict) else ({}, False)


def save_snapshot(kode_paket: str, jenis_pl: str, snapshot: dict) -> None:
    """Simpan snapshot hanya pada namespace khusus, mempertahankan key lain."""
    data = _read_data_snapshot(kode_paket)
    namespace = _as_dict(data.get(SNAPSHOT_NAMESPACE))
    packages = _as_dict(namespace.get("paket"))
    packages[str(kode_paket)] = {
        "jenis_pl": str(jenis_pl or "").upper(),
        "captured_at": datetime.now(timezone.utc).isoformat(),
        "files": snapshot,
    }
    namespace.update({"version": 1, "paket": packages})
    data[SNAPSHOT_NAMESPACE] = namespace
    (
        _sb()
        .table("draft_paket_pl")
        .update({"data_snapshot": data})
        .eq("kode_paket", str(kode_paket))
        .execute()
    )


def check_dokumen_ppk_pl(kode_paket: str, jenis_pl: str) -> dict:
    """Cek live dokumen PPK; baseline pertama disimpan otomatis."""
    snapshot_lama, baseline_exists = load_saved_snapshot(kode_paket, jenis_pl)
    snapshot_baru = fetch_live_snapshot(kode_paket)
    diff = compare_snapshots(snapshot_lama, snapshot_baru)
    diff.update({
        "kode_paket": str(kode_paket),
        "jenis_pl": str(jenis_pl or "").upper(),
        "snapshot_lama": snapshot_lama,
        "snapshot_baru": snapshot_baru,
        "baseline_created": False,
        "ada_update": bool(
            diff["berubah"] or diff["baru"] or diff["perlu_verifikasi"] or diff["hilang"]
        ),
    })
    if not baseline_exists:
        save_snapshot(kode_paket, jenis_pl, snapshot_baru)
        diff["baseline_created"] = True
        diff["ada_update"] = False
    return diff
