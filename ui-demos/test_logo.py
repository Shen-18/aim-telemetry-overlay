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

    def test_thin_strokes_reach_full_opacity(self):
        """细笔画（Racing 下划线那类）必须实心。

        用全局 solid 参考值换算时细笔画永远到不了 255，在深色背景上显示成
        半透明灰线——这正是素材看起来「发虚」的原因。
        """
        blue = np.array([44, 80, 154], dtype=float)
        rgb = np.full((24, 44, 3), 255.0)
        rgb[3:12, 5:35] = blue               # 粗块：确定 solid 参考值
        rgb[15, 5:35] = (blue + 255.0) / 2   # 抗锯齿过渡的中间调
        rgb[19:21, 5:35] = blue              # 2px 细线
        alpha = MODULE.extract_alpha(rgb)
        self.assertEqual(alpha[0, 0], 0)          # 背景透明
        self.assertEqual(alpha[7, 20], 255)       # 粗块实心
        self.assertEqual(alpha[19, 20], 255)      # 细线实心（回归点）
        self.assertEqual(alpha[20, 20], 255)
        self.assertGreater(alpha[15, 20], 0)      # 贴边过渡仍保留
        self.assertLess(alpha[15, 20], 255)


if __name__ == "__main__":
    unittest.main()
