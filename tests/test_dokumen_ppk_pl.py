from unittest.mock import patch

import dokumen_ppk_pl as engine


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
