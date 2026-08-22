from pathlib import Path
from unittest.mock import patch

import dokumen_ppk_pl as engine
import dokumen_ppk_pl_ui as ui
import pl_data_ui


class _ExpanderGuard:
    def __init__(self, owner, label):
        self.owner = owner
        self.label = label

    def __enter__(self):
        if self.owner.depth:
            raise AssertionError(f"nested expander: {self.label}")
        self.owner.depth += 1
        return self

    def __exit__(self, *_args):
        self.owner.depth -= 1


class _FakeStreamlit:
    def __init__(self):
        self.depth = 0

    def expander(self, label, **_kwargs):
        return _ExpanderGuard(self, label)

    def __getattr__(self, _name):
        return lambda *_args, **_kwargs: None


def test_render_result_does_not_nest_expander_inside_package_card():
    st = _FakeStreamlit()
    result = {"baseline_created": True, "snapshot_baru": {"spek": []}}

    with st.expander("📄 Paket"):
        ui._render_result(st, engine, {"kode_paket": "123"}, result, "jkk", {})


def test_monitor_excludes_packages_already_announced():
    rows = [
        {"kode_paket": "34", "status": "draft", "tahap_spse": ""},
        {"kode_paket": "71", "status": "draft", "tahap_spse": ""},
    ]
    session_status = {"34": {"status": "sudah diumumkan"}}

    filtered = ui._filter_unannounced_rows(
        rows,
        session_status,
        pl_data_ui.is_paket_sudah_diumumkan,
    )

    assert [row["kode_paket"] for row in filtered] == ["71"]


def test_same_name_and_date_is_unchanged():
    snapshot = {
        "spek": [{"nama": "KAK.pdf", "tanggal": "20 Agustus 2026", "url_dl": "old"}],
    }

    result = engine.compare_snapshots(snapshot, {
        "spek": [{"nama": "KAK.pdf", "tanggal": "20 Agustus 2026", "url_dl": "new"}],
    })

    assert result == {"berubah": [], "baru": [], "perlu_verifikasi": [], "hilang": []}


def test_same_name_with_new_upload_date_is_changed():
    result = engine.compare_snapshots(
        {"spek": [{"nama": "KAK.pdf", "tanggal": "20 Agustus 2026"}]},
        {"spek": [{"nama": "KAK.pdf", "tanggal": "21 Agustus 2026"}]},
    )

    assert len(result["berubah"]) == 1
    assert result["berubah"][0]["tanggal_baru"] == "21 Agustus 2026"
    assert result["baru"] == []
    assert result["hilang"] == []


def test_new_and_missing_files_are_not_paired_by_position():
    result = engine.compare_snapshots(
        {"spek": [{"nama": "KAK lama.pdf", "tanggal": "20 Agustus 2026"}]},
        {"spek": [{"nama": "Gambar baru.pdf", "tanggal": "21 Agustus 2026"}]},
    )

    assert result["baru"][0]["nama"] == "Gambar baru.pdf"
    assert result["hilang"][0]["nama"] == "KAK lama.pdf"
    assert result["perlu_verifikasi"] == []


def test_similar_rename_is_held_for_manual_verification():
    result = engine.compare_snapshots(
        {"spek": [{"nama": "KAK Banua.pdf", "tanggal": "20 Agustus 2026"}]},
        {"spek": [{"nama": "KAK Banua Revisi.pdf", "tanggal": "21 Agustus 2026"}]},
    )

    assert result["baru"] == []
    assert result["hilang"] == []
    assert result["perlu_verifikasi"][0]["nama_baru"] == "KAK Banua Revisi.pdf"


def test_file_table_reads_name_date_and_download_link():
    html = """
    <table id="files"><tbody><tr>
      <td><a href="/tapinkab/dl/abc">KAK.pdf - 10 KB</a></td>
      <td>20 Agustus 2026</td>
    </tr></tbody></table>
    """

    assert engine._parse_file_table(html) == [{
        "nama": "KAK.pdf",
        "tanggal": "20 Agustus 2026",
        "url_dl": "https://spse.inaproc.id/tapinkab/dl/abc",
    }]


def test_save_snapshot_preserves_existing_data_snapshot_keys():
    payloads = []

    class Query:
        def update(self, payload):
            payloads.append(payload)
            return self

        def eq(self, *_args):
            return self

        def execute(self):
            return type("Result", (), {"data": []})()

    class Client:
        def table(self, _name):
            return Query()

    existing = {"r3": {"hps": "100"}, "r4": {"nama": "tetap"}}
    with (
        patch.object(engine, "_read_data_snapshot", return_value=existing),
        patch.object(engine, "_sb", return_value=Client()),
    ):
        engine.save_snapshot("123", "JKK", {"spek": []})

    saved = payloads[0]["data_snapshot"]
    assert saved["r3"] == existing["r3"]
    assert saved["r4"] == existing["r4"]
    assert saved[engine.SNAPSHOT_NAMESPACE]["paket"]["123"]["jenis_pl"] == "JKK"


class _SnapshotDownloadResponse:
    status_code = 200
    headers = {}

    def __init__(self, url, content=b"downloaded"):
        self.url = url
        self.content = content

    def iter_content(self, chunk_size=65536):
        yield self.content

    def close(self):
        pass


def test_download_all_snapshot_categories_to_revision_folder(monkeypatch, tmp_path):
    package_dir = tmp_path / "35. PLPK - Paket Uji"
    package_dir.mkdir()
    (package_dir / engine.DOWNLOAD_SUBFOLDER).mkdir()
    monkeypatch.setattr(engine, "_resolve_package_folder", lambda _row: str(package_dir))
    requested = []

    def fake_get(url, **_kwargs):
        requested.append(url)
        return _SnapshotDownloadResponse(url)

    monkeypatch.setattr(engine.requests, "get", fake_get)
    snapshot = {
        kind: [{"nama": f"{kind}.pdf", "tanggal": "22 Agustus 2026", "url_dl": f"https://x/{kind}"}]
        for kind in engine.DOCUMENT_TYPES
    }

    result = engine.download_all_dokumen_ppk(
        {"kode_paket": "35", "jenis_pl": "PK"}, snapshot, cookie_str="cookie"
    )

    target = package_dir / engine.DOWNLOAD_SUBFOLDER
    assert result["error"] == []
    assert result["folder"] == str(target)
    assert target.is_dir()
    assert {Path(path).name for path in result["ok"]} == {
        f"{kind}.pdf" for kind in engine.DOCUMENT_TYPES
    }
    assert requested == [f"https://x/{kind}" for kind in engine.DOCUMENT_TYPES]


def test_download_failure_removes_partial_file(monkeypatch, tmp_path):
    package_dir = tmp_path / "paket"
    package_dir.mkdir()
    (package_dir / engine.DOWNLOAD_SUBFOLDER).mkdir()
    monkeypatch.setattr(engine, "_resolve_package_folder", lambda _row: str(package_dir))

    class _BrokenResponse(_SnapshotDownloadResponse):
        def iter_content(self, chunk_size=65536):
            yield b"partial"
            raise RuntimeError("stream putus")

    monkeypatch.setattr(
        engine.requests,
        "get",
        lambda url, **_kwargs: _BrokenResponse(url),
    )
    result = engine.download_all_dokumen_ppk(
        {"kode_paket": "35", "jenis_pl": "PK"},
        {"spek": [{"nama": "KAK.pdf", "url_dl": "https://x/kak"}]},
        cookie_str="cookie",
    )

    target = package_dir / engine.DOWNLOAD_SUBFOLDER
    assert result["ok"] == []
    assert result["error"]
    assert not list(target.glob("*.part"))
    assert not (target / "KAK.pdf").exists()


def test_download_duplicate_names_get_unique_suffix(monkeypatch, tmp_path):
    package_dir = tmp_path / "paket"
    package_dir.mkdir()
    (package_dir / engine.DOWNLOAD_SUBFOLDER).mkdir()
    monkeypatch.setattr(engine, "_resolve_package_folder", lambda _row: str(package_dir))
    monkeypatch.setattr(
        engine.requests,
        "get",
        lambda url, **_kwargs: _SnapshotDownloadResponse(url),
    )
    snapshot = {
        "spek": [{"nama": "dokumen.pdf", "url_dl": "https://x/spek"}],
        "docsskk": [{"nama": "dokumen.pdf", "url_dl": "https://x/docsskk"}],
    }

    result = engine.download_all_dokumen_ppk(
        {"kode_paket": "35", "jenis_pl": "PK"}, snapshot, cookie_str="cookie"
    )

    names = {Path(path).name for path in result["ok"]}
    assert names == {"dokumen.pdf", "dokumen_2.pdf"}
    assert (package_dir / engine.DOWNLOAD_SUBFOLDER / "dokumen.pdf").read_bytes() == b"downloaded"
    assert (package_dir / engine.DOWNLOAD_SUBFOLDER / "dokumen_2.pdf").read_bytes() == b"downloaded"


def test_refresh_archives_old_batch_and_replaces_active_folder(monkeypatch, tmp_path):
    package_dir = tmp_path / "paket"
    package_dir.mkdir()
    target = package_dir / engine.DOWNLOAD_SUBFOLDER
    target.mkdir()
    (target / "revisi-lama.pdf").write_bytes(b"old")
    monkeypatch.setattr(engine, "_resolve_package_folder", lambda _row: str(package_dir))
    monkeypatch.setattr(
        engine.requests,
        "get",
        lambda url, **_kwargs: _SnapshotDownloadResponse(url, b"new"),
    )

    result = engine.download_all_dokumen_ppk(
        {"kode_paket": "35", "jenis_pl": "PK"},
        {"spek": [{"nama": "revisi-baru.pdf", "url_dl": "https://x/new"}]},
        cookie_str="cookie",
    )

    assert result["error"] == []
    assert result["archive"]
    assert {path.name for path in target.iterdir()} == {"revisi-baru.pdf"}
    archive = Path(result["archive"])
    assert archive.parent.name == engine.DOWNLOAD_ARCHIVE_SUBFOLDER
    assert (archive / "revisi-lama.pdf").read_bytes() == b"old"


def test_refresh_failure_keeps_previous_active_batch(monkeypatch, tmp_path):
    package_dir = tmp_path / "paket"
    package_dir.mkdir()
    target = package_dir / engine.DOWNLOAD_SUBFOLDER
    target.mkdir()
    old_file = target / "revisi-lama.pdf"
    old_file.write_bytes(b"old")
    monkeypatch.setattr(engine, "_resolve_package_folder", lambda _row: str(package_dir))

    class _BrokenResponse(_SnapshotDownloadResponse):
        def iter_content(self, chunk_size=65536):
            yield b"partial"
            raise RuntimeError("stream putus")

    monkeypatch.setattr(
        engine.requests,
        "get",
        lambda url, **_kwargs: _BrokenResponse(url),
    )
    result = engine.download_all_dokumen_ppk(
        {"kode_paket": "35", "jenis_pl": "PK"},
        {"spek": [{"nama": "revisi-baru.pdf", "url_dl": "https://x/new"}]},
        cookie_str="cookie",
    )

    assert result["ok"] == []
    assert result["archive"] == ""
    assert result["error"]
    assert old_file.read_bytes() == b"old"
    assert not list(package_dir.glob(".ppk_revision_download_*"))
    assert not list(package_dir.glob(f"{engine.DOWNLOAD_ARCHIVE_SUBFOLDER}/*"))


def test_download_does_not_create_missing_revision_folder(monkeypatch, tmp_path):
    package_dir = tmp_path / "paket"
    package_dir.mkdir()
    monkeypatch.setattr(engine, "_resolve_package_folder", lambda _row: str(package_dir))

    result = engine.download_all_dokumen_ppk(
        {"kode_paket": "35", "jenis_pl": "PK"},
        {"spek": [{"nama": "KAK.pdf", "url_dl": "https://x/kak"}]},
        cookie_str="cookie",
    )

    target = package_dir / engine.DOWNLOAD_SUBFOLDER
    assert result["ok"] == []
    assert result["error"]
    assert not target.exists()
