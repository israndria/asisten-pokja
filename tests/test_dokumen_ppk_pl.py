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
