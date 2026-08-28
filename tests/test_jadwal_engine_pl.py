from datetime import datetime, timedelta
import unittest
from unittest.mock import patch

import jadwal_engine
import jadwal_engine_pl


class JadwalEnginePlTest(unittest.TestCase):
    def _custom_schedule(self):
        return [
            {
                "mulai": datetime(2026, 9, 1, 7, 11),
                "selesai": datetime(2026, 9, 3, 18, 22),
            },
            {
                "mulai": datetime(2026, 9, 8, 13, 5),
                "selesai": datetime(2026, 9, 8, 13, 7),
            },
            {
                "mulai": datetime(2026, 9, 10, 21, 30),
                "selesai": datetime(2026, 9, 12, 6, 45),
            },
            {
                "mulai": datetime(2026, 9, 15, 10, 0),
                "selesai": datetime(2026, 9, 15, 10, 1),
            },
            {
                "mulai": datetime(2026, 9, 20, 23, 59),
                "selesai": datetime(2026, 9, 30, 0, 1),
            },
        ]

    def test_custom_keeps_each_stage_exactly_as_entered(self):
        custom = self._custom_schedule()

        jadwal = jadwal_engine_pl.hitung_jadwal_pl_custom(custom)

        self.assertEqual(
            [(row["mulai"], row["selesai"]) for row in jadwal],
            [(row["mulai"], row["selesai"]) for row in custom],
        )
        self.assertEqual(
            [row["nama"] for row in jadwal],
            jadwal_engine_pl.NAMA_TAHAP_PL,
        )

    def test_custom_rejects_incomplete_or_invalid_stage(self):
        custom = self._custom_schedule()

        with self.assertRaisesRegex(ValueError, "tepat 5"):
            jadwal_engine_pl.hitung_jadwal_pl_custom(custom[:4])

        custom[2]["selesai"] = custom[2]["mulai"]
        with self.assertRaisesRegex(ValueError, "T3"):
            jadwal_engine_pl.hitung_jadwal_pl_custom(custom)

    def test_auto_fill_custom_uses_explicit_schedule_for_payload(self):
        custom = self._custom_schedule()
        scraped = {
            "csrf": "csrf",
            "id": "paket-id",
            "rows": [
                {
                    "index": index,
                    "hidden": {f"jadwalList[{index}].dtj_id": str(index)},
                    "name_mulai": f"jadwalList[{index}].dtj_tglawal",
                    "name_selesai": f"jadwalList[{index}].dtj_tglakhir",
                }
                for index in range(5)
            ],
        }

        with patch.object(jadwal_engine_pl, "scrap_hidden_fields_pl", return_value=scraped):
            result = jadwal_engine_pl.auto_fill_jadwal_pl(
                "kode-paket",
                mode="custom",
                jadwal_custom=custom,
            )

        self.assertEqual(result["jadwal_list"], jadwal_engine_pl.hitung_jadwal_pl_custom(custom))
        self.assertEqual(
            result["payload"]["jadwalList[2].dtj_tglawal"],
            "10-09-2026 21:30",
        )
        self.assertEqual(
            result["payload"]["jadwalList[4].dtj_tglakhir"],
            "30-09-2026 00:01",
        )

    def test_exact_seventeen_is_valid_start_time(self):
        tgl_mulai = datetime(2026, 8, 13, 17, 0)

        self.assertTrue(jadwal_engine.is_jam_kerja(tgl_mulai))
        self.assertEqual(jadwal_engine.geser_ke_jam_kerja(tgl_mulai), tgl_mulai)
        for mode_fn in (
            jadwal_engine_pl.hitung_jadwal_pl,
            jadwal_engine_pl.hitung_jadwal_pl_standar,
            jadwal_engine_pl.hitung_jadwal_pl_cepat,
            jadwal_engine_pl.hitung_jadwal_pl_santai,
        ):
            with self.subTest(mode=mode_fn.__name__):
                self.assertEqual(mode_fn(tgl_mulai)[0]["mulai"], tgl_mulai)

    def test_one_minute_after_seventeen_is_shifted_to_work_hours(self):
        shifted = jadwal_engine.geser_ke_jam_kerja(datetime(2026, 8, 13, 17, 1))

        self.assertEqual(shifted.hour, 8)
        self.assertEqual(shifted.minute, 0)

    def test_t5_starts_one_minute_after_t4_for_all_modes(self):
        tgl_mulai = datetime(2026, 8, 6, 8, 0)

        for mode_fn in (
            jadwal_engine_pl.hitung_jadwal_pl,
            jadwal_engine_pl.hitung_jadwal_pl_standar,
            jadwal_engine_pl.hitung_jadwal_pl_cepat,
        ):
            with self.subTest(mode=mode_fn.__name__):
                jadwal = mode_fn(tgl_mulai)
                t4 = jadwal[3]
                t5 = jadwal[4]
                self.assertEqual(t5["mulai"], t4["selesai"] + timedelta(minutes=1))

    def test_24_jam_preserves_input_time_and_calendar_duration(self):
        mulai = datetime(2026, 8, 26, 21, 30)
        jadwal = jadwal_engine_pl.hitung_jadwal_pl_24_jam(mulai)
        self.assertEqual(jadwal[0]["mulai"], mulai)
        self.assertEqual(jadwal[0]["selesai"], datetime(2026, 8, 31, 10, 0))
        self.assertEqual(jadwal[1]["mulai"], datetime(2026, 8, 31, 10, 1))
        self.assertEqual(jadwal[1]["selesai"], datetime(2026, 8, 31, 11, 5))
        self.assertEqual(jadwal[2]["mulai"], datetime(2026, 8, 31, 11, 6))
        self.assertEqual(jadwal[2]["selesai"], datetime(2026, 9, 1, 11, 6))
        self.assertEqual(jadwal[3]["mulai"], datetime(2026, 9, 1, 11, 7))
        self.assertEqual(jadwal[3]["selesai"], datetime(2026, 9, 1, 17, 0))
        self.assertEqual(jadwal[4]["mulai"], datetime(2026, 9, 1, 17, 1))
        self.assertEqual(jadwal[4]["selesai"] - jadwal[4]["mulai"], timedelta(days=10))
        self.assertLessEqual(jadwal[3]["selesai"].hour, 17)

    def test_24_jam_non_evening_start_keeps_same_finish_time(self):
        mulai = datetime(2026, 8, 26, 16, 30)
        jadwal = jadwal_engine_pl.hitung_jadwal_pl_24_jam(mulai)
        self.assertEqual(jadwal[0]["selesai"], datetime(2026, 8, 31, 16, 30))

    def test_24_jam_seventeen_oclock_uses_ten_oclock_finish(self):
        mulai = datetime(2026, 8, 26, 17, 0)
        jadwal = jadwal_engine_pl.hitung_jadwal_pl_24_jam(mulai)
        self.assertEqual(jadwal[0]["selesai"], datetime(2026, 8, 31, 10, 0))

    def test_normal_3_minggu_keeps_normal_t1_to_t4_and_extends_t5(self):
        tgl_mulai = datetime(2026, 8, 6, 8, 0)
        normal = jadwal_engine_pl.hitung_jadwal_pl(tgl_mulai)
        tiga_minggu = jadwal_engine_pl.hitung_jadwal_pl_3_minggu(tgl_mulai)

        self.assertEqual(tiga_minggu[:4], normal[:4])
        self.assertEqual(tiga_minggu[4]["mulai"], normal[4]["mulai"])
        expected_selesai = jadwal_engine.geser_ke_hari_kerja(
            (normal[4]["mulai"] + timedelta(days=21)).replace(
                hour=16, minute=0, second=0, microsecond=0
            )
        ).replace(hour=16, minute=0, second=0, microsecond=0)
        self.assertEqual(tiga_minggu[4]["selesai"], expected_selesai)

    def test_santai_keeps_normal_t1_t2_and_extends_evaluation_to_two_workdays(self):
        tgl_mulai = datetime(2026, 8, 6, 8, 0)
        normal = jadwal_engine_pl.hitung_jadwal_pl(tgl_mulai)
        santai = jadwal_engine_pl.hitung_jadwal_pl_santai(tgl_mulai)

        self.assertEqual(santai[:2], normal[:2])
        self.assertEqual(santai[2]["mulai"], normal[2]["mulai"])
        expected_t3_selesai = jadwal_engine_pl._tambah_hari_kerja(
            santai[2]["mulai"], 2
        ).replace(hour=16, minute=0, second=0, microsecond=0)
        self.assertEqual(santai[2]["selesai"], expected_t3_selesai)
        expected_t4_mulai = jadwal_engine_pl._tambah_hari_kerja(
            santai[2]["mulai"], 1
        ).replace(hour=9, minute=0, second=0, microsecond=0)
        self.assertEqual(santai[3]["mulai"], expected_t4_mulai)
        self.assertEqual(santai[3]["mulai"].time().isoformat(timespec="minutes"), "09:00")
        self.assertEqual(santai[3]["selesai"].time().isoformat(timespec="minutes"), "15:45")
        self.assertEqual(santai[4]["mulai"], santai[3]["selesai"] + timedelta(minutes=1))

    def test_santai_preserves_evening_input_time(self):
        mulai = datetime(2026, 8, 27, 19, 0)
        jadwal = jadwal_engine_pl.hitung_jadwal_pl_santai(mulai)

        self.assertEqual(jadwal[0]["mulai"], mulai)
        self.assertEqual(jadwal[0]["selesai"], datetime(2026, 9, 1, 19, 0))
        self.assertEqual(jadwal[1]["mulai"], datetime(2026, 9, 1, 19, 1))
