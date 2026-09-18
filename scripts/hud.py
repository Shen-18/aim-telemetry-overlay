"""卡片舱 HUD 渲染器：布局由 cfg['layout'] 的控件 spec 列表驱动。

渲染层（widgets.py）与数据层（telemetry.py）解耦；本模块只做装配：
构造 RenderContext → 按布局构建控件 → 逐帧合成 1920×1080 RGBA。
默认布局 DEFAULT_LAYOUT 与 assets/default-config.json 的 layout 键保持一致。
"""
import numpy as np
from PIL import Image

from widgets import RenderContext, build_layout, render_frame, CANVAS_W, CANVAS_H

DEFAULT_LAYOUT = {
    "widgets": [
        {"type": "logo", "x": 60, "y": 48, "origin": "tl", "height": 56, "opacity": 0.95},
        {"type": "timing_bar", "x": 60, "y": 48, "origin": "tr",
         "w": 370, "h": 60, "opacity": 0.94},
        {"type": "bottom_bar", "x": 0, "y": 0, "origin": "bl",
         "h": 172, "max_deg": 160, "positive_left": True,
         "torque_pos_max": 20, "torque_neg_max": 10, "opacity": 0.95},
    ],
}


def g_ball_offset(ax, ay, cfg, radius):
    """反向惯性显示：加速时球向后（下），刹车向前（上）；左转向右，右转向左。"""
    d = float(cfg.get('g_ball_direction', -1))
    g = float(cfg['g_max'])
    return (d * np.clip(ay, -g, g) * radius / g, -d * np.clip(ax, -g, g) * radius / g)


def make_renderer(data, ts, cfg, info=None):
    """返回 frame(i) 闭包；dashboard.py 逐帧调用。

    info: CSV 元数据（vehicle/racer/lap_seconds），来自 telemetry 报告的 meta 字段。
    """
    ctx = RenderContext(data, cfg, info=info or {})
    layout = cfg.get('layout') or DEFAULT_LAYOUT
    widgets = build_layout(layout, ctx)
    def frame(i):
        im = render_frame(ctx, widgets, i)
        if (cfg['width'], cfg['height']) != im.size:
            # HUD consists mostly of line art and text. BICUBIC keeps edges clean while
            # avoiding the much costlier LANCZOS pass on every video frame.
            im = im.resize((cfg['width'], cfg['height']), Image.Resampling.BICUBIC)
        return im

    return frame
