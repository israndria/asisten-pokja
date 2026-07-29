import io
import json
import base64
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
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
    async def test_fetch_captcha_uses_displayed_dom_image_without_second_get(self):
        displayed = b"displayed-captcha"
        element = SimpleNamespace(
            evaluate=AsyncMock(
                return_value=base64.b64encode(displayed).decode("ascii")
            )
        )
        page = SimpleNamespace(
            query_selector=AsyncMock(return_value=element),
            wait_for_function=AsyncMock(),
        )

        result = await spse_login._fetch_captcha_bytes(page)

        self.assertEqual(result, displayed)
        page.wait_for_function.assert_awaited_once()
        element.evaluate.assert_awaited_once()

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

    async def test_wait_for_authenticated_role_retries_transient_probe(self):
        page = SimpleNamespace(wait_for_timeout=AsyncMock())
        with patch.object(
            spse_login,
            "_probe_authenticated_role",
            AsyncMock(side_effect=[None, None, "PP"]),
        ) as probe:
            detected = await spse_login._wait_for_authenticated_role(
                page,
                timeout_ms=1500,
                interval_ms=500,
            )

        self.assertEqual(detected, "PP")
        self.assertEqual(probe.await_count, 3)

    async def test_ensure_loginpass_reopens_form_after_root_redirect(self):
        page = SimpleNamespace(url="https://spse.inaproc.id/tapinkab/")
        with (
            patch.object(
                spse_login,
                "_probe_authenticated_role",
                AsyncMock(return_value=None),
            ),
            patch.object(
                spse_login,
                "_open_loginpass",
                AsyncMock(),
            ) as reopen,
        ):
            detected = await spse_login._ensure_loginpass(
                page,
                username="user",
                expected_role="PP",
            )

        self.assertIsNone(detected)
        reopen.assert_awaited_once_with(page, "user", log_fn=None)

    async def test_captcha_loop_continues_after_root_redirect(self):
        page = SimpleNamespace(
            url="https://spse.inaproc.id/tapinkab/loginpass",
            wait_for_selector=AsyncMock(),
            fill=AsyncMock(),
            wait_for_timeout=AsyncMock(),
        )

        async def redirect_to_root(*_args, **_kwargs):
            page.url = "https://spse.inaproc.id/tapinkab/"

        page.click = AsyncMock(side_effect=redirect_to_root)
        with (
            patch.object(
                spse_login,
                "_ensure_loginpass",
                AsyncMock(side_effect=[None, "PP"]),
            ) as ensure,
            patch.object(
                spse_login,
                "_fetch_captcha_bytes",
                AsyncMock(return_value=b"image"),
            ),
            patch.object(
                spse_login,
                "_solve_captcha",
                AsyncMock(return_value=("abc123", "test")),
            ),
            patch.object(
                spse_login,
                "_wait_for_authenticated_role",
                AsyncMock(return_value=None),
            ),
            patch.object(
                spse_login,
                "_read_login_error",
                AsyncMock(return_value=""),
            ),
            patch.object(spse_login, "_record_login_event"),
        ):
            result = await spse_login._run_captcha_attempts(
                page,
                "user",
                "password",
                "PP",
            )

        self.assertTrue(result)
        self.assertEqual(ensure.await_count, 2)
        page.click.assert_awaited_once_with("button[type='submit']")


class SpseLunaFailureTest(unittest.TestCase):
    def test_luna_config_error_is_not_reported_as_no_match(self):
        self.assertEqual(
            spse_login._classify_luna_failure(
                1,
                "Error loading config.toml: duplicate key",
            ),
            "config_error",
        )

    def test_luna_valid_empty_verdict_is_no_match(self):
        self.assertEqual(spse_login._classify_luna_failure(0, ""), "no_match")


if __name__ == "__main__":
    unittest.main()
