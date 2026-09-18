"""Regression checks for the white-background logo cutout."""
import importlib.util
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("make_logo_white.py")
SPEC = importlib.util.spec_from_file_location("make_logo_white", MODULE_PATH)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class LogoAlphaTests(unittest.TestCase):
    def test_gray_antialias_pixels_are_not_cut_into_transparent_cracks(self):
        rgb = np.array([[[255, 255, 255], [120, 120, 120], [44, 80, 154]]], dtype=float)
        alpha = MODULE.extract_alpha(rgb)[0]
        self.assertEqual(alpha[0], 0)
        self.assertGreater(alpha[1], 160)
        self.assertGreater(alpha[2], 240)


if __name__ == "__main__":
    unittest.main()
