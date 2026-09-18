"""UI demo 布局。

当前布局 = 「卡片舱」细调版 v6（2026-09-16，按用户反馈第五轮调整）：
  - 底部通栏信息带（bottom_bar，贴满底边与左右两端，各区块等高、标题在最下排）：
    GPS 迷你轨迹 → 电池双层（SOC/VOLT 上排，POWER/CURRENT 下排）→
    转向完整圆环（绿色光标 + 中心数字，左正右负）→
    速度（数字 + km/h 在值右侧 + 条形图 0..120 均分刻度数字）→
    四轮扭矩（条形+数字）→ 踏板 → G 力（ACC X/Y 上下两侧）
  - 顶部中央横向计时条（timing_bar）：车辆 · 当前圈用时 · 第几圈
  - logo 左上角（顶角边距 60px）
  - 画面其余部分完全净空

每个布局 = 控件 spec 列表（坐标均为 1920×1080 画布）。
origin: tl/tc/tr 上排、bl/bc/br 下排、ml/mr 垂直居中（c = 水平居中）。
"""

CARDS_V2 = {
    "id": "cards",
    "name": "卡片舱 · 细调版 v6",
    "desc": "底部通栏信息带（GPS/电池双层/转向环/速度/四轮扭矩/踏板/G 力，等高、"
            "标题在最下、贴满底边与左右两端）；顶部中央横向计时条；logo 左上；"
            "画面其余部分完全净空。",
    "widgets": [
        {"type": "logo", "x": 60, "y": 48, "origin": "tl", "height": 56, "opacity": 0.95},

        # 右上：计时条（时间为主，车辆/车手辅助），高度与左上角 logo 一致
        {"type": "timing_bar", "x": 60, "y": 48, "origin": "tr",
         "w": 370, "h": 60, "opacity": 0.94},

        # 底部通栏信息带：贴满底边与左右两端
        {"type": "bottom_bar", "x": 0, "y": 0, "origin": "bl",
         "h": 172, "max_deg": 160, "positive_left": True, "speed_max": 120,
         "torque_pos_max": 20, "torque_neg_max": 10, "opacity": 0.95},
    ],
}

DEMOS = {d["id"]: d for d in (CARDS_V2,)}

