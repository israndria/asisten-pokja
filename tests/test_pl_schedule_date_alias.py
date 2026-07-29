from datetime import datetime
from types import SimpleNamespace

import pytest


class _Query:
    def __init__(self, sink):
        self.sink = sink

    def upsert(self, payload):
        self.sink["payload"] = payload
        return self

    def update(self, payload):
        self.sink["payload"] = payload
        return self

    def eq(self, *_args):
        return self

    def execute(self):
        return SimpleNamespace(data=[])


class _Client:
    def __init__(self, sink):
        self.sink = sink

    def table(self, name):
        self.sink["table"] = name
        return _Query(self.sink)


@pytest.mark.parametrize("module_name", ["pl_engine", "pl_engine_plpk"])
def test_simpan_paket_pl_syncs_opening_date_aliases(monkeypatch, module_name):
    module = __import__(module_name)
    sink = {}
    monkeypatch.setattr(module, "_sb", lambda: _Client(sink))
    source = {
        "kode_paket": "10930000000",
        "tgl_buka_penawaran": "2026-07-29",
    }

    result = module.simpan_paket_pl(source)

    assert result["ok"] is True
    assert sink["payload"]["tgl_buka_penawaran"] == "2026-07-29"
    assert sink["payload"]["tgl_pembukaan"] == "2026-07-29"
    assert "tgl_pembukaan" not in source


def test_sync_jadwal_pl_updates_both_opening_date_columns(monkeypatch):
    import config
    import gcal_pl_helper as helper

    sink = {}
    jadwal = [
        {"nama": "Upload", "mulai": datetime(2026, 7, 24, 10), "selesai": datetime(2026, 7, 29, 10)},
        {"nama": "Pembukaan", "mulai": datetime(2026, 7, 29, 10, 1), "selesai": datetime(2026, 7, 29, 11, 5)},
        {"nama": "Evaluasi", "mulai": datetime(2026, 7, 29, 11, 6), "selesai": datetime(2026, 7, 30, 16)},
        {"nama": "Negosiasi", "mulai": datetime(2026, 7, 30, 9), "selesai": datetime(2026, 7, 30, 15, 45)},
        {"nama": "Kontrak", "mulai": datetime(2026, 7, 31, 8), "selesai": datetime(2026, 8, 7, 16)},
    ]
    monkeypatch.setattr(helper, "parse_jadwal_pl_dari_spse", lambda _kode: jadwal)
    monkeypatch.setattr(
        helper,
        "push_jadwal_pl_ke_gcal",
        lambda *_args: {"ok": True, "inserted": 5, "deleted": 0, "error": ""},
    )
    monkeypatch.setattr(config, "sb", lambda: _Client(sink))

    result = helper.sync_jadwal_pl("10930000000", "Paket 30")

    assert result["ok"] is True
    assert sink["payload"]["tgl_buka_penawaran"] == "2026-07-29"
    assert sink["payload"]["tgl_pembukaan"] == "2026-07-29"
    assert sink["payload"]["tgl_negosiasi"] == "2026-07-30"
