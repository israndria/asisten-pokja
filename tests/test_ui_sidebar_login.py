import unittest
from unittest.mock import patch

import ui_sidebar


class FinalizeSpseLoginTest(unittest.TestCase):
    def test_cleanup_failure_keeps_validated_login(self):
        state = {
            "login_failed": True,
            "login_failed_role": "PP",
            "manual_spse_captcha": "abc1",
        }
        logs = []
        with (
            patch.object(ui_sidebar.st, "session_state", state),
            patch("spse_login.remember_login_role"),
            patch.object(
                ui_sidebar.spse_browser,
                "buka_browser",
                side_effect=RuntimeError("tab race"),
            ),
            patch.object(ui_sidebar.spse_browser, "mulai_auto_refresh"),
        ):
            ui_sidebar._finalize_authenticated_spse_login("PP", logs.append)

        self.assertEqual(state["spse_role"], "PP")
        self.assertIn("_spse_session_epoch", state)
        self.assertNotIn("login_failed", state)
        self.assertNotIn("login_failed_role", state)
        self.assertNotIn("manual_spse_captcha", state)
        self.assertTrue(any("cleanup tab dilewati" in line for line in logs))


if __name__ == "__main__":
    unittest.main()
