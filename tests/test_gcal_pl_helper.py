from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
import unittest

import gcal_pl_helper
import config
from openpyxl import Workbook


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
        self.updated_bodies = []

    def insert(self, *, calendarId, body):
        self.insert_index += 1
        return _FakeRequest(self.insert_index == self.fail_index)

    def list(self, **kwargs):
        return _FakeRequest(payload={"items": self.items})

    def update(self, *, eventId, body, **kwargs):
        self.update_count += 1
        self.updated_bodies.append(body)
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
    def test_pl_folder_identity_uses_master_data_code(self):
        with TemporaryDirectory() as temp_dir:
            folder_root = Path(temp_dir)
            folder = folder_root / "Paket PL"
            folder.mkdir(parents=True)
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "@ Master Data"
            sheet["C3"] = "123456"
            workbook.save(folder / "Paket.xlsm")
            workbook.close()

            with patch.object(gcal_pl_helper, "OUTPUT_DIR_PL_JKK", str(folder_root)), patch.object(
                gcal_pl_helper, "OUTPUT_DIR_PL_PK", str(folder_root / "PK")
            ):
                self.assertTrue(
                    gcal_pl_helper._pl_folder_identity_valid("Paket PL", "123456")
                )
                self.assertFalse(
                    gcal_pl_helper._pl_folder_identity_valid("Paket PL", "999999")
                )

    def test_pl_sync_uses_registry_targets_even_when_db_row_is_missing(self):
        class _Query:
            def select(self, *_columns):
                return self

            def in_(self, *_args):
                return self

            def execute(self):
                return type("Response", (), {"data": [
                    {"kode_paket": "1", "nama_paket": "Target", "tahap_spse": "Evaluasi"},
                    {"kode_paket": "2", "nama_paket": "Selesai", "tahap_spse": "Paket Sudah Selesai"},
                ]})()

        class _Client:
            def table(self, name):
                assert name == "draft_paket_pl"
                return _Query()

        with patch.object(gcal_pl_helper, "load_targets", return_value=[
            {"kode_paket": "1"}, {"kode_paket": "2"}, {"kode_paket": "3"},
            {"kode_paket": "4", "source": "folder-auto", "folder_name": "Z:\\stale-package"},
        ]), patch.object(config, "sb", return_value=_Client()):
            rows = gcal_pl_helper._load_owned_pl_rows()

        self.assertEqual(rows, [
            {"kode_paket": "1", "nama_paket": "Target"},
            {"kode_paket": "3", "nama_paket": "3"},
            {"kode_paket": "4", "nama_paket": "4"},
        ])

    def test_auto_enroll_pl_resolves_boolean_folder_status(self):
        expected_folder = r"D:\PL\30. PLPK - Paket Aktif"

        class _Query:
            def select(self, *_columns):
                return self

            def execute(self):
                return type("Response", (), {"data": [{
                    "kode_paket": "10986970000",
                    "nama_paket": "Paket Aktif",
                    "folder_dibuat": True,
                    "jenis_pl": "PK",
                    "nomor_urut": 30,
                    "is_ulang": False,
                }]})()

        class _Client:
            def table(self, name):
                assert name == "draft_paket_pl"
                return _Query()

        with patch.object(config, "sb", return_value=_Client()), patch.object(
            gcal_pl_helper, "load_targets", return_value=[]
        ), patch.object(
            gcal_pl_helper,
            "folder_identity_matches",
            side_effect=lambda folder, *_args: folder == expected_folder,
        ), patch.object(gcal_pl_helper, "upsert_target") as upsert, patch(
            "parse_kak_pl._resolve_folder_pl",
            return_value=(expected_folder, "30"),
        ) as resolve:
            gcal_pl_helper._auto_enroll_folder_pl()

        resolve.assert_called_once_with(
            30,
            "Paket Aktif",
            "PK",
            is_ulang=False,
            strict_name=True,
        )
        self.assertEqual(upsert.call_args.kwargs["folder_name"], expected_folder)

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

    def test_stage_number_is_removed_from_new_and_updated_event_title(self):
        jadwal = _jadwal_lima_tahap()
        jadwal[0]["nama"] = "1. Upload Dokumen Penawaran"
        existing = [{
            "id": "old-event",
            "summary": "1. Upload Dokumen Penawaran - Paket Uji",
            "description": "Paket PL: 789\nPaket Uji",
            "extendedProperties": {"private": {
                "source_pl": "789", "source_stage_index": "1",
            }},
        }]
        service = _FakeService(items=existing)
        with patch.object(gcal_pl_helper, "_build_service", return_value=service):
            result = gcal_pl_helper.push_jadwal_pl_ke_gcal(
                "789", "Paket Uji", jadwal
            )

        self.assertTrue(result["ok"])
        self.assertEqual(service.events_api.updated_bodies[0]["summary"], "Upload Dokumen Penawaran - Paket Uji")


if __name__ == "__main__":
    unittest.main()
