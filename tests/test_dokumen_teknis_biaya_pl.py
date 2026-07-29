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

    def fake_download(url, dest):
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
