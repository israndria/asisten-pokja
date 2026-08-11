from tender_setup_engine import normalize_sbu_classification


def test_normalize_sbu_classification_inserts_expected_space():
    raw = (
        "Memiliki Sertifikat Badan Usaha (SBU) dengan Kualifikasi Usaha Kecil, "
        "serta disyaratkan:\nSBU BG009 Konstruksi Gedung Lainnya KBLI 41019"
    )

    assert normalize_sbu_classification(raw) == (
        "Memiliki Sertifikat Badan Usaha SBU dengan Kualifikasi Usaha Kecil, "
        "serta disyaratkan SBU BG009 Konstruksi Gedung Lainnya KBLI 41019"
    )


def test_normalize_sbu_classification_leaves_custom_text_unchanged():
    assert normalize_sbu_classification("Persyaratan izin custom") == "Persyaratan izin custom"
