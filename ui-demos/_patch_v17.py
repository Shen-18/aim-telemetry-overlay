# -*- coding: utf-8 -*-
"""v17：区块重排（GPS 收窄/电池加宽对称/速度加宽不居中/gforce 对称留白 220）、
Y 竖排恢复、扭矩零线 3:1、时间块缩窄。"""
from pathlib import Path

p = Path(__file__).resolve().parent / "widgets.py"
s = p.read_text(encoding="utf-8")

# 1. 区块边界
old = '''    BASE_SECTIONS = [
        ("gps", 0, 360), ("battery", 360, 565), ("steer", 565, 765),
        ("speed", 765, 1155), ("gforce", 1155, 1410), ("pedals", 1410, 1570),
        ("motors", 1570, 1920)
    ]'''
new = '''    BASE_SECTIONS = [
        ("gps", 0, 315), ("battery", 315, 600), ("steer", 600, 800),
        ("speed", 800, 1215), ("gforce", 1215, 1435), ("pedals", 1435, 1570),
        ("motors", 1570, 1920)
    ]'''
assert old in s, "sections"
s = s.replace(old, new)

# 2. GPS 地图宽度随之收窄
old = '        self.map_w = int(round(float(spec.get("map_w", 330)) * s))'
new = '        self.map_w = int(round(float(spec.get("map_w", 285)) * s))'
assert old in s, "map_w"
s = s.replace(old, new)

# 3. 电池：区块内左右留白对称（不再贴 PAD），列距 106
old = "        col_w = int(round(99 * s))"
assert s.count(old) == 2, "col_w"
s = s.replace(old, "        col_w = int(round(106 * s))")
old = "        bx0 = x0 + P + (x1 - x0 - 2 * P - block_w) / 2"
assert s.count(old) == 2, "bx0"
s = s.replace(old, "        bx0 = x0 + (x1 - x0 - block_w) / 2  # 左右留白对称")

# 4. G 力：圆环位置 = 左(Y列)22 + 盘 + 右22 对称
old = '''        r = int(round(52 * s))
        cx, cy = (x0 + x1) / 2, top + int(round(70 * s))'''
assert s.count(old) == 2, "gforce cx"
new = '''        r = int(round(52 * s))
        cx, cy = x0 + P + int(round(40 * s)) + int(round(22 * s)) + r, top + int(round(70 * s))'''
s = s.replace(old, new)

# 5. Y 恢复竖排：Y 在数字上方，右对齐列（右缘距圆环 22 = 右侧留白）
old = '''        fonts.text(dr, (cx - r - int(round(8 * s)), cy), f"Y {fmt(ay, 2)}", int(round(13 * s)),
                   with_alpha(WHITE, 205 * alpha), "bold", anchor="rm")'''
new = '''        ycol = cx - r - int(round(22 * s))
        fonts.text(dr, (ycol, cy - int(round(13 * s))), "Y", int(round(11 * s)),
                   with_alpha(WHITE, 170 * alpha), "regular", anchor="rs")
        fonts.text(dr, (ycol, cy), fmt(ay, 2), int(round(14 * s)), WHITE,
                   "bold", anchor="rs")'''
assert old in s, "Y stack"
s = s.replace(old, new)

# 6. 扭矩零线：固定 3:1（正:负），量程只影响填充比例
old = """            neg_h = bar_h * self.torque_neg_max / (self.torque_pos_max + self.torque_neg_max)
            zero_y = by1 - neg_h
            dr.line((gx + 1, zero_y, gx + bar_w - 1, zero_y),"""
new = """            neg_h = bar_h * 0.25  # 零线固定 3:1（正:负）
            zero_y = by1 - neg_h
            dr.line((gx + 1, zero_y, gx + bar_w - 1, zero_y),"""
assert old in s, "torque base"
s = s.replace(old, new)

old = """            neg_h = bar_h * self.torque_neg_max / (self.torque_pos_max + self.torque_neg_max)
            zero_y = by1 - neg_h
            pos_h = bar_h - neg_h"""
new = """            neg_h = bar_h * 0.25  # 零线固定 3:1（正:负）
            zero_y = by1 - neg_h
            pos_h = bar_h - neg_h"""
assert old in s, "torque paint"
s = s.replace(old, new)

p.write_text(s, encoding="utf-8")
print("widgets.py v17 patched")

# 7. 时间块缩窄：layouts / default-config / hud
l = Path(__file__).resolve().parent / "layouts.py"
t = l.read_text(encoding="utf-8")
old = '"w": 430, "h": 60, "opacity": 0.94},'
assert old in t, "layouts timing"
t = t.replace(old, '"w": 370, "h": 60, "opacity": 0.94},')
l.write_text(t, encoding="utf-8")

import json
dc = Path(__file__).resolve().parent.parent / "assets" / "default-config.json"
cfg = json.loads(dc.read_text(encoding="utf-8"))
assert cfg["layout"]["widgets"][1]["type"] == "timing_bar"
cfg["layout"]["widgets"][1]["w"] = 370
dc.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

h = Path(__file__).resolve().parent.parent / "scripts" / "hud.py"
s = h.read_text(encoding="utf-8")
old = '"w": 430, "h": 60, "opacity": 0.94},'
assert old in s, "hud timing"
s = s.replace(old, '"w": 370, "h": 60, "opacity": 0.94},')
h.write_text(s, encoding="utf-8")
print("timing width 430 -> 370 synced")
