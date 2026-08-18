"""Regression resolver workbook untuk populate evaluasi PLPK."""

from types import SimpleNamespace

import config
import hasil_evaluasi_plpk_engine as engine
import parse_kak_pl


def test_find_xlsm_uses_baplpks_for_pk_package(monkeypatch, tmp_path):
    workbook = tmp_path / "0. BAPLPK- Paket Fisik.xlsm"
    workbook.write_bytes(b"placeholder")

    class FakeQuery:
        def select(self, *_args):
            return self

        def eq(self, *_args):
            return self

        def maybe_single(self):
            return self

        def execute(self):
            return SimpleNamespace(data={
                "kode_paket": "PK-28",
                "nama_paket": "Paket Fisik",
                "jenis_pl": "PK",
                "nomor_urut": "28",
                "is_ulang": False,
            })

    class FakeClient:
        def table(self, _name):
            return FakeQuery()

    monkeypatch.setattr(config, "sb", lambda: FakeClient())
    monkeypatch.setattr(
        parse_kak_pl,
        "_resolve_folder_pl",
        lambda *_args, **_kwargs: (str(tmp_path), "28"),
    )

    assert engine._find_xlsm("PK-28") == str(workbook)
