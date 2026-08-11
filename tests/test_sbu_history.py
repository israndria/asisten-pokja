import sbu_history
from sbu_history import compact_sbu_label, load_sbu_history, save_sbu_history


def test_load_merges_legacy_string_and_pair_history(tmp_path):
    canonical = tmp_path / "sbu_history.json"
    legacy_pl = tmp_path / "pl_sbu_history.json"
    legacy_tender = tmp_path / "tender_sbu_history.json"
    legacy_pl.write_text('[{"baru": "PL baru", "lama": "PL lama"}]', encoding="utf-8")
    legacy_tender.write_text('["Tender lama"]', encoding="utf-8")

    history = load_sbu_history(canonical, (legacy_pl, legacy_tender))

    assert history[0] == {"baru": "PL baru", "lama": "PL lama"}
    assert {"baru": "Tender lama", "lama": ""} in history
    assert any(item["baru"].startswith("SBU BS010") for item in history)


def test_save_puts_new_pair_first_and_persists_canonical(tmp_path):
    canonical = tmp_path / "sbu_history.json"

    history = save_sbu_history("SBU baru", "SBU lama", canonical, ())

    assert history[0] == {"baru": "SBU baru", "lama": "SBU lama"}
    reloaded = load_sbu_history(canonical, ())
    assert reloaded[0] == history[0]


def test_legacy_jkk_consultancy_does_not_enter_shared_history(tmp_path, monkeypatch):
    canonical = tmp_path / "sbu_history.json"
    legacy_jkk = tmp_path / "pl_sbu_history.json"
    legacy_jkk.write_text(
        '[{"baru": "SBU BG009 Konstruksi Gedung Lainnya", "lama": ""}, '
        '{"baru": "RK003 Jasa Rekayasa Konsultansi", "lama": ""}]',
        encoding="utf-8",
    )
    monkeypatch.setattr(sbu_history, "LEGACY_PK_SBU_HISTORY_PATH", legacy_jkk)

    history = load_sbu_history(canonical, ())
    values = {item["baru"] for item in history}

    assert "SBU BG009 Konstruksi Gedung Lainnya" in values
    assert "RK003 Jasa Rekayasa Konsultansi" not in values


def test_compact_label_keeps_code_and_kbli_only():
    label = compact_sbu_label(
        "SBU BG006 Konstruksi Gedung Pendidikan KBLI 41016 atau "
        "Konstruksi Konvensional Gedung Pendidikan"
    )

    assert label == "BG006 — Konstruksi Gedung Pendidikan · KBLI 41016"


def test_load_deduplicates_legacy_wording_by_code_and_kbli(tmp_path):
    canonical = tmp_path / "sbu_history.json"
    canonical.write_text(
        '[{"baru": "SBU BG009 Konstruksi Gedung Lainnya KBLI 41019", "lama": ""}, '
        '{"baru": "SBU BG009 KBLI 41019 Konstruksi Gedung Lainnya", "lama": ""}]',
        encoding="utf-8",
    )

    history = load_sbu_history(canonical, ())
    assert sum("BG009" in item["baru"] for item in history) == 1
