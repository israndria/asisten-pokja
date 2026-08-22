"""Regression bounded untuk status bulk PL; tanpa SPSE, network, atau COM."""

from types import SimpleNamespace

import pytest
import requests

import pl_engine
import pl_engine_plpk
import ppk_upload_engine
import spse_browser
from pl_ui_helpers import (
    _copy_pl_evaluator_files,
    _engine_for_jenis_pl,
    _fmt_elapsed,
    _pl_download_success,
    _pl_io_success,
)
from pl_engine import _safe_download_name_for_folder


def test_ubah_metode_cdp_includes_submit_field_and_retries_transient_503(monkeypatch):
    calls = []

    def fake_cdp_eval(js, timeout=20):
        calls.append((js, timeout))
        return True, {"ok": False, "msg": "POST status 503 type basic"}, None

    monkeypatch.setattr(ppk_upload_engine, "_cdp_eval", fake_cdp_eval)
    monkeypatch.setattr(spse_browser.time, "sleep", lambda _seconds: None)

    result = spse_browser.ubah_metode_via_playwright(
        "X", 5, 17, "https://spse.test/tapinkab/"
    )

    assert result == "Gagal: POST status 503 type basic"
    assert len(calls) == 3
    assert all("new FormData()" in js and "simpan" in js for js, _timeout in calls)


def test_bulk_worker_resolves_engine_by_family():
    assert _engine_for_jenis_pl("PK").__name__ == "pl_engine_plpk"
    assert _engine_for_jenis_pl("JKK").__name__ == "pl_engine"
    assert _engine_for_jenis_pl("").__name__ == "pl_engine"


def test_spse_retry_call_retries_transient_connection_error():
    calls = []

    def flaky_call():
        calls.append(len(calls) + 1)
        if len(calls) < 3:
            raise requests.exceptions.ConnectionError("reset oleh server")
        return "OK"

    result = pl_engine._spse_retry_call(
        flaky_call,
        requests,
        delays=(0, 0, 0),
    )

    assert result == "OK"
    assert calls == [1, 2, 3]


def test_pk_download_retries_broken_stream_and_removes_partial_file(monkeypatch, tmp_path):
    class _Response:
        def __init__(self, url, text="", headers=None, chunks=()):
            self.url = url
            self.status_code = 200
            self.text = text
            self.headers = headers or {}
            self._chunks = chunks

        def raise_for_status(self):
            pass

        def iter_content(self, _chunk_size):
            for chunk in self._chunks:
                if isinstance(chunk, BaseException):
                    raise chunk
                yield chunk

        def close(self):
            pass

    stream_calls = []

    def fake_get(url, **_kwargs):
        if "/dl/" in url:
            stream_calls.append(url)
            chunks = (
                (b"partial", requests.exceptions.ChunkedEncodingError("reset"))
                if len(stream_calls) == 1
                else (b"complete",)
            )
            return _Response(
                url,
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": 'attachment; filename="dokumen.pdf"',
                },
                chunks=chunks,
            )
        html = '<a href="/tapinkab/dl/test">dokumen.pdf</a>' if url.endswith("/spek") else "<html></html>"
        return _Response(url, text=html)

    monkeypatch.setattr(requests, "get", fake_get)
    result = pl_engine_plpk.download_dokumen_paket_pl(
        "X", str(tmp_path), cookie_str="SPSE_SESSION=test", skip_merge=True,
    )

    assert result["error"] == []
    assert len(result["ok"]) == 1
    output = tmp_path / "1. KAK & Spesifikasi Teknis" / "dokumen.pdf"
    assert output.read_bytes() == b"complete"
    assert not list(output.parent.glob("*.part"))
    assert len(stream_calls) == 2


def test_download_filename_is_bounded_for_windows_path_limit(tmp_path):
    folder = tmp_path / ("paket-" + "x" * 80)
    folder.mkdir()
    original = "gambar " + "Pengaspalan Jalan Samping Gedung Ruhuy Rahayu " * 4 + ".pdf"

    safe = _safe_download_name_for_folder(str(folder), original)

    assert safe.endswith(".pdf")
    assert safe != original
    assert len(str(folder / safe)) <= 240
    assert len(safe) < len(original)


def test_download_filename_reports_folder_path_without_budget(tmp_path):
    folder = tmp_path / ("paket-" + "x" * 80)
    folder.mkdir()

    with pytest.raises(OSError, match="Folder path terlalu panjang"):
        _safe_download_name_for_folder(str(folder), "dokumen.pdf", limit=len(str(folder)) + 1)


def test_elapsed_uses_seconds_suffix_not_ambiguous_day_suffix():
    assert _fmt_elapsed(8 * 60 + 21) == "8m 21s"


def test_io_false_when_setup_created_but_output_missing():
    result = {"setup_ok": True, "output_ok": False, "download_ok": True, "hps_ok": True}
    assert _pl_io_success(result, download_requested=True) is False


def test_io_false_when_download_has_no_successful_file():
    result = {"setup_ok": True, "output_ok": True, "download_ok": False, "hps_ok": True}
    assert _pl_io_success(result, download_requested=True) is False


def test_io_true_only_after_requested_phases_are_valid():
    result = {"setup_ok": True, "output_ok": True, "download_ok": True, "hps_ok": True}
    assert _pl_io_success(result, download_requested=True) is True


def test_io_does_not_require_download_when_phase_skipped():
    result = {"setup_ok": True, "output_ok": True, "download_ok": True, "hps_ok": True}
    assert _pl_io_success(result, download_requested=False) is True


def test_io_false_when_hps_phase_failed():
    result = {"setup_ok": True, "output_ok": True, "download_ok": True, "hps_ok": False}
    assert _pl_io_success(result, download_requested=True) is False


def test_pl_evaluator_copy_puts_canonical_review_sops_in_draft_folder(tmp_path):
    sop_root = tmp_path / "_SOP Evaluator"
    sop_root.mkdir()
    for filename in (
        "SOP_ISI_REVIU_DPP_CORE.md",
        "SOP_ISI_REVIU_DPP_DOMAIN.md",
        "SOP_REKONSILIASI_XML_DOKUMEN_PPK_CORE.md",
        "SOP_REKONSILIASI_XML_DOKUMEN_PPK_PLPK.md",
        "PROTOKOL_EVALUASI_AI.md",
        "EVALUATOR_KUALIFIKASI_PL_JKK_LUMSUM.md",
        "EVALUATOR_KUALIFIKASI_PL_JKK_ADMIN_TEKNIS.md",
    ):
        (sop_root / filename).write_text(filename, encoding="utf-8")

    target = tmp_path / "paket"
    copied = _copy_pl_evaluator_files(str(target), str(tmp_path), "JKK")

    draft = target / "0. Draft Dokumen PPK"
    evaluator = target / "5. Evaluator Kualifikasi & Teknis"
    assert (draft / "SOP_ISI_REVIU_DPP_CORE.md").read_text(encoding="utf-8")
    assert (draft / "SOP_ISI_REVIU_DPP_DOMAIN.md").read_text(encoding="utf-8")
    assert (draft / "SOP_REKONSILIASI_XML_DOKUMEN_PPK_CORE.md").read_text(encoding="utf-8")
    assert (draft / "SOP_REKONSILIASI_XML_DOKUMEN_PPK_PLPK.md").read_text(encoding="utf-8")
    assert (evaluator / "PROTOKOL_EVALUASI_AI.md").exists()
    assert "SOP_ISI_REVIU_DPP_CORE.md" in copied
    assert "SOP_ISI_REVIU_DPP_DOMAIN.md" in copied
    assert "SOP_REKONSILIASI_XML_DOKUMEN_PPK_CORE.md" in copied
    assert "SOP_REKONSILIASI_XML_DOKUMEN_PPK_PLPK.md" in copied


@pytest.mark.parametrize("engine", [pl_engine, pl_engine_plpk])
def test_revision_folder_is_provisioned_idempotently_for_both_pl_families(tmp_path, engine):
    package_dir = tmp_path / "paket"
    package_dir.mkdir()

    first = engine.buat_subfolder_dokumen(str(package_dir))
    second = engine.buat_subfolder_dokumen(str(package_dir))

    revision = "10. Revisi Uploadan PPK"
    assert (package_dir / revision).is_dir()
    assert revision in first
    assert revision not in second


def test_download_allows_optional_nota_dinas_failure_when_files_exist():
    assert _pl_download_success(
        ["1. KAK.pdf"], ["Nota Dinas PPK: sesi SPSE tidak valid"]
    ) is True


def test_download_keeps_required_endpoint_failure_fatal():
    assert _pl_download_success(
        ["1. KAK.pdf"], ["KAK & Personil: HTTP 403"]
    ) is False


class _FakeSupabaseQuery:
    def __init__(self, data):
        self._data = data

    def update(self, _payload):
        return self

    def eq(self, *_args):
        return self

    def select(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=self._data)


class _FakeSupabase:
    def __init__(self, data):
        self._data = data

    def table(self, _name):
        return _FakeSupabaseQuery(self._data)


@pytest.mark.parametrize("engine", [pl_engine, pl_engine_plpk])
@pytest.mark.parametrize("rows, expected", [([], False), ([{"kode_paket": "X"}], True)])
def test_tandai_folder_dibuat_verifies_updated_row(monkeypatch, engine, rows, expected):
    monkeypatch.setattr(engine, "_sb", lambda: _FakeSupabase(rows))
    result = engine.tandai_folder_dibuat("X")
    assert result.get("ok") is expected


@pytest.mark.parametrize("engine", [pl_engine, pl_engine_plpk])
def test_download_http_403_is_recorded_as_error(monkeypatch, tmp_path, engine):
    class _ForbiddenResponse:
        status_code = 403
        headers = {}
        text = "Forbidden"

        def close(self):
            pass

        def raise_for_status(self):
            raise RuntimeError("403 Forbidden")

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _ForbiddenResponse())
    result = engine.download_dokumen_paket_pl(
        "X", str(tmp_path), cookie_str="SPSE_SESSION=test"
    )
    http_errors = [item for item in result["error"] if "HTTP 403" in item]
    assert len(http_errors) == 5


@pytest.mark.parametrize("engine", [pl_engine, pl_engine_plpk])
def test_download_edit_page_login_link_does_not_hide_nota_dinas(monkeypatch, tmp_path, engine):
    class _Response:
        def __init__(self, url, text="", headers=None, chunks=()):
            self.url = url
            self.status_code = 200
            self.text = text
            self.headers = headers or {}
            self._chunks = chunks

        def raise_for_status(self):
            pass

        def iter_content(self, _chunk_size):
            return iter(self._chunks)

        def close(self):
            pass

    def fake_get(url, **_kwargs):
        if "/dl/" in url:
            return _Response(
                url,
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": 'attachment; filename="8. ND PPK.pdf"',
                },
                chunks=(b"%PDF-1.4",),
            )
        html = (
            '<a href="/tapinkab/login/homeotp">Enable 2FA</a>'
            '<a href="/tapinkab/dl/nota-dinas">8. ND PPK.pdf</a>'
            if url.endswith("/nontender/X/edit")
            else "<html></html>"
        )
        return _Response(url, text=html)

    monkeypatch.setattr(requests, "get", fake_get)
    result = engine.download_dokumen_paket_pl(
        "X", str(tmp_path), cookie_str="SPSE_SESSION=test", skip_merge=True
    )

    assert any(path.endswith("8. ND PPK.pdf") for path in result["ok"])
    assert not any("server mengembalikan halaman login" in error for error in result["error"])


@pytest.mark.parametrize("engine", [pl_engine, pl_engine_plpk])
def test_download_shortens_long_content_disposition_filename(monkeypatch, tmp_path, engine):
    long_name = "gambar " + "Perbaikan Jalan Perumahan Desa Tapin Tengah " * 5 + ".pdf"
    folder_name = "p" * max(1, 180 - len(str(tmp_path)) - 1)
    target = tmp_path / folder_name
    target.mkdir()

    class _Response:
        def __init__(self, url, text="", headers=None):
            self.url = url
            self.status_code = 200
            self.text = text
            self.headers = headers or {}

        def raise_for_status(self):
            pass

        def iter_content(self, _chunk_size):
            return iter((b"%PDF-1.4",))

        def close(self):
            pass

    def fake_get(url, **_kwargs):
        if "/dl/" in url:
            return _Response(
                url,
                headers={
                    "Content-Type": "application/pdf",
                    "Content-Disposition": f'attachment; filename="{long_name}"',
                },
            )
        if url.endswith("/dokumennontender/X/spek"):
            return _Response(
                url,
                text=(
                    f'<a href="/tapinkab/dl/long-1">{long_name}</a>'
                    f'<a href="/tapinkab/dl/long-2">{long_name}</a>'
                ),
            )
        return _Response(url, text="<html></html>")

    monkeypatch.setattr(requests, "get", fake_get)
    result = engine.download_dokumen_paket_pl(
        "X", str(target), cookie_str="SPSE_SESSION=test", skip_merge=True
    )

    assert result["error"] == []
    assert len(result["ok"]) == 2
    assert len({path for path in result["ok"]}) == 2
    assert all(len(path) <= 240 for path in result["ok"])


def test_pk_download_force_clean_is_scoped_to_document_subfolders(monkeypatch, tmp_path):
    class _EmptyEndpointResponse:
        status_code = 200
        headers = {}
        text = "<html><body>No documents</body></html>"

        def raise_for_status(self):
            pass

        def close(self):
            pass

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _EmptyEndpointResponse())

    protected = [
        tmp_path / "root-template.docx",
        tmp_path / "0. Draft Dokumen PPK" / "draft.pdf",
    ]
    for path in protected:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("keep", encoding="utf-8")

    for subfolder in set(pl_engine_plpk.SUBFOLDER_DOK_PPK.values()):
        path = tmp_path / subfolder
        path.mkdir(parents=True, exist_ok=True)
        (path / "old.pdf").write_text("remove", encoding="utf-8")

    result = pl_engine_plpk.download_dokumen_paket_pl(
        "X", str(tmp_path), cookie_str="SPSE_SESSION=test", force_clean=True,
        skip_merge=True,
    )

    assert result["ok"] == []
    assert result["error"] == []
    assert all(path.exists() for path in protected)
    assert all(
        not (tmp_path / subfolder / "old.pdf").exists()
        for subfolder in set(pl_engine_plpk.SUBFOLDER_DOK_PPK.values())
    )


def test_spse_viewdraft_location_and_funding_are_preserved(monkeypatch):
    class _ViewResponse:
        status_code = 200
        text = """
        <table>
          <tr><td>Lokasi Pekerjaan</td><td>Kecamatan Binuang - Tapin (Kab.)</td></tr>
          <tr><td>Sumber Dana</td><td>APBDP</td></tr>
        </table>
        """

    monkeypatch.setattr(requests, "get", lambda *args, **kwargs: _ViewResponse())
    result = pl_engine._scrape_viewdraftpl("X", {"Cookie": "session"}, "https://spse.test/")
    assert result == {
        "lokasi": "Kecamatan Binuang - Tapin (Kab.)",
        "sumber_anggaran": "APBDP",
    }


def test_pk_merged_draft_is_written_under_draft_dokumen_ppk(monkeypatch, tmp_path):
    class _SingleRow:
        data = {"nama_paket": "Paket Uji"}

    class _Query:
        def select(self, *_args):
            return self

        def eq(self, *_args):
            return self

        def maybe_single(self):
            return self

        def execute(self):
            return _SingleRow()

    class _FakeSB:
        def table(self, _name):
            return _Query()

    import inbox_engine

    monkeypatch.setattr(pl_engine_plpk, "_sb", lambda: _FakeSB())
    monkeypatch.setattr(
        inbox_engine,
        "_gabung_pdf_draft",
        lambda path, _ordered, _progress=None: path,
    )

    result = pl_engine_plpk.gabung_draft_pl("X", str(tmp_path), [])

    assert result == str(tmp_path / "0. Draft Dokumen PPK" / "Draft_PL_Paket Uji.pdf")
