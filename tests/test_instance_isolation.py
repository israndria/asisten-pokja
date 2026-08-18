import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch

import spse_browser


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _config_snapshot(instance: str) -> dict:
    env = os.environ.copy()
    env["ASISTEN_INSTANCE"] = instance
    env.pop("ASISTEN_FIXED_ROLE", None)
    env.pop("SPSE_CDP_PORT", None)
    code = (
        "import json, config, spse_browser; "
        "print(json.dumps({" 
        "'instance': config.ASISTEN_INSTANCE, "
        "'role': config.ASISTEN_FIXED_ROLE, "
        "'allowed': list(config.ASISTEN_ALLOWED_ROLES), "
        "'default': config.ASISTEN_DEFAULT_ROLE, "
        "'cdp': config.SPSE_CDP_PORT, "
        "'runtime': config.RUNTIME_ROOT, "
        "'browser': config.BROWSER_SESSION_DIR, "
        "'downloads': config.DOWNLOAD_DIR, "
        "'icon': config.APP_ICON_PATH, "
        "'browser_cdp': spse_browser.CDP_PORT" 
        "}))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return json.loads(result.stdout.strip())


def _role_probe(instance: str, role: str) -> str:
    env = os.environ.copy()
    env["ASISTEN_INSTANCE"] = instance
    env.pop("ASISTEN_FIXED_ROLE", None)
    code = "\n".join(
        [
            "import spse_login",
            "role = " + repr(role),
            "try:",
            "    spse_login._assert_role_allowed(role)",
            "    print('allowed')",
            "except ValueError:",
            "    print('blocked')",
        ]
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        cwd=REPO_ROOT,
        env=env,
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


class InstanceIsolationTest(unittest.TestCase):
    def test_pp_and_tender_have_separate_role_cdp_and_runtime(self):
        pp = _config_snapshot("PP")
        tender = _config_snapshot("TENDER")

        self.assertEqual((pp["role"], pp["default"], pp["cdp"], pp["browser_cdp"]), (None, "PP", 9222, 9222))
        self.assertEqual(pp["allowed"], ["PP", "PPK"])
        self.assertEqual(
            (tender["role"], tender["default"], tender["cdp"], tender["browser_cdp"]),
            ("POKJA", "POKJA", 9223, 9223),
        )
        self.assertEqual(tender["allowed"], ["POKJA"])
        self.assertNotEqual(pp["runtime"], tender["runtime"])
        self.assertNotEqual(pp["browser"], tender["browser"])
        self.assertNotEqual(pp["downloads"], tender["downloads"])
        self.assertTrue(pp["icon"].endswith(os.path.join("assets", "pppk-favicon.png")))
        self.assertTrue(tender["icon"].endswith(os.path.join("assets", "pokja-favicon.png")))
        self.assertTrue(os.path.isfile(pp["icon"]))
        self.assertTrue(os.path.isfile(tender["icon"]))

    def test_role_allowlist_keeps_ppk_with_pp_but_blocks_cross_instance_roles(self):
        self.assertEqual(_role_probe("PP", "PP"), "allowed")
        self.assertEqual(_role_probe("PP", "PPK"), "allowed")
        self.assertEqual(_role_probe("PP", "POKJA"), "blocked")
        self.assertEqual(_role_probe("TENDER", "POKJA"), "allowed")
        self.assertEqual(_role_probe("TENDER", "PPK"), "blocked")

    def test_cdp_listener_pids_use_instance_port(self):
        netstat = """  TCP    127.0.0.1:9222    0.0.0.0:0    LISTENING    111
  TCP    127.0.0.1:9223    0.0.0.0:0    LISTENING    222
"""
        completed = type("Completed", (), {"stdout": netstat})()
        with patch.object(spse_browser, "CDP_PORT", 9223), patch(
            "subprocess.run", return_value=completed
        ):
            self.assertEqual(spse_browser._cdp_listener_pids(), {222})

    def test_kill_browser_only_uses_listener_pids_for_own_instance(self):
        with (
            patch.object(spse_browser, "_cdp_listener_pids", return_value={222}),
            patch.object(spse_browser, "stop_auto_refresh"),
            patch.object(spse_browser, "diskonek"),
            patch("subprocess.run") as run,
        ):
            spse_browser._kill_browser()

        taskkill_calls = [call for call in run.call_args_list if call.args]
        self.assertEqual(taskkill_calls[0].args[0], ["taskkill", "/F", "/T", "/PID", "222"])


if __name__ == "__main__":
    unittest.main()
