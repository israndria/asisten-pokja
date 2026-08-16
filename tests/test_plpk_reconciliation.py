"""Regression tests untuk snapshot SPSE PK dan gate SKP."""

from cek_penyedia_engine import check_selected_providers, search_provider, summarize_provider_rows
from pl_engine import is_paket_berjalan, is_paket_ditarik
from pl_engine_plpk import _kode_live_dan_stale


def test_snapshot_invalid_never_marks_packages_stale():
    existing = [{"kode_paket": "100"}, {"kode_paket": "200"}]
    stale, valid = _kode_live_dan_stale(
        existing,
        {"100"},
        snapshot_valid=False,
    )
    assert stale == []
    assert valid is False


def test_snapshot_marks_only_missing_pk_codes_stale():
    existing = [{"kode_paket": "100"}, {"kode_paket": "200"}]
    stale, valid = _kode_live_dan_stale(
        existing,
        {"100", "300"},
        snapshot_valid=True,
    )
    assert stale == ["200"]
    assert valid is True


def test_withdrawn_row_is_hidden_from_operational_gate():
    assert is_paket_ditarik({"status": "ditarik_spse"}) is True
    assert is_paket_berjalan({"status": "ditarik_spse"}) is False
    assert is_paket_berjalan({"status": "berjalan"}) is True


def test_skp_counts_only_winner_running_not_participant():
    rows = [
        {
            "source": "Tender",
            "kode_tender": "T1",
            "nama_peserta": "CV. A",
            "npwp": "123",
            "is_pemenang": True,
            "is_berjalan": True,
            "is_pemenang_berjalan": True,
        },
        {
            "source": "Tender",
            "kode_tender": "T2",
            "nama_peserta": "CV. A",
            "npwp": "123",
            "is_pemenang": False,
            "is_berjalan": True,
            "is_pemenang_berjalan": False,
        },
    ]
    summary = summarize_provider_rows(rows)[0]
    assert summary["paket_dimenangkan"] == 1
    assert summary["peserta_bukan_pemenang"] == 1
    assert summary["skp_berjalan"] == 1


class _FakeQuery:
    def __init__(self, rows):
        self.rows = rows

    def select(self, _fields):
        return self

    def ilike(self, field, pattern):
        needle = pattern.strip("%").lower()
        self.rows = [row for row in self.rows if needle in str(row.get(field) or "").lower()]
        return self

    def limit(self, _count):
        return self

    def in_(self, field, values):
        self.rows = [row for row in self.rows if str(row.get(field)) in {str(v) for v in values}]
        return self

    def execute(self):
        return type("Response", (), {"data": self.rows})()


class _FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return _FakeQuery([dict(row) for row in self.tables.get(name, [])])


def test_selected_provider_gate_projects_new_package_against_limit():
    provider_rows = [
        {
            "kode_tender": f"T{i}",
            "urutan": i,
            "nama_peserta": "CV. A",
            "npwp": "1234567890123456",
            "is_pemenang": True,
        }
        for i in range(1, 6)
    ]
    tender_rows = [
        {
            "kode_tender": f"T{i}",
            "nama_paket": f"Paket {i}",
            "instansi": "Tapin",
            "tahapan": "Evaluasi",
            "jenis_pengadaan": "Pekerjaan Konstruksi",
        }
        for i in range(1, 6)
    ]
    fake = _FakeSupabase({"tender_peserta": provider_rows, "tender": tender_rows})
    result = check_selected_providers(
        [{
            "kode_paket": "PK-BARU",
            "nama_penyedia": "CV. A",
            "npwp_penyedia": "1234567890123456",
        }],
        sb_factory=lambda: fake,
    )
    assert result["ok"] is True
    assert result["providers"][0]["skp_berjalan"] == 5
    assert result["providers"][0]["skp_proyeksi"] == 6
    assert result["providers"][0]["boleh_submit"] is False


def test_non_tender_winner_fields_do_not_count_one_package_twice():
    fake = _FakeSupabase({
        "non_tender": [{
            "kode_tender": "N1",
            "nama_paket": "Paket fisik",
            "instansi": "Tapin",
            "tahapan": "Evaluasi",
            "jenis_pengadaan": "Pekerjaan Konstruksi",
            "nama_pemenang": "CV. A",
            "pemenang_berkontrak": "CV. A",
        }],
    })
    result = search_provider("CV. A", sb_factory=lambda: fake)
    assert result["ok"] is True
    assert len(result["rows"]) == 1
