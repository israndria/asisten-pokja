from types import SimpleNamespace
from unittest import IsolatedAsyncioTestCase
from unittest.mock import AsyncMock, patch

from kualifikasi_engine_pl import _checklist_output_path
from kualifikasi_engine_plpk import _participant_page_with_retry


def test_checklist_path_keeps_participant_name_when_short(tmp_path):
    output = _checklist_output_path(str(tmp_path), "CV. CONTOH")

    assert output.endswith("checklist_kualifikasi_CV. CONTOH.pdf")


def test_checklist_path_falls_back_when_windows_path_is_long():
    destination = "D:\\" + ("x" * 210)

    output = _checklist_output_path(destination, "CV. CONTOH PANJANG")

    assert output.endswith("checklist_kualifikasi.pdf")
    assert len(output) < 248


class _FakeParticipantPage:
    def __init__(self, url="about:blank", fail_goto_times=0):
        self.url = url
        self.fail_goto_times = fail_goto_times
        self.goto_calls = []
        self.wait_load_calls = []
        self.wait_selector_calls = []

    def is_closed(self):
        return False

    async def goto(self, url, **kwargs):
        self.goto_calls.append((url, kwargs))
        if len(self.goto_calls) <= self.fail_goto_times:
            raise TimeoutError("navigation timeout")
        self.url = url

    async def wait_for_load_state(self, state, **kwargs):
        self.wait_load_calls.append((state, kwargs))

    async def wait_for_selector(self, selector, **kwargs):
        self.wait_selector_calls.append((selector, kwargs))


class ParticipantPageRetryTest(IsolatedAsyncioTestCase):
    async def test_reuses_loaded_target_tab_without_goto(self):
        url = "https://spse.inaproc.id/tapinkab/pesertanontender/PK-1/penawaran"
        page = _FakeParticipantPage(url)
        context = SimpleNamespace(pages=[page])

        with patch(
            "kualifikasi_engine_plpk.spse_browser._connect_cdp_async",
            new=AsyncMock(),
        ), patch(
            "kualifikasi_engine_plpk.spse_browser._get_ctx",
            return_value=context,
        ), patch(
            "kualifikasi_engine_plpk.spse_browser._set_page",
        ) as set_page:
            result = await _participant_page_with_retry(url)

        assert result is page
        assert page.goto_calls == []
        assert page.wait_load_calls[0][0] == "domcontentloaded"
        assert page.wait_selector_calls[0][0] == "table"
        set_page.assert_called_once_with(page)

    async def test_retries_slow_navigation_before_failing(self):
        url = "https://spse.inaproc.id/tapinkab/pesertanontender/PK-2/penawaran"
        page = _FakeParticipantPage(fail_goto_times=1)

        async def new_page():
            context.pages.append(page)
            return page

        context = SimpleNamespace(pages=[], new_page=new_page)

        with patch(
            "kualifikasi_engine_plpk.spse_browser._connect_cdp_async",
            new=AsyncMock(),
        ), patch(
            "kualifikasi_engine_plpk.spse_browser._get_ctx",
            return_value=context,
        ), patch(
            "kualifikasi_engine_plpk.spse_browser._set_page",
        ), patch(
            "asyncio.sleep",
            new=AsyncMock(),
        ):
            result = await _participant_page_with_retry(url)

        assert result is page
        assert len(page.goto_calls) == 2
        assert page.goto_calls[-1][1]["timeout"] == 60000
        assert context.pages == [page]
