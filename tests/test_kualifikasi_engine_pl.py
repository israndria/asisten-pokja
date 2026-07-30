from kualifikasi_engine_pl import _checklist_output_path


def test_checklist_path_keeps_participant_name_when_short(tmp_path):
    output = _checklist_output_path(str(tmp_path), "CV. CONTOH")

    assert output.endswith("checklist_kualifikasi_CV. CONTOH.pdf")


def test_checklist_path_falls_back_when_windows_path_is_long():
    destination = "D:\\" + ("x" * 210)

    output = _checklist_output_path(destination, "CV. CONTOH PANJANG")

    assert output.endswith("checklist_kualifikasi.pdf")
    assert len(output) < 248
