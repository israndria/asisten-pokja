from datetime import datetime, timedelta
from unittest.mock import patch
import unittest

import gcal_pl_helper


def _jadwal_lima_tahap():
    awal = datetime(2026, 8, 6, 8, 0)
    return [
        {
            "nama": f"Tahap {index}",
            "mulai": awal + timedelta(hours=index),
            "selesai": awal + timedelta(hours=index, minutes=30),
        }
        for index in range(1, 6)
    ]


class _FakeRequest:
    def __init__(self, should_fail=False):
        self.should_fail = should_fail
        self.body = None

    def execute(self):
        if self.should_fail:
            raise RuntimeError("insert gagal untuk simulasi")
        return {"id": "event-id"}


class _FakeEvents:
    def __init__(self, fail_index=None):
        self.fail_index = fail_index
        self.insert_index = 0

    def insert(self, *, calendarId, body):
        self.insert_index += 1
        return _FakeRequest(self.insert_index == self.fail_index)


class _FakeService:
    def __init__(self, fail_index=None):
        self.events_api = _FakeEvents(fail_index)

    def events(self):
        return self.events_api


class GcalPlHelperTest(unittest.TestCase):
    def test_all_events_inserted(self):
        service = _FakeService()
        with patch.object(gcal_pl_helper, "_build_service", return_value=service), patch.object(
            gcal_pl_helper, "_delete_events_by_kode", return_value=2
        ):
            result = gcal_pl_helper.push_jadwal_pl_ke_gcal(
                "123", "Paket Uji", _jadwal_lima_tahap()
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["inserted"], 5)
        self.assertEqual(result["deleted"], 2)
        self.assertEqual(result["error"], "")

    def test_partial_insert_is_reported_as_failure(self):
        service = _FakeService(fail_index=3)
        with patch.object(gcal_pl_helper, "_build_service", return_value=service), patch.object(
            gcal_pl_helper, "_delete_events_by_kode", return_value=5
        ):
            result = gcal_pl_helper.push_jadwal_pl_ke_gcal(
                "456", "Paket Parsial", _jadwal_lima_tahap()
            )

        self.assertFalse(result["ok"])
        self.assertEqual(result["inserted"], 4)
        self.assertEqual(result["deleted"], 5)
        self.assertIn("Tahap 3", result["error"])


if __name__ == "__main__":
    unittest.main()
