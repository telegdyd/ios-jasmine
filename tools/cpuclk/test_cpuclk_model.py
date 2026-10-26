"""Input-integrity checks; no device access or private fuse fixtures.

Run: python -m unittest discover -s tools/cpuclk -p test_*.py
"""
import unittest
from unittest.mock import mock_open, patch

import cpuclk_model as model


class FuseInputTests(unittest.TestCase):
    def parse(self, text):
        with patch("builtins.open", mock_open(read_data=text)):
            return model.parse_fuses("synthetic-fuses.txt")

    def test_split_field_concatenates_low_segment_first(self):
        # Four-bit RO field split across the end of a 64-bit fuse row.
        self.assertEqual(model.read_param({68: 5 << 61, 69: 1},
                                         [(68, 61, 63), (69, 0, 0)]), 13)

    def test_missing_row_is_not_zero(self):
        with self.assertRaisesRegex(ValueError, "missing fuse row 69"):
            model.read_param({68: 0}, [(68, 61, 63), (69, 0, 0)])

    def test_cluster_model_rejects_incomplete_capture_before_dt_access(self):
        for cluster in model.CLUSTERS:
            with self.subTest(cluster=cluster):
                rows = {row: 0 for row in model.required_rows(cluster)}
                del rows[71]
                with self.assertRaisesRegex(ValueError, "missing fuse rows.*71"):
                    model.cprh_model({}, rows, lambda _: None, cluster)

    def test_identical_repeated_capture_is_allowed(self):
        self.assertEqual(self.parse("SWEET OSM: fuse 38 0x1\n38 0x1\n"), {38: 1})

    def test_mixed_conflicting_captures_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "conflicting values for fuse row 38"):
            self.parse("38 0x1\nSWEET OSM: fuse 38 0x2\n")

    def test_wider_than_hardware_row_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "exceeds 64 bits"):
            self.parse("38 0x10000000000000000\n")


if __name__ == "__main__":
    unittest.main()
