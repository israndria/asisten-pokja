import unittest
from types import SimpleNamespace
from unittest.mock import patch

import spse_browser


class SpseBrowserTabSelectionTest(unittest.TestCase):
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
