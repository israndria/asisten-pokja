from pathlib import Path
from types import SimpleNamespace

import requests

import dokumen_teknis_biaya_pl as downloader


class _Response:
    status_code = 200
    headers = {
        "Content-Type": "application/pdf",
        "Content-Disposition": 'attachment; filename="personel.pdf"',
        "Content-Length": "8",
    }

    def iter_content(self, chunk_size=8192):
        yield b"personel"

    def close(self):
        pass


def test_download_file_retries_transient_timeout(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(downloader.spse_browser, "get_spse_cookies", lambda: "cookie")

    def fake_get(*args, **kwargs):
        calls.append((args, kwargs))
        if len(calls) == 1:
            raise requests.Timeout("temporary")
        return _Response()

    monkeypatch.setattr(downloader.requests, "get", fake_get)

    result = downloader._download_file(
        "https://spse.inaproc.id/tapinkab/dlsec/test",
        str(tmp_path / "fallback.pdf"),
    )

    assert result["ok"] is True
    assert result["attempts"] == 2
    assert len(calls) == 2
    assert (tmp_path / "personel.pdf").read_bytes() == b"personel"
    assert not list(tmp_path.glob("*.part"))


def test_download_file_accepts_identical_existing_when_drive_blocks_replace(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(downloader.spse_browser, "get_spse_cookies", lambda: "cookie")
    existing = tmp_path / "personel.pdf"
    existing.write_bytes(b"personel")
    monkeypatch.setattr(downloader.requests, "get", lambda *a, **k: _Response())
    monkeypatch.setattr(
        downloader.os,
        "replace",
        lambda *args: (_ for _ in ()).throw(PermissionError("drive lock")),
    )

    result = downloader._download_file(
        "https://spse.inaproc.id/tapinkab/dlsec/test",
        str(tmp_path / "fallback.pdf"),
    )

    assert result["ok"] is True
    assert result["path"] == str(existing)
    assert existing.read_bytes() == b"personel"
    assert not list(tmp_path.glob("*.part"))


def test_partial_download_is_failure_and_writes_marker(tmp_path, monkeypatch):
    monkeypatch.setattr(
        downloader,
        "fetch_dokumen_teknis_biaya_pl",
        lambda _id: {
            "ok": True,
            "dokumen": [
                {"nama": "proposal.pdf", "url": "https://x/proposal"},
                {"nama": "personel.pdf", "url": "https://x/personel"},
            ],
            "pesan": "2 dokumen",
        },
    )

    def fake_download(url, dest, **kwargs):
        if url.endswith("personel"):
            return {
                "ok": False,
                "pesan": "timeout setelah 3 percobaan",
                "path": "",
                "attempts": 3,
            }
        Path(dest).write_bytes(b"%PDF-1.4\n")
        return {
            "ok": True,
            "pesan": "OK",
            "path": dest,
            "ukuran": 9,
            "attempts": 1,
        }

    monkeypatch.setattr(downloader, "_download_file", fake_download)
    monkeypatch.setattr(downloader, "_gabung_pdf", lambda *args, **kwargs: True)
    monkeypatch.setattr(downloader.spse_browser, "get_spse_cookies", lambda: "cookie")

    result = downloader.download_teknis_biaya_peserta(
        "participant-id",
        "CV UJI",
        str(tmp_path),
        1,
    )

    marker = (
        tmp_path
        / "9. Dokumen Teknis Biaya"
        / "1. CV UJI"
        / "_DOWNLOAD_TIDAK_LENGKAP.txt"
    )
    assert result["ok"] is False
    assert result["files_expected"] == 2
    assert result["files_downloaded"] == 1
    assert result["failed_documents"][0]["nama"] == "personel.pdf"
    assert marker.is_file()
    assert "personel.pdf" in marker.read_text(encoding="utf-8")


def test_empty_document_list_is_not_complete(tmp_path, monkeypatch):
    monkeypatch.setattr(
        downloader,
        "fetch_dokumen_teknis_biaya_pl",
        lambda _id: {"ok": True, "dokumen": [], "pesan": "OK"},
    )
    monkeypatch.setattr(downloader.spse_browser, "get_spse_cookies", lambda: "cookie")

    result = downloader.download_teknis_biaya_peserta(
        "participant-id",
        "CV UJI",
        str(tmp_path),
        1,
    )

    marker = (
        tmp_path
        / "9. Dokumen Teknis Biaya"
        / "1. CV UJI"
        / "_DOWNLOAD_TIDAK_LENGKAP.txt"
    )
    assert result["ok"] is False
    assert result["files_expected"] == 0
    assert result["files_downloaded"] == 0
    assert marker.is_file()


def test_participant_download_reuses_http_and_office_resources(tmp_path, monkeypatch):
    class _Session:
        closed = False

        def close(self):
            self.closed = True

    class _Office:
        closed = False

        def close(self):
            self.closed = True

    session = _Session()
    office = _Office()
    download_calls = []

    monkeypatch.setattr(downloader.requests, "Session", lambda: session)
    monkeypatch.setattr(downloader, "_OfficeConversionSession", lambda: office)
    monkeypatch.setattr(downloader.spse_browser, "get_spse_cookies", lambda: "cookie-once")
    monkeypatch.setattr(
        downloader,
        "fetch_dokumen_teknis_biaya_pl",
        lambda _id: {
            "ok": True,
            "dokumen": [
                {"nama": "teknis.pdf", "url": "https://x/teknis"},
                {"nama": "harga.pdf", "url": "https://x/harga"},
            ],
            "pesan": "2 dokumen",
        },
    )

    def fake_download(url, dest, **kwargs):
        download_calls.append((url, dest, kwargs))
        Path(dest).write_bytes(b"%PDF-1.4\n")
        return {"ok": True, "pesan": "OK", "path": dest, "ukuran": 9, "attempts": 1}

    monkeypatch.setattr(downloader, "_download_file", fake_download)
    monkeypatch.setattr(downloader, "_gabung_pdf", lambda *args, **kwargs: True)

    result = downloader.download_teknis_biaya_peserta(
        "participant-id",
        "CV UJI",
        str(tmp_path),
        1,
    )

    assert result["ok"] is True
    assert len(download_calls) == 2
    assert all(call[2]["http_session"] is session for call in download_calls)
    assert all(call[2]["cookie_str"] == "cookie-once" for call in download_calls)
    assert session.closed is True
    assert office.closed is True


def test_nested_archive_pdfs_are_included_in_merge(tmp_path, monkeypatch):
    nested_pdf = tmp_path / "1. CV UJI" / "lampiran" / "dokumen.pdf"
    merged_inputs = []

    monkeypatch.setattr(downloader.spse_browser, "get_spse_cookies", lambda: "cookie")
    monkeypatch.setattr(
        downloader,
        "fetch_dokumen_teknis_biaya_pl",
        lambda _id: {
            "ok": True,
            "dokumen": [{"nama": "lampiran.zip", "url": "https://x/lampiran"}],
            "pesan": "1 dokumen",
        },
    )

    def fake_download(url, dest, **kwargs):
        return {"ok": True, "pesan": "OK", "path": dest, "ukuran": 9, "attempts": 1}

    def fake_extract(archive, dest_folder, log_cb=None):
        nested_pdf.parent.mkdir(parents=True, exist_ok=True)
        nested_pdf.write_bytes(b"%PDF-1.4\n")
        return [str(nested_pdf)]

    def fake_merge(output_path, file_list, progress_cb=None):
        merged_inputs.extend(file_list)
        Path(output_path).write_bytes(b"merged")
        return True

    monkeypatch.setattr(downloader, "_download_file", fake_download)
    monkeypatch.setattr(downloader, "_ekstrak_arsip", fake_extract)
    monkeypatch.setattr(downloader, "_gabung_pdf", fake_merge)

    result = downloader.download_teknis_biaya_peserta(
        "participant-id",
        "CV UJI",
        str(tmp_path),
        1,
    )

    assert result["ok"] is True
    assert result["files_downloaded"] == 1
    assert merged_inputs == [str(nested_pdf)]
