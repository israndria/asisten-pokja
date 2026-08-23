import unittest

import input_ba_engine
import kk_evaluasi_engine
import penawaran_engine


class ParticipantCapacityTests(unittest.TestCase):
    def test_sheet6_blocks_are_capped_at_ten(self):
        self.assertEqual(penawaran_engine._block_starts(4), [0, 9, 18, 27])
        self.assertEqual(len(penawaran_engine._block_starts(11)), 10)
        self.assertEqual(penawaran_engine._block_starts(11)[-1], 81)
        formula = penawaran_engine._sheet6_block_lookup_formula(38, 12, 10)
        self.assertIn("$L$38", formula)
        self.assertIn("'6. Harga Penawaran'!$CD$1", formula)

    def test_input_ba_uses_canonical_matrix_c_to_l(self):
        self.assertEqual(input_ba_engine.MAX_PARTICIPANTS, 10)
        self.assertEqual(input_ba_engine._COL_PESERTA[1], 3)
        self.assertEqual(input_ba_engine._COL_PESERTA[4], 6)
        self.assertEqual(input_ba_engine._COL_PESERTA[10], 12)
        self.assertEqual(input_ba_engine._LEGACY_VIEW_COLS[4], 9)

    def test_kk_capacity_is_ten(self):
        self.assertEqual(kk_evaluasi_engine.MAX_PARTICIPANTS, 10)
        self.assertEqual(2 + kk_evaluasi_engine.MAX_PARTICIPANTS, 12)
        self.assertTrue(kk_evaluasi_engine._is_formula("=A1"))
        self.assertFalse(kk_evaluasi_engine._is_formula("Peserta 10"))


if __name__ == "__main__":
    unittest.main()
