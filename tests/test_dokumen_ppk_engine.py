from unittest.mock import patch

import dokumen_ppk_engine as engine


class _DownloadResponse:
    status_code = 200
    headers = {}

    def iter_content(self, chunk_size=65536):
        yield b"test-content"


def test_update_download_is_grouped_by_document_type(tmp_path):
    package_dir = tmp_path / "paket"
    kak_dir = package_dir / "1. KAK & Spesifikasi Teknis"
    kak_dir.mkdir(parents=True)
    (kak_dir / "KAK lama.pdf").write_bytes(b"old")

    changed = {
        "jenis": "spek",
        "nama_lama": "KAK lama.pdf",
        "nama_baru": "KAK revisi.pdf",
        "url_dl": "https://example.test/update",
    }
    new = {
        "jenis": "spek",
        "nama": "Gambar baru.pdf",
        "url_dl": "https://example.test/new",
    }

    with (
        patch.object(engine, "_get_cookies", return_value="cookie"),
        patch.object(engine.requests, "get", return_value=_DownloadResponse()),
    ):
        result = engine.download_update_dokumen(
            "041",
            str(package_dir),
            [changed],
            [new],
            {},
            organize_by_type=True,
        )

    assert result["error"] == []
    assert (kak_dir / "1. File Update" / "KAK lama_REV1.pdf").read_bytes() == b"test-content"
    assert (kak_dir / "2. File Baru" / "Gambar baru.pdf").read_bytes() == b"test-content"
    assert (kak_dir / "KAK lama.pdf").read_bytes() == b"old"
    assert not (package_dir / "File Baru").exists()


class _FakeQuery:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def select(self, *_args):
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        return type("Result", (), {"data": [{"dokumen_snapshot": self._snapshot}]})()


class _FakeSB:
    def __init__(self, snapshot):
        self._snapshot = snapshot

    def table(self, *_args):
        return _FakeQuery(self._snapshot)


def _cek_diff(snapshot_lama, snapshot_baru):
    def fake_fetch(_id, jenis, _cookie):
        return snapshot_baru.get(jenis, [])

    with (
        patch.object(engine, "sb", return_value=_FakeSB(snapshot_lama)),
        patch.object(engine, "_get_cookies", return_value="cookie"),
        patch.object(engine, "_link_dokumen_dari_edit", return_value={}),
        patch.object(engine, "fetch_dokumen_endpoint", side_effect=fake_fetch),
    ):
        return engine.cek_update_dokumen("041")


def test_same_filename_with_new_upload_date_is_safe_update():
    old = {"spek": [{"nama": "KAK Banua.pdf", "tanggal": "1 Januari 2026", "url_dl": "old"}]}
    new = {"spek": [{"nama": "KAK Banua.pdf", "tanggal": "2 Januari 2026", "url_dl": "new"}]}

    result = _cek_diff(old, new)

    assert len(result["berubah"]) == 1
    assert result["berubah"][0]["nama_lama"] == "KAK Banua.pdf"
    assert result["baru"] == []
    assert result["perlu_verifikasi"] == []


def test_unrelated_rename_is_not_paired_by_order():
    old = {"spek": [{"nama": "KAK lama.pdf", "tanggal": "1 Januari 2026", "url_dl": "old"}]}
    new = {"spek": [{"nama": "Gambar baru.pdf", "tanggal": "2 Januari 2026", "url_dl": "new"}]}

    result = _cek_diff(old, new)

    assert result["berubah"] == []
    assert result["baru"][0]["nama"] == "Gambar baru.pdf"
    assert result["hilang"][0]["nama"] == "KAK lama.pdf"


def test_similar_rename_requires_manual_verification():
    old = {"spek": [{"nama": "KAK Banua.pdf", "tanggal": "1 Januari 2026", "url_dl": "old"}]}
    new = {"spek": [{"nama": "KAK Banua Revisi.pdf", "tanggal": "2 Januari 2026", "url_dl": "new"}]}

    result = _cek_diff(old, new)

    assert result["berubah"] == []
    assert result["baru"] == []
    assert result["hilang"] == []
    assert result["perlu_verifikasi"][0]["nama_baru"] == "KAK Banua Revisi.pdf"


def test_snapshot_merge_preserves_unresolved_old_file():
    old = {
        "spek": [
            {"nama": "KAK lama.pdf", "tanggal": "1 Januari 2026", "url_dl": "old"},
        ],
    }
    new = {
        "spek": [
            {"nama": "Gambar baru.pdf", "tanggal": "2 Januari 2026", "url_dl": "new"},
        ],
    }
    safe_new = {
        "jenis": "spek",
        "nama": "Lampiran aman.pdf",
        "tanggal": "3 Januari 2026",
        "url_dl": "safe",
    }

    merged = engine.snapshot_setelah_download_aman(old, new, [], [safe_new])

    names = {item["nama"] for item in merged["spek"]}
    assert "KAK lama.pdf" in names
    assert "Lampiran aman.pdf" in names
    assert "Gambar baru.pdf" not in names
