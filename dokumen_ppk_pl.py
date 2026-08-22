"""Monitor upload dokumen PPK pada paket Pengadaan Langsung."""

from __future__ import annotations

import json
import os
import re
import shutil
import tempfile
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from urllib.parse import urljoin, urlsplit, urlunsplit

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
DOWNLOAD_SUBFOLDER = "10. Revisi Uploadan PPK"
DOWNLOAD_ARCHIVE_SUBFOLDER = "10. Revisi Uploadan PPK - Archive"
_DOWNLOAD_TRANSIENT_STATUS = frozenset({429, 500, 502, 503, 504})


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


def _iter_snapshot_files(snapshot: dict | None):
    """Iterasi file snapshot dalam urutan kategori yang ditampilkan UI."""
    data = snapshot if isinstance(snapshot, dict) else {}
    for kind in DOCUMENT_TYPES:
        for item in data.get(kind) or []:
            if isinstance(item, dict):
                yield kind, item


def _resolve_package_folder(row: dict) -> str | None:
    """Cari folder fisik paket dengan resolver resmi PL, tanpa membuat folder baru."""
    from parse_kak_pl import _resolve_folder_pl

    folder, _ = _resolve_folder_pl(
        row.get("nomor_urut"),
        row.get("nama_paket") or "",
        row.get("jenis_pl") or "JKK",
        is_ulang=row.get("is_ulang", False),
        strict_name=True,
    )
    return folder if folder and os.path.isdir(folder) else None


def _clean_download_filename(value: str) -> str:
    """Jadikan nama metadata aman sebagai satu nama file Windows."""
    name = str(value or "").replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[<>:"/\\|?*]', "_", name).strip().rstrip(" .")
    return name or "dokumen"


def _bounded_download_filename(folder: str, filename: str) -> str:
    """Pakai batas path download yang sudah dipakai engine PL lainnya."""
    from pl_engine import _safe_download_name_for_folder

    return _safe_download_name_for_folder(folder, filename)


def _unique_download_path(folder: str, filename: str) -> str:
    """Pilih nama baru agar file lama tidak pernah tertimpa."""
    safe_name = _bounded_download_filename(folder, _clean_download_filename(filename))
    candidate = os.path.join(folder, safe_name)
    if not os.path.exists(candidate):
        return candidate

    stem, ext = os.path.splitext(safe_name)
    number = 2
    while True:
        numbered = _bounded_download_filename(folder, f"{stem}_{number}{ext}")
        candidate = os.path.join(folder, numbered)
        if not os.path.exists(candidate):
            return candidate
        number += 1


def _archive_active_revision_files(folder_paket: str, folder_tujuan: str) -> str:
    """Pindahkan batch aktif ke archive bertimestamp dengan rollback lokal."""
    with os.scandir(folder_tujuan) as scan:
        entries = list(scan)
    if not entries:
        return ""

    archive_root = os.path.join(folder_paket, DOWNLOAD_ARCHIVE_SUBFOLDER)
    os.makedirs(archive_root, exist_ok=True)
    stamp = datetime.now().astimezone().strftime("%Y%m%d-%H%M%S")
    archive_dir = os.path.join(archive_root, stamp)
    suffix = 2
    while os.path.exists(archive_dir):
        archive_dir = os.path.join(archive_root, f"{stamp}_{suffix}")
        suffix += 1
    os.makedirs(archive_dir)

    moved = []
    try:
        for entry in entries:
            destination = os.path.join(archive_dir, entry.name)
            shutil.move(entry.path, destination)
            moved.append(destination)
    except Exception:
        for destination in reversed(moved):
            if os.path.exists(destination):
                shutil.move(destination, os.path.join(folder_tujuan, os.path.basename(destination)))
        try:
            os.rmdir(archive_dir)
        except OSError:
            pass
        raise
    return archive_dir


def _restore_archived_revision_files(archive_dir: str, folder_tujuan: str) -> None:
    """Kembalikan archive ke folder aktif setelah promosi batch baru gagal."""
    if not archive_dir or not os.path.isdir(archive_dir):
        return
    with os.scandir(archive_dir) as scan:
        entries = list(scan)
    for entry in entries:
        destination = os.path.join(folder_tujuan, entry.name)
        if os.path.exists(destination):
            raise RuntimeError(f"Gagal rollback: nama file sudah dipakai {destination}")
        shutil.move(entry.path, destination)


def _download_snapshot_file(url_dl: str, destination: str, cookie_str: str) -> str:
    """Download satu URL ke .part lalu atomically rename ke tujuan."""
    def _get_response():
        current_url = url_dl
        for _ in range(5):
            parsed = urlsplit(current_url)
            headers = _headers(current_url, cookie_str)
            if parsed.hostname == "customhostname":
                path = parsed.path
                if not path.startswith("/lpse-prod-data/"):
                    path = "/lpse-prod-data" + path
                current_url = urlunsplit(
                    (parsed.scheme, "storage.googleapis.com", path, parsed.query, parsed.fragment)
                )
                headers = {
                    key: value
                    for key, value in headers.items()
                    if key.lower() not in {"cookie", "host"}
                }
            response = requests.get(
                current_url,
                headers=headers,
                timeout=60,
                stream=True,
                allow_redirects=False,
            )
            if response.status_code not in (301, 302, 303, 307, 308):
                return response
            location = response.headers.get("Location")
            response.close()
            if not location:
                return response
            current_url = urljoin(current_url, location)
        return requests.get(
            current_url,
            headers=_headers(current_url, cookie_str),
            timeout=60,
            stream=True,
            allow_redirects=False,
        )

    last_error = None
    partial = f"{destination}.part"
    for attempt, delay in enumerate((0.0, 0.5, 1.5), start=1):
        if delay:
            time.sleep(delay)
        response = None
        try:
            response = _get_response()
            status = int(getattr(response, "status_code", 0) or 0)
            if status in _DOWNLOAD_TRANSIENT_STATUS:
                last_error = f"HTTP {status}"
                if attempt < 3:
                    continue
                raise RuntimeError(last_error)
            if status != 200:
                raise RuntimeError(f"HTTP {status}")

            final_url = str(getattr(response, "url", url_dl) or url_dl)
            if urlsplit(final_url).path.lower().rstrip("/").endswith("/login"):
                raise RuntimeError("server mengembalikan halaman login")
            content_type = str((getattr(response, "headers", {}) or {}).get("Content-Type", ""))
            if "text/html" in content_type.lower():
                raise RuntimeError("server mengembalikan halaman HTML/login")

            with open(partial, "wb") as handle:
                for chunk in response.iter_content(chunk_size=65536):
                    if chunk:
                        handle.write(chunk)
            os.replace(partial, destination)
            return destination
        except requests.exceptions.RequestException as exc:
            last_error = str(exc)
            if attempt >= 3:
                raise RuntimeError(f"gagal setelah 3 percobaan: {last_error}") from exc
        finally:
            close = getattr(response, "close", None)
            if callable(close):
                close()
            if os.path.exists(partial):
                os.remove(partial)
    raise RuntimeError(last_error or "download gagal")


def download_all_dokumen_ppk(
    row: dict,
    snapshot: dict | None,
    cookie_str: str | None = None,
) -> dict[str, list | str]:
    """Refresh batch dokumen PPK ke ``10. Revisi Uploadan PPK``.

    File baru diunduh ke staging lebih dahulu. Folder aktif hanya diganti
    setelah seluruh file berhasil; batch lama dipindahkan ke archive sibling
    bertimestamp agar folder aktif tidak mencampur revisi.
    """
    folder_paket = _resolve_package_folder(row)
    if not folder_paket:
        return {
            "folder": "",
            "ok": [],
            "error": [
                f"Folder paket tidak ditemukan untuk {row.get('kode_paket') or row.get('nama_paket') or '-'}"
            ],
        }

    folder_tujuan = os.path.join(folder_paket, DOWNLOAD_SUBFOLDER)
    if not os.path.isdir(folder_tujuan):
        return {
            "folder": folder_tujuan,
            "ok": [],
            "error": [
                f"Folder tujuan belum diprovision saat create paket: {folder_tujuan}"
            ],
        }
    items = list(_iter_snapshot_files(snapshot))
    if not items:
        return {"folder": folder_tujuan, "archive": "", "ok": [], "error": []}

    cookie = cookie_str if cookie_str is not None else _get_cookies()
    if not cookie:
        return {
            "folder": folder_tujuan,
            "ok": [],
            "error": ["Cookie SPSE kosong — buka Brave SPSE dan login sebagai PP."],
        }

    result = {"folder": folder_tujuan, "archive": "", "ok": [], "error": []}
    staging = tempfile.mkdtemp(prefix=".ppk_revision_download_", dir=folder_paket)
    staged_files = []
    download_errors = []
    for kind, item in items:
        label = DOCUMENT_TYPES[kind]
        name = _clean_download_filename(item.get("nama"))
        url_dl = str(item.get("url_dl") or "").strip()
        if not url_dl:
            download_errors.append(f"{label}/{name}: URL download kosong")
            continue
        try:
            destination = _unique_download_path(staging, name)
            staged_files.append(_download_snapshot_file(url_dl, destination, cookie))
        except Exception as exc:
            download_errors.append(f"{label}/{name}: {exc}")

    if download_errors:
        shutil.rmtree(staging, ignore_errors=True)
        result["error"] = download_errors + [
            "Batch terbaru tidak diaktifkan; folder 10 tetap memakai batch sebelumnya."
        ]
        return result

    archive_dir = ""
    promoted = []
    try:
        archive_dir = _archive_active_revision_files(folder_paket, folder_tujuan)
        for staged_path in staged_files:
            destination = os.path.join(folder_tujuan, os.path.basename(staged_path))
            shutil.move(staged_path, destination)
            promoted.append(destination)
        result["archive"] = archive_dir
        result["ok"] = promoted
    except Exception as exc:
        for destination in reversed(promoted):
            if os.path.exists(destination):
                shutil.move(destination, os.path.join(staging, os.path.basename(destination)))
        try:
            _restore_archived_revision_files(archive_dir, folder_tujuan)
        except Exception as rollback_exc:
            exc = RuntimeError(f"{exc}; rollback batch lama gagal: {rollback_exc}")
        result["error"] = [f"Batch refresh gagal: {exc}"]
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    return result
