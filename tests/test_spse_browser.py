import unittest
from types import SimpleNamespace
from unittest.mock import patch

import spse_browser


class SpseBrowserTabSelectionTest(unittest.TestCase):
    def test_cdp_health_requires_devtools_http_endpoint(self):
        class _Response:
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def read(self):
                return b'{"Browser":"Brave/1","webSocketDebuggerUrl":"ws://127.0.0.1/devtools/browser/1"}'

        with patch("socket.create_connection") as socket_connect, \
                patch("urllib.request.urlopen", return_value=_Response()):
            socket_connect.return_value.__enter__.return_value = socket_connect.return_value
            self.assertTrue(spse_browser._cek_cdp_aktif())

        class _InvalidResponse(_Response):
            def read(self):
                return b"{}"

        with patch("socket.create_connection"), \
                patch("urllib.request.urlopen", return_value=_InvalidResponse()):
            self.assertFalse(spse_browser._cek_cdp_aktif())

    def test_cdp_ready_waits_for_transient_cold_start(self):
        with patch.object(
            spse_browser,
            "_cek_cdp_aktif",
            side_effect=[False, False, True],
        ), patch.object(spse_browser.time, "sleep") as sleep:
            self.assertTrue(
                spse_browser.tunggu_cdp_ready(
                    timeout_seconds=1,
                    interval_seconds=0,
                )
            )

        self.assertEqual(sleep.call_count, 2)

    def test_spse_tab_ready_waits_for_tab_after_cdp(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")

        class FakePage:
            def __init__(self, url):
                self.url = url

            def is_closed(self):
                return False

        external = FakePage("https://example.test/")
        spse = FakePage(base + "/")
        context = SimpleNamespace(pages=[external, spse])

        with patch.object(spse_browser, "_get_ctx", return_value=context), \
                patch.object(spse_browser, "_get_page", return_value=external), \
                patch.object(spse_browser, "_set_page") as set_page:
            selected = spse_browser.tunggu_tab_spse_ready(
                timeout_seconds=0.1,
                interval_seconds=0,
            )

        self.assertIs(selected, spse)
        set_page.assert_called_once_with(spse)

    def test_brave_gui_command_does_not_inherit_hidden_startup(self):
        command = spse_browser._visible_brave_command(with_cdp=True)

        self.assertEqual(command[0], spse_browser.CHROME_EXE)
        self.assertIn(f"--remote-debugging-port={spse_browser.CDP_PORT}", command)
        self.assertIn("--new-window", command)
        self.assertNotIn("--headless", command)

    def test_launch_brave_uses_original_popen(self):
        with patch.object(spse_browser, "clone_profil_ke_session", return_value=(True, "")), \
                patch.object(spse_browser, "_OrigPopen") as original_popen:
            spse_browser.launch_chrome_dengan_cdp()

        original_popen.assert_called_once()
        command = original_popen.call_args.args[0]
        self.assertIn(f"--remote-debugging-port={spse_browser.CDP_PORT}", command)
        self.assertNotIn("startupinfo", original_popen.call_args.kwargs)

    def test_access_denied_title_is_not_valid_spse_tab(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")

        self.assertLess(
            spse_browser._url_spse_score(base + "/home", "Terjadi Kesalahan"),
            0,
        )
        self.assertGreater(
            spse_browser._url_spse_score(base + "/home", "Beranda PPK"),
            0,
        )

    def test_access_denied_body_is_detected(self):
        self.assertTrue(
            spse_browser._is_spse_access_error_text(
                "Akses Ditolak! Session telah habis."
            )
        )
        self.assertFalse(
            spse_browser._is_spse_access_error_text("Selamat datang Pejabat Pembuat Komitmen")
        )

    def test_auto_refresh_accepts_home_root_but_not_detail_form(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")

        self.assertTrue(spse_browser._boleh_auto_refresh(base + "/"))
        self.assertTrue(spse_browser._boleh_auto_refresh(base + "/paketnontender"))
        self.assertFalse(spse_browser._boleh_auto_refresh(base + "/nontender/10975369000/edit"))

    def test_public_login_body_is_not_authenticated_tab(self):
        self.assertTrue(spse_browser._is_spse_login_page_text("BERANDA LOGIN"))
        self.assertTrue(spse_browser._is_spse_login_page_text("Nama Pengguna Kata Sandi"))
        self.assertFalse(
            spse_browser._is_spse_login_page_text("Daftar Paket Pejabat Pembuat Komitmen")
        )

    def test_refresh_does_not_claim_success_for_login_body(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")

        class FakePage:
            def is_closed(self):
                return False

            def title(self):
                return "Daftar Paket"

            def locator(self, _selector):
                return self

            def inner_text(self, **_kwargs):
                return "BERANDA LOGIN"

            def reload(self, **_kwargs):
                return None

        fake_page = FakePage()
        run_values = iter([fake_page, None, "Daftar Paket", "BERANDA LOGIN"])

        def fake_run(value, **_kwargs):
            close = getattr(value, "close", None)
            if close is not None:
                close()
            return next(run_values)

        with (
            patch("requests.get") as get,
            patch.object(
                spse_browser,
                "_get_ctx",
                return_value=SimpleNamespace(),
            ),
            patch.object(spse_browser, "_pilih_tab_spse", return_value={"url": base + "/home"}),
            patch.object(spse_browser, "_find_page_for_tab_async"),
            patch.object(spse_browser, "_run", side_effect=fake_run),
            patch.object(spse_browser, "_cek_cdp_aktif", return_value=True),
            patch.object(spse_browser, "diskonek"),
            patch.object(spse_browser, "buka_browser"),
        ):
            get.return_value.json.return_value = [{"type": "page", "url": base + "/home"}]
            self.assertFalse(spse_browser.refresh_browser())

    def test_authenticated_duplicate_url_beats_stale_error_tab(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")
        selected = spse_browser._pilih_tab_spse(
            [
                {"url": base + "/home", "title": "Terjadi Kesalahan"},
                {"url": base + "/home", "title": "Beranda PPK"},
            ]
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["title"], "Beranda PPK")

    def test_restore_cleanup_runs_once_per_tab_snapshot(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")
        before = [
            {"url": base + "/home", "title": "Terjadi Kesalahan"},
            {"url": base + "/paketnontender", "title": "Daftar Paket"},
        ]
        after = [before[1]]
        spse_browser._builtins_sb._spse_restore_state["signature"] = None
        with patch.object(spse_browser, "_cek_cdp_aktif", return_value=True), \
                patch.object(spse_browser, "_cdp_tabs", side_effect=[before, after]) as tabs, \
                patch.object(spse_browser, "buka_browser") as connect, \
                patch.object(spse_browser, "rapikan_tab_spse", return_value=SimpleNamespace(url=after[0]["url"])):
            result = spse_browser.ensure_spse_restore_cleaned()

        self.assertTrue(result["ok"])
        self.assertFalse(result["skipped"])
        connect.assert_called_once_with(navigate=False)
        self.assertEqual(tabs.call_count, 2)


class SpseBrowserPageMappingTest(unittest.IsolatedAsyncioTestCase):
    async def test_duplicate_url_mapping_uses_title(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")

        class FakePage:
            def __init__(self, title, body):
                self.url = base + "/home"
                self._title = title
                self._body = body

            def is_closed(self):
                return False

            async def title(self):
                return self._title

            def locator(self, _selector):
                return self

            async def inner_text(self, timeout=None):
                return self._body

        stale = FakePage("Terjadi Kesalahan", "Akses Ditolak")
        authenticated = FakePage("Beranda PPK", "Pejabat Pembuat Komitmen")
        context = SimpleNamespace(pages=[stale, authenticated])

        with patch.object(spse_browser, "_get_ctx", return_value=context):
            selected = await spse_browser._find_page_for_tab_async(
                {"url": base + "/home", "title": "Beranda PPK"}
            )

        self.assertIs(selected, authenticated)

    async def test_focus_raises_best_non_error_tab_to_foreground(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")

        class FakePage:
            def __init__(self, title, body):
                self.url = base + "/home"
                self._title = title
                self._body = body
                self.brought_to_front = False

            def is_closed(self):
                return False

            async def title(self):
                return self._title

            def locator(self, _selector):
                return self

            async def inner_text(self, timeout=None):
                return self._body

            async def bring_to_front(self):
                self.brought_to_front = True

        stale = FakePage("Terjadi Kesalahan", "Akses Ditolak")
        authenticated = FakePage("Beranda PPK", "Pejabat Pembuat Komitmen")
        context = SimpleNamespace(pages=[stale, authenticated])

        with patch.object(spse_browser, "_get_ctx", return_value=context):
            selected = await spse_browser._fokuskan_tab_spse_async()

        self.assertIs(selected, authenticated)
        self.assertTrue(authenticated.brought_to_front)
        self.assertFalse(stale.brought_to_front)

    async def test_cleanup_closes_only_restored_error_tabs(self):
        base = spse_browser.SPSE_BASE_URL.rstrip("/")

        class FakePage:
            def __init__(self, url, title, body):
                self.url = base + url
                self._title = title
                self._body = body
                self.closed = False
                self.brought_to_front = False

            def is_closed(self):
                return self.closed

            async def title(self):
                return self._title

            def locator(self, _selector):
                return self

            async def inner_text(self, timeout=None):
                return self._body

            async def close(self):
                self.closed = True

            async def bring_to_front(self):
                self.brought_to_front = True

        error_one = FakePage("/home", "Terjadi Kesalahan", "Akses Ditolak")
        error_two = FakePage("/home", "Terjadi Kesalahan", "Session telah habis")
        normal = FakePage("/paketnontender", "Daftar Paket", "BERANDA LOGOUT")
        context = SimpleNamespace(pages=[error_one, normal, error_two])

        with patch.object(spse_browser, "_get_ctx", return_value=context):
            selected = await spse_browser._rapikan_tab_spse_async()

        self.assertIs(selected, normal)
        self.assertTrue(error_one.closed)
        self.assertTrue(error_two.closed)
        self.assertFalse(normal.closed)
        self.assertTrue(normal.brought_to_front)


if __name__ == "__main__":
    unittest.main()
