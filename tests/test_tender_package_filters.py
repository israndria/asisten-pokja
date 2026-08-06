from tender_package_filters import (
    filter_tender_candidates,
    is_draft,
    normalize_stage,
    stage_rank,
    stale_selection_keys,
)


def row(kode, status_tahap, **extra):
    return {"kode": kode, "status_tahap": status_tahap, **extra}


def test_stage_normalization_is_tolerant():
    assert normalize_stage(" PEMBERIAN-PENJELASAN ") == "pemberian penjelasan"
    assert stage_rank(row("1", "Pembukaan Dokumen Penawaran")) == 6


def test_tabs_1_to_3_are_draft_only():
    rows = [
        row("D", "Draft", _tender_source="draft"),
        row("A", "Pemberian Penjelasan", _tender_source="aktif"),
    ]
    for tab in (1, 2, 3):
        assert [p["kode"] for p in filter_tender_candidates(rows, tab)] == ["D"]


def test_tab_4_stops_after_pemberian_penjelasan_and_excludes_draft():
    rows = [
        row("early", "Pemberian Penjelasan", _tender_source="aktif"),
        row("late", "Masa Pemasukan Dokumen Penawaran", _tender_source="aktif"),
        row("draft", "Draft", _tender_source="draft"),
    ]
    assert [p["kode"] for p in filter_tender_candidates(rows, 4)] == ["early"]


def test_tabs_5_to_8_use_distinct_stage_gates():
    rows = [
        row("eval", "Evaluasi Administrasi"),
        row("proof", "Pembuktian Kualifikasi"),
        row("open", "Pembukaan Dokumen Penawaran"),
        row("early", "Pemberian Penjelasan"),
        row("done", "Penandatanganan Kontrak"),
    ]
    assert [p["kode"] for p in filter_tender_candidates(rows, 5)] == ["eval", "proof"]
    assert [p["kode"] for p in filter_tender_candidates(rows, 6)] == ["eval", "proof", "open"]
    assert [p["kode"] for p in filter_tender_candidates(rows, 7)] == ["eval", "proof", "open"]
    assert [p["kode"] for p in filter_tender_candidates(rows, 8)] == ["eval", "proof"]


def test_known_draft_code_wins_when_row_cache_has_no_status():
    assert is_draft(row("D", ""), draft_kodes={"D"})
    assert filter_tender_candidates([row("D", "Pemberian Penjelasan")], 4, draft_kodes={"D"}) == []


def test_stale_widget_keys_are_identified_without_mutation():
    keys = ["kp_chk_A", "kp_chk_B", "other_A"]
    assert stale_selection_keys(keys, "kp_chk_", {"A"}) == ["kp_chk_B"]
    assert keys == ["kp_chk_A", "kp_chk_B", "other_A"]


if __name__ == "__main__":
    for _name, _fn in sorted(globals().items()):
        if _name.startswith("test_") and callable(_fn):
            _fn()
    print("targeted pure tests: PASS")
