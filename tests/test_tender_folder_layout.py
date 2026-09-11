from types import SimpleNamespace

import config
import kualifikasi_engine
import pindah_penawaran_engine


def test_tender_document_folder_constants_are_canonical():
    assert config.TENDER_KUALIFIKASI_SUBFOLDER == "8. Dokumen Kualifikasi"
    assert config.TENDER_PENAWARAN_SUBFOLDER == "9. Dokumen Penawaran Teknis & Biaya"


def test_tender_offer_destination_uses_canonical_folder(tmp_path):
    item = {
        "folder_paket": str(tmp_path),
        "kode_tender": "101",
        "urutan": 1,
        "nama_perusahaan": "CV Contoh",
    }

    result = pindah_penawaran_engine.resolve_dest(item, {"101": 1})

    assert result == str(tmp_path / "9. Dokumen Penawaran Teknis & Biaya")


def test_tender_kualifikasi_resolver_uses_canonical_folder(tmp_path, monkeypatch):
    class _Query:
        def select(self, _fields):
            return self

        def eq(self, *_args):
            return self

        def maybe_single(self):
            return self

        def execute(self):
            return SimpleNamespace(data={"folder_dibuat": "12. [Pokja-061] Uji"})

    monkeypatch.setattr(config, "sb", lambda: SimpleNamespace(table=lambda _name: _Query()))
    monkeypatch.setattr(config, "TENDER_ROOT", str(tmp_path))

    result = kualifikasi_engine.resolve_folder_paket("10161566000")

    assert result["ok"] is True
    assert result["path"] == str(tmp_path / "12. [Pokja-061] Uji" / "8. Dokumen Kualifikasi")
