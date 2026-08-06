from datetime import datetime, timedelta
import unittest

import jadwal_engine_pl


class JadwalEnginePlTest(unittest.TestCase):
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
