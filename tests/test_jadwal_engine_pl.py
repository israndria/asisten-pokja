from datetime import datetime, timedelta
import unittest

import jadwal_engine
import jadwal_engine_pl


class JadwalEnginePlTest(unittest.TestCase):
    def test_exact_seventeen_is_valid_start_time(self):
        tgl_mulai = datetime(2026, 8, 13, 17, 0)

        self.assertTrue(jadwal_engine.is_jam_kerja(tgl_mulai))
        self.assertEqual(jadwal_engine.geser_ke_jam_kerja(tgl_mulai), tgl_mulai)
        for mode_fn in (
            jadwal_engine_pl.hitung_jadwal_pl,
            jadwal_engine_pl.hitung_jadwal_pl_standar,
            jadwal_engine_pl.hitung_jadwal_pl_cepat,
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
