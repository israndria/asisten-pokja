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
    def __init__(self, should_fail=False, payload=None):
        self.should_fail = should_fail
        self.body = None
        self.payload = payload

    def execute(self):
        if self.should_fail:
            raise RuntimeError("insert gagal untuk simulasi")
        return self.payload or {"id": "event-id"}


class _FakeEvents:
    def __init__(self, fail_index=None, items=None):
        self.fail_index = fail_index
        self.insert_index = 0
        self.items = items or []
        self.update_count = 0
        self.delete_count = 0

    def insert(self, *, calendarId, body):
        self.insert_index += 1
        return _FakeRequest(self.insert_index == self.fail_index)

    def list(self, **kwargs):
        return _FakeRequest(payload={"items": self.items})

    def update(self, *, eventId, body, **kwargs):
        self.update_count += 1
        return _FakeRequest(payload={"id": eventId})

    def delete(self, *, eventId, **kwargs):
        self.delete_count += 1
        return _FakeRequest(payload={})


class _FakeService:
    def __init__(self, fail_index=None, items=None):
        self.events_api = _FakeEvents(fail_index, items)

    def events(self):
        return self.events_api


class GcalPlHelperTest(unittest.TestCase):
    def test_tapin_uses_wita_timezone(self):
        self.assertEqual(gcal_pl_helper.TZ, "Asia/Makassar")

    def test_automatic_sync_skips_unchanged_schedule(self):
        jadwal = _jadwal_lima_tahap()
        schedule_hash = gcal_pl_helper._schedule_hash(jadwal)
        with patch.object(gcal_pl_helper, "parse_jadwal_pl_dari_spse", return_value=jadwal), patch.object(
            gcal_pl_helper, "_load_schedule_state", return_value={"123": schedule_hash}
        ), patch.object(gcal_pl_helper, "_gcal_schedule_complete", return_value=True), patch.object(
            gcal_pl_helper, "push_jadwal_pl_ke_gcal"
        ) as push:
            result = gcal_pl_helper.sync_jadwal_pl(
                "123", "Paket Uji", skip_unchanged=True
            )

        self.assertTrue(result["ok"])
        self.assertTrue(result["skipped"])
        push.assert_not_called()

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
        self.assertEqual(result["deleted"], 0)
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
        self.assertEqual(result["deleted"], 0)
        self.assertIn("Tahap 3", result["error"])

    def test_existing_event_is_updated_and_missing_events_are_inserted(self):
        existing = [{
            "id": "old-event",
            "summary": "Tahap 1 - Paket Uji",
            "description": "Paket PL: 789\nPaket Uji",
            "extendedProperties": {"private": {
                "source_pl": "789", "source_stage_index": "1",
            }},
        }]
        service = _FakeService(items=existing)
        with patch.object(gcal_pl_helper, "_build_service", return_value=service):
            result = gcal_pl_helper.push_jadwal_pl_ke_gcal(
                "789", "Paket Uji", _jadwal_lima_tahap()
            )

        self.assertTrue(result["ok"])
        self.assertEqual(result["updated"], 1)
        self.assertEqual(result["inserted"], 4)
        self.assertEqual(result["deleted"], 0)
        self.assertEqual(service.events_api.update_count, 1)


if __name__ == "__main__":
    unittest.main()
