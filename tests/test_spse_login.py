import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from PIL import Image

import spse_login


class SpseLoginHelpersTest(unittest.TestCase):
    def test_normalize_rgba_captcha_uses_alpha_on_white(self):
        source = Image.new("RGBA", (2, 1), (0, 0, 0, 0))
        source.putpixel((1, 0), (0, 0, 0, 255))
        raw = io.BytesIO()
        source.save(raw, format="PNG")

        normalized = Image.open(
            io.BytesIO(spse_login._normalize_captcha_png(raw.getvalue()))
        ).convert("RGB")

        self.assertEqual(normalized.getpixel((0, 0)), (255, 255, 255))
        self.assertEqual(normalized.getpixel((1, 0)), (0, 0, 0))

    def test_rank_candidates_prefers_consensus_then_six_chars(self):
        ranked = spse_login._rank_captcha_candidates(
            ["abcd", "abc123", "abcd", "abc123", "abc123", "zzzzzz"]
        )
        self.assertEqual(ranked[:3], ["abc123", "abcd", "zzzzzz"])

    def test_parse_luna_verdict_only_accepts_exact_candidate(self):
        candidates = ["abc123", "def456"]
        self.assertEqual(
            spse_login._parse_luna_verdict("abc123\n", candidates),
            "abc123",
        )
        self.assertEqual(
            spse_login._parse_luna_verdict("MATCH\n", ["abc123"]),
            "abc123",
        )
        self.assertEqual(
            spse_login._parse_luna_verdict("Sorry, I cannot help.", candidates),
            "",
        )

    def test_role_detection_from_text(self):
        self.assertEqual(
            spse_login._role_from_text("Selamat datang Pejabat Pengadaan"),
            "PP",
        )
        self.assertEqual(
            spse_login._role_from_text("Pejabat Pembuat Komitmen"),
            "PPK",
        )
        self.assertEqual(
            spse_login._role_from_text("Dashboard Kelompok Kerja Pemilihan"),
            "POKJA",
        )
        self.assertIsNone(spse_login._role_from_text("Akses Ditolak"))

    def test_telemetry_contains_no_secret_or_captcha_value(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "metrics.jsonl"
            spse_login._record_login_event(
                "captcha_attempt",
                role="POKJA",
                method="luna",
                attempt=1,
                status="rejected",
                elapsed_ms=12,
                path=path,
            )
            payload = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(payload["event"], "captcha_attempt")
        self.assertEqual(payload["role"], "POKJA")
        self.assertNotIn("candidate", payload)
        self.assertNotIn("password", payload)
        self.assertNotIn("username", payload)


class SpseSessionFirstTest(unittest.IsolatedAsyncioTestCase):
    async def test_valid_same_role_skips_credentials_and_navigation(self):
        page = object()
        with (
            patch("spse_browser._get_page", return_value=page),
            patch.object(
                spse_login,
                "_probe_authenticated_role",
                AsyncMock(return_value="PP"),
            ),
            patch.object(
                spse_login,
                "_get_creds",
                side_effect=AssertionError("credentials must not be read"),
            ),
            patch.object(spse_login, "_record_login_event"),
        ):
            result = await spse_login._login_async("PP")

        self.assertTrue(result)


if __name__ == "__main__":
    unittest.main()
