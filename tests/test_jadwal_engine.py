from datetime import datetime, timedelta
import unittest

import jadwal_engine


class JadwalEngineTenderTest(unittest.TestCase):
    def test_t10_masa_sanggah_minimum_lima_hari(self):
        jadwal = jadwal_engine.hitung_jadwal(datetime(2026, 8, 17, 8, 0))
        t10 = jadwal[9]

        self.assertGreaterEqual(
            t10["selesai"] - t10["mulai"],
            timedelta(days=5),
        )
        self.assertEqual(t10["selesai"], datetime(2026, 9, 2, 8, 0))

    def test_t11_starts_when_t10_ends(self):
        jadwal = jadwal_engine.hitung_jadwal(datetime(2026, 8, 17, 8, 0))

        self.assertEqual(jadwal[10]["mulai"], jadwal[9]["selesai"])
