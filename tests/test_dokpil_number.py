import unittest
from unittest.mock import patch

import pl_data_ui
import pl_ui_helpers
from upload_dokpil_pl import upload_dokpil_pl, validate_nomor_dokpil


class DokpilNumberTests(unittest.TestCase):
    def test_valid_excel_nomor_dokpil(self):
        ok, error = validate_nomor_dokpil(
            "000.3.3/01/PL/PP-29/P.Block_P.Bng/DISDAG/2026"
        )
        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_valid_paket_ulang_nomor_dokpil(self):
        ok, error = validate_nomor_dokpil(
            "000.3.3/PLU/01/PL/PP-29/P.Block_P.Bng/DISDAG/2026"
        )
        self.assertTrue(ok)
        self.assertEqual(error, "")

    def test_question_mark_is_rejected(self):
        ok, error = validate_nomor_dokpil(
            "000.3.3/01/PL/PP-29/?/DISDAG/2026"
        )
        self.assertFalse(ok)
        self.assertIn("tanda '?'", error)

    def test_upload_rejects_invalid_number_before_network(self):
        with patch("upload_dokpil_pl.spse_browser.get_spse_cookies") as get_cookies:
            result = upload_dokpil_pl(
                kode_paket="11900000000",
                file_bytes=b"%PDF-1.7",
                file_name="dokpil.pdf",
                nomor_dokpil="000.3.3/01/PL/PP-29/?/DISDAG/2026",
                tgl_dokpil="06-08-2026",
            )
        self.assertFalse(result["ok"])
        self.assertIn("Nomor Dokpil tidak valid", result["error"])
        self.assertIn("status", result)
        self.assertEqual(result["stage"], "validasi nomor Dokpil")
        get_cookies.assert_not_called()

    def test_loader_overwrites_stale_supabase_number_from_excel(self):
        resolved = {
            "ok": True,
            "nomor_dokpil": "000.3.3/01/PL/PP-29/P.Block_P.Bng/DISDAG/2026",
            "master_data": {
                "kode_unik": "P.Block_P.Bng",
                "nomor_dokpil": "000.3.3/01/PL/PP-29/P.Block_P.Bng/DISDAG/2026",
                "tgl_dokpil": "2026-08-06",
            },
            "error": "",
        }
        with patch.object(pl_ui_helpers, "_resolve_nomor_dokpil_excel_pl", return_value=resolved):
            rows = pl_data_ui._hydrate_dokpil_from_excel([{
                "kode_paket": "11900000000",
                "nomor_dokpil": "000.3.3/01/PL/PP-29/?/DISDAG/2026",
            }])
        self.assertEqual(rows[0]["nomor_dokpil"], resolved["nomor_dokpil"])
        self.assertTrue(rows[0]["_nomor_dokpil_excel_ok"])
        self.assertEqual(rows[0]["tgl_dokpil"], "2026-08-06")


if __name__ == "__main__":
    unittest.main()
