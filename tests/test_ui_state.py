from unittest.mock import patch

import ui_state


def test_invalidate_ppk_session_state_preserves_non_ppk_state():
    state = {
        "ppk_detail_1": {"nama": "lama"},
        "ppk_versi_1_kak": [],
        "ppk_bulk_1": True,
        "pl_rows": [{"kode": "tetap"}],
    }
    with patch.object(ui_state.st, "session_state", state):
        with patch.object(ui_state.time, "time_ns", return_value=123):
            ui_state.invalidate_ppk_session_state()

    assert state == {
        "_spse_session_epoch": 123,
        "pl_rows": [{"kode": "tetap"}],
    }


def test_ppk_upload_expander_label_changes_identity_when_active():
    idle = ui_state.ppk_upload_expander_label("10. Paket", active=False)
    active = ui_state.ppk_upload_expander_label("10. Paket", active=True)

    assert idle != active
    assert idle.endswith("10. Paket")
    assert active.endswith("10. Paket")
