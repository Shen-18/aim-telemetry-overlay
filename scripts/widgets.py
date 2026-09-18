"""叠加层控件框架（ui-demos 共用）。

设计目标：把「一个控件 = 一份 spec（类型 + 位置 + 选项）」作为最小单元，
任何布局都只是控件 spec 的列表。这与将来在自研软件里做
「自由摆放 / 自选数据」的方向一致——软件里拖出来的每个控件，
序列化后就是这里的一份 spec。

扩展一个新控件：继承 Widget，注册到 REGISTRY，即可在任意布局 JSON 里引用。
"""
from __future__ import annotations

import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

CANVAS_W, CANVAS_H = 1920, 1080

HERE = Path(__file__).resolve().parent
LOGO_PATH = HERE / "assets" / "logo_white.png"
FONT_DIR = HERE / "assets" / "fonts"

WHITE = (255, 255, 255, 255)
GREEN = (0, 232, 54, 255)
RED = (255, 64, 48, 255)


def with_alpha(color, alpha):
    return (color[0], color[1], color[2], int(alpha))


def scale_color(color, factor):
    """按 0..1 整体缩放颜色透明度。"""
    return (color[0], color[1], color[2], int(color[3] * factor))


# ---------------------------------------------------------------- 字体

class Fonts:
    """按 (家族, 字号) 懒加载。家族: regular / semibold / bold"""

    FILES = {
        "regular": "Formula1-Display-Regular.ttf",
        "bold": "Formula1-Display-Bold.ttf",
        "semibold": "Titillium-SemiBold.ttf",  # 备用：F1 Display 无中间字重
    }

    def __init__(self):
        self._cache = {}

    def get(self, size, family="regular"):
        key = (family, int(size))
        if key not in self._cache:
            path = FONT_DIR / self.FILES[family]
            self._cache[key] = ImageFont.truetype(str(path), int(size))
        return self._cache[key]

    def text(self, dr, xy, s, size, fill=WHITE, family="regular", anchor="la",
             letter_spacing=0, shadow=True):
        if letter_spacing:
            self._spaced(dr, xy, s, size, fill, family, anchor, letter_spacing, shadow)
            return
        dr.text(xy, s, font=self.get(size, family), fill=fill, anchor=anchor,
                stroke_width=1 if shadow else 0, stroke_fill=(0, 0, 0, 110) if shadow else None)

    def _spaced(self, dr, xy, s, size, fill, family, anchor, spacing, shadow):
        font = self.get(size, family)
        widths = [dr.textlength(ch, font=font) + spacing for ch in s]
        total = sum(widths) - spacing
        x, y = xy
        if anchor[0] == "m":
            x -= total / 2
        elif anchor[0] == "r":
            x -= total
        for ch, w in zip(s, widths):
            dr.text((x, y), ch, font=font, fill=fill, anchor="l" + anchor[1],
                    stroke_width=1 if shadow else 0, stroke_fill=(0, 0, 0, 110) if shadow else None)
            x += w


# ---------------------------------------------------------------- 数据上下文

def fmt(value, digits=0, dash="--"):
    return dash if not np.isfinite(value) else f"{value:.{digits}f}"


def fmt_clock(seconds):
    """秒 → m:ss.t 计时格式；无效值显示 --:--.-"""
    if not np.isfinite(seconds) or seconds < 0:
        return "--:--.-"
    m = int(seconds // 60)
    s = seconds - m * 60
    return f"{m}:{s:04.1f}"


def draw_clock(dr, fonts, xy, text, size, fill, family="bold", anchor="mm"):
    """渲染 m:ss.d 计时文本（垂直居中锚点）。

    Formula1 Display 的冒号字形接近句点，冒号由两个方形点手工绘制，
    其余字符仍用该字体：分秒之间读作冒号，秒的小数读作句点。
    """
    font = fonts.get(size, family)
    parts = text.split(":")
    cw = size * 0.18
    total = sum(dr.textlength(part, font=font) for part in parts) + cw * (len(parts) - 1)
    x, cy = xy
    if anchor[0] == "m":
        x -= total / 2
    elif anchor[0] == "r":
        x -= total
    dot = max(2.0, size * 0.09)
    for k, part in enumerate(parts):
        if k:
            cxx = x + cw / 2
            dr.rectangle((cxx - dot / 2, cy - size * 0.20 - dot / 2,
                          cxx + dot / 2, cy - size * 0.20 + dot / 2), fill=fill)
            dr.rectangle((cxx - dot / 2, cy + size * 0.15 - dot / 2,
                          cxx + dot / 2, cy + size * 0.15 + dot / 2), fill=fill)
            x += cw
        dr.text((x, cy), part, font=font, fill=fill, anchor="l" + anchor[1])
        x += dr.textlength(part, font=font)


def steer_text(value):
    return "--" if not np.isfinite(value) else f"{value:+.0f}°"


def pedal_text(value):
    return "--" if not np.isfinite(value) else f"{np.clip(value,0,100):.0f}"


def speed_ticks():
    return [0,30,60,90,120]


def speed_fraction(value):
    return float(np.clip(value,0,120)/120) if np.isfinite(value) else 0.0


class RenderContext:
    """包装 prepare() 产出的逐帧数组，供所有控件统一取数。

    info: 来自 CSV 元数据的标量信息（vehicle、lap_seconds 等），供计时类控件使用。
    """

    def __init__(self, data, cfg, info=None):
        self.data = data
        self.cfg = cfg
        self.info = info or {}
        self.fonts = Fonts()
        self.frame_count = len(data["Video Time"])
        self.logo = Image.open(LOGO_PATH).convert("RGBA")
        self.width = int(cfg.get("width", CANVAS_W))
        self.height = int(cfg.get("height", CANVAS_H))
        self.scale = self.width / float(CANVAS_W)
        self._route_cache = {}
        self.motor_slots = [s for s in ("FL", "FR", "RL", "RR")
                            if cfg["motors"][s]["active"]] or ["FL", "FR", "RL", "RR"]

    def get(self, key, i):
        arr = self.data[key]
        return arr[i] if i < len(arr) else float("nan")

    def route(self, w, h):
        """把整段 GPS 轨迹投影到 w×h 的局部坐标（带缓存）。"""
        if w in self._route_cache:
            return self._route_cache[w]
        lat = self.data["Route Latitude"]
        lon = self.data["Route Longitude"]
        pts = None
        if len(lat) > 1:
            lat0 = float(np.median(lat))
            lon0 = float(np.median(lon))
            rx = (lon - lon0) * 111320 * math.cos(math.radians(lat0))
            ry = -(lat - lat0) * 111320
            span_x = max(float(np.ptp(rx)), 1e-6)
            span_y = max(float(np.ptp(ry)), 1e-6)
            scale = min((w - 8) / span_x, (h - 8) / span_y)
            mx = (rx.max() + rx.min()) / 2
            my = (ry.max() + ry.min()) / 2
            x0 = w / 2
            y0 = h / 2
            pts = np.stack([(rx - mx) * scale + x0, (ry - my) * scale + y0], axis=1)
        self._route_cache[w] = pts
        return pts

    def live_route_xy(self, i, w, h):
        """当前帧 GPS 点在局部坐标里的位置；缺失返回 None。"""
        pts = self.route(w, h)
        route_time = self.data["Route Time"]
        if pts is None or i >= self.frame_count or len(route_time) != len(pts):
            return None
        query = self.get("Data Time", i)
        if not np.isfinite(query) or query < route_time[0] or query > route_time[-1]:
            return None

        right = int(np.searchsorted(route_time, query, side="left"))
        if right < len(route_time) and np.isclose(route_time[right], query, rtol=0, atol=1e-8):
            return tuple(pts[right])
        if right == 0 or right >= len(route_time):
            return None

        left = right - 1
        gap = float(route_time[right] - route_time[left])
        if gap <= 0 or gap > float(self.cfg.get("max_gap_seconds", 0.5)):
            return None
        ratio = float((query - route_time[left]) / gap)
        return tuple(pts[left] + (pts[right] - pts[left]) * ratio)


# ---------------------------------------------------------------- 基类

class Widget:
    TYPE = "widget"
    DEFAULT_SOURCE = None  # 控件默认绑定的数据键（子类可覆盖）

    def __init__(self, spec, ctx: RenderContext):
        self.spec = spec
        self.ctx = ctx
        self.s = ctx.scale
        self.opacity = float(spec.get("opacity", 1.0))
        self.origin = spec.get("origin", "tl")
        self.x = float(spec.get("x", 0)) * self.s
        self.y = float(spec.get("y", 0)) * self.s
        self.card = spec.get("card")  # {"title": "..."} 时绘制卡片底

    def place(self, w, h):
        """根据 origin 与自身尺寸换算画布上的左上角。
        origin: tl/tc/tr（上排）、bl/bc/br（下排）、ml/mr（左右垂直居中），c = 水平居中。"""
        cw, ch = self.ctx.width, self.ctx.height
        if self.origin == "tl":
            return self.x, self.y
        if self.origin in ("tc", "bc"):
            cx = cw / 2 - w / 2
            return (cx, self.y) if self.origin == "tc" else (cx, ch - self.y - h)
        if self.origin in ("ml", "mr"):
            cy = ch / 2 - h / 2
            return (self.x, cy) if self.origin == "ml" else (cw - self.x - w, cy)
        if self.origin == "tr":
            return cw - self.x - w, self.y
        if self.origin == "bl":
            return self.x, ch - self.y - h
        return cw - self.x - w, ch - self.y - h  # br

    def size(self):
        raise NotImplementedError

    # 子类实现
    def paint_base(self, dr, ox, oy):
        pass

    def paint(self, dr, i, ox, oy):
        pass

    # 通用装饰
    def draw_card(self, dr, ox, oy, w, h):
        title = self.card.get("title")
        bg = self.spec.get("card_bg", 58)
        line = self.spec.get("card_line", 62)
        radius = int(round(float(self.spec.get("card_radius", 12)) * self.s))
        dr.rounded_rectangle((ox, oy, ox + w, oy + h), radius=radius,
                             fill=(8, 10, 14, bg), outline=with_alpha(WHITE, line), width=max(1, int(round(1 * self.s))))
        if title:
            self.ctx.fonts.text(dr, (ox + 14 * self.s, oy + 8 * self.s), title, int(round(12 * self.s)),
                                with_alpha(WHITE, 150), "regular", letter_spacing=max(1, int(round(2 * self.s))))

    def content_origin(self, w, h):
        return self.place(w, h)


def draw_lines(dr, pts, fill, width):
    if pts is not None and len(pts) > 1:
        dr.line([tuple(p) for p in pts], fill=fill, width=width, joint="curve")


# ---------------------------------------------------------------- 控件实现

class LogoWidget(Widget):
    """纯白 SCUT Racing logo（左上角）。"""

    TYPE = "logo"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.height = int(round(float(spec.get("height", 40)) * self.s))
        w, h = self.size()
        self.image = self.ctx.logo.resize((w, h), Image.Resampling.LANCZOS)
        if self.opacity < 1.0:
            a = self.image.getchannel("A").point(lambda v: int(v * self.opacity))
            self.image.putalpha(a)

    def size(self):
        ratio = self.ctx.logo.width / self.ctx.logo.height
        return int(round(self.height * ratio)), self.height

    def paint_base(self, dr, ox, oy):
        dr._image.alpha_composite(self.image, (int(ox), int(oy)))

    def paint(self, dr, i, ox, oy):
        pass


class TorqueBarsWidget(Widget):
    """四电机扭矩柱：柱高=|扭矩|/max；无数据的槽位保留空框。
    columns=4 时单行 FL FR RL RR；columns=2 时两行网格（前轮在上、后轮在下）。"""

    TYPE = "torque_bars"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.bar_w = int(spec.get("bar_w", 20))
        self.bar_h = int(spec.get("bar_h", 48))
        self.gap = int(spec.get("gap", 12))
        self.columns = int(spec.get("columns", 4))
        self.labels = bool(spec.get("labels", True))
        self.max_nm = float(spec.get("torque_max", 0)) or float(ctx.cfg["torque_max_nm"])

    def size(self):
        rows = math.ceil(4 / self.columns)
        w = self.columns * self.bar_w + (self.columns - 1) * self.gap
        cell = self.bar_h + (14 if self.labels else 2)
        h = rows * cell + (rows - 1) * 8
        return w, h

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        label_h = 14 if self.labels else 2
        rows = math.ceil(4 / self.columns)
        for k, slot in enumerate(("FL", "FR", "RL", "RR")):
            row, col = k // self.columns, k % self.columns
            x = ox + col * (self.bar_w + self.gap)
            y = oy + row * (self.bar_h + label_h + 8) + self.bar_h
            active = slot in self.ctx.motor_slots
            dr.rectangle((x, y - self.bar_h, x + self.bar_w, y),
                         outline=with_alpha(WHITE, 95 * alpha), width=1)
            if active:
                v = self.ctx.get(slot + " Torque", i)
                if np.isfinite(v):
                    h = max(0.0, min(1.0, abs(v) / self.max_nm)) * (self.bar_h - 1)
                    if h >= 1:
                        dr.rectangle((x + 1, y - h, x + self.bar_w - 1, y - 1), fill=scale_color(GREEN, alpha))
            if self.labels:
                self.ctx.fonts.text(dr, (x + self.bar_w / 2, y + 3), slot, 11,
                                    with_alpha(WHITE, 150 * alpha), anchor="ma")


class TorqueStripWidget(Widget):
    """贴屏幕上缘的极简扭矩条：四段、高度随扭矩变化，几乎不占视野。"""

    TYPE = "torque_strip"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.width = int(spec.get("width", CANVAS_W - 2 * int(spec.get("inset", 0))))
        self.max_h = int(spec.get("max_h", 10))
        self.max_nm = float(spec.get("torque_max", 0)) or float(ctx.cfg["torque_max_nm"])

    def size(self):
        return self.width, self.max_h + 2

    def paint(self, dr, i, ox, oy):
        seg = self.width / 4
        alpha = self.opacity
        for k, slot in enumerate(("FL", "FR", "RL", "RR")):
            x0 = ox + k * seg
            v = self.ctx.get(slot + " Torque", i)
            level = min(1.0, abs(v) / self.max_nm) if np.isfinite(v) else 0.0
            h = level * self.max_h
            dr.line((x0 + 2, oy + self.max_h, x0 + seg - 2, oy + self.max_h),
                    fill=with_alpha(WHITE, 60 * alpha), width=1)
            if h >= 1:
                dr.rectangle((x0 + 2, oy + self.max_h - h, x0 + seg - 2, oy + self.max_h - 1),
                             fill=scale_color(GREEN, 170 * alpha))


class SpeedDialWidget(Widget):
    """速度圆环 + 数字 + 功率；紧凑版替代原右下大表盘。"""

    TYPE = "speed_dial"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.radius = int(spec.get("radius", 78))
        self.number_size = int(spec.get("number_size", 54))
        self.show_arc = bool(spec.get("arc", True))
        self.show_power = bool(spec.get("power", True))
        self.max_kmh = float(spec.get("speed_max", 0)) or float(ctx.cfg["speed_max_kmh"])

    def size(self):
        w = self.radius * 2 + 8
        h = self.radius * 2 + 8 + (30 if self.show_power else 0)
        return w, h

    def paint(self, dr, i, ox, oy):
        cx = ox + self.radius + 4
        cy = oy + self.radius + 4
        r = self.radius
        alpha = self.opacity
        v = self.ctx.get("VehSpd", i)
        if self.show_arc:
            dr.arc((cx - r, cy - r, cx + r, cy + r), 135, 405,
                   fill=with_alpha(WHITE, 55 * alpha), width=3)
            if np.isfinite(v) and v > 0:
                sweep = min(v, self.max_kmh) / self.max_kmh * 270
                dr.arc((cx - r, cy - r, cx + r, cy + r), 135, 135 + sweep,
                       fill=with_alpha(WHITE, 235 * alpha), width=3)
        self.ctx.fonts.text(dr, (cx, cy - self.number_size * 0.18), fmt(v),
                            self.number_size, WHITE, "bold", anchor="mm")
        self.ctx.fonts.text(dr, (cx, cy + self.number_size * 0.62), "km/h", 13,
                            with_alpha(WHITE, 160 * alpha), anchor="mm")
        if self.show_power:
            p = self.ctx.get("Power", i)
            self.ctx.fonts.text(dr, (cx, oy + self.radius * 2 + 12), f"{fmt(p, 1)} kW", 16,
                                with_alpha(WHITE, 215 * alpha), "regular", anchor="mm")


class SpeedNumberWidget(Widget):
    """纯数字速度：大号半透明数字 + 底部细进度线，水印级占位。"""

    TYPE = "speed_number"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.size_px = int(spec.get("size", 150))
        self.show_power = bool(spec.get("power", True))
        self.max_kmh = float(spec.get("speed_max", 0)) or float(ctx.cfg["speed_max_kmh"])
        self.alpha = float(spec.get("fill_alpha", 0.42))

    def size(self):
        return int(self.size_px * 2.4), int(self.size_px * 1.18)

    def paint(self, dr, i, ox, oy):
        v = self.ctx.get("VehSpd", i)
        alpha = self.opacity
        self.ctx.fonts.text(dr, (ox, oy), fmt(v), self.size_px,
                            scale_color(WHITE, 255 * self.alpha * alpha), "bold", anchor="la",
                            shadow=False)
        y = oy + self.size_px * 1.02
        w = self.size_px * 1.9
        dr.line((ox + 2, y, ox + w, y), fill=with_alpha(WHITE, 70 * alpha), width=2)
        if np.isfinite(v) and v > 0:
            dr.line((ox + 2, y, ox + 2 + w * min(v, self.max_kmh) / self.max_kmh, y),
                    fill=with_alpha(WHITE, 190 * alpha), width=2)
        self.ctx.fonts.text(dr, (ox + w + 10, y - 6), "km/h", 15,
                            with_alpha(WHITE, 150 * alpha), anchor="rs", shadow=False)
        if self.show_power:
            p = self.ctx.get("Power", i)
            self.ctx.fonts.text(dr, (ox + w / 2, y + 10), f"{fmt(p, 1)} kW", 17,
                                with_alpha(WHITE, 150 * alpha), anchor="ma", shadow=False)


class SpeedFlatWidget(Widget):
    """扁平速度卡：大号数字 + 小型模拟圆表（指针弧） + 横向进度条 + 功率。"""

    TYPE = "speed_flat"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.width = int(spec.get("w", 440))
        self.height = int(spec.get("h", 106))
        self.number_size = int(spec.get("number_size", 48))
        self.show_power = bool(spec.get("power", True))
        self.max_kmh = float(spec.get("speed_max", 0)) or float(ctx.cfg["speed_max_kmh"])

    def size(self):
        return self.width, self.height

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        h = self.height
        v = self.ctx.get("VehSpd", i)
        frac = min(max(v, 0), self.max_kmh) / self.max_kmh if np.isfinite(v) else 0.0
        # 速度数字（左侧）
        num_cx = ox + 54
        self.ctx.fonts.text(dr, (num_cx, oy + 44), fmt(v), self.number_size,
                            WHITE, "bold", anchor="mm")
        self.ctx.fonts.text(dr, (num_cx, oy + 80), "km/h", 12,
                            with_alpha(WHITE, 155 * alpha), anchor="mm")
        # 小型模拟圆表（中部左）：270° 弧 + 指针
        acx, acy, r = ox + 155, oy + 46, 32
        bbox = (acx - r, acy - r, acx + r, acy + r)
        dr.arc(bbox, 135, 405, fill=with_alpha(WHITE, 55 * alpha), width=3)
        if frac > 0:
            dr.arc(bbox, 135, 135 + frac * 270, fill=with_alpha(WHITE, 225 * alpha), width=3)
            a = math.radians(135 + frac * 270)
            dr.line((acx + math.cos(a) * (r - 11), acy + math.sin(a) * (r - 11),
                     acx + math.cos(a) * (r - 3), acy + math.sin(a) * (r - 3)),
                    fill=with_alpha(WHITE, 240 * alpha), width=2)
        # 横向进度条（中部右）
        x0, x1 = ox + 205, ox + self.width - (100 if self.show_power else 16)
        bar_y = oy + h / 2
        dr.rounded_rectangle((x0, bar_y - 3, x1, bar_y + 3), radius=3,
                             fill=with_alpha(WHITE, 52 * alpha))
        if frac > 0:
            fill = (x1 - x0) * frac
            if fill >= 2:
                dr.rounded_rectangle((x0, bar_y - 3, x0 + fill, bar_y + 3), radius=3,
                                     fill=with_alpha(WHITE, 225 * alpha))
        for t in np.linspace(0, 1, 5):
            tx = x0 + (x1 - x0) * t
            dr.line((tx, bar_y + 7, tx, bar_y + 12), fill=with_alpha(WHITE, 95 * alpha), width=1)
        # 功率（右侧）
        if self.show_power:
            p = self.ctx.get("Power", i)
            px = ox + self.width - 46
            self.ctx.fonts.text(dr, (px, oy + 44), fmt(p, 1), 25, WHITE, "bold", anchor="mm")
            self.ctx.fonts.text(dr, (px, oy + 72), "kW", 11,
                                with_alpha(WHITE, 155 * alpha), anchor="mm")


class SteerIndicatorWidget(Widget):
    """转向角指示：水平标尺 + 中心刻度 + 指针，扁平不挡视野。

    显示约定：左正右负（左打方向指针向左）。source 默认 'Ave Steer'（deg）；
    若实测指针方向与打方向相反，在 spec 加 "positive_left": false 翻转。
    """

    TYPE = "steer_indicator"
    DEFAULT_SOURCE = "Steer Sense"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.width = int(spec.get("w", 340))
        self.max_deg = float(spec.get("max_deg", 160))
        self.positive_left = bool(spec.get("positive_left", True))
        self.source = spec.get("source", self.DEFAULT_SOURCE)

    def size(self):
        return self.width, 40

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        x0, x1 = ox + 10, ox + self.width - 10
        mid = (x0 + x1) / 2
        y = oy + 28
        # 标尺与刻度
        dr.line((x0, y, x1, y), fill=with_alpha(WHITE, 60 * alpha), width=1)
        for t in np.linspace(0, 1, 5):
            tx = x0 + (x1 - x0) * t
            h = 9 if t in (0.0, 0.5, 1.0) else 5
            dr.line((tx, y - h, tx, y), fill=with_alpha(WHITE, 110 * alpha), width=1)
        # 指针（中心向打方向的实心细条；左正右负）
        v = self.ctx.get(self.source, i)
        if not np.isfinite(v) and self.source == "Steer Sense":
            v = self.ctx.get("Ave Steer", i)
        if np.isfinite(v):
            frac = np.clip(v / self.max_deg, -1, 1)
            if not self.positive_left:
                frac = -frac
            nx = mid - frac * (x1 - x0) / 2
            dr.rounded_rectangle((nx - 2, y - 15, nx + 2, y + 1), radius=2,
                                 fill=with_alpha(WHITE, 235 * alpha))
            # 中心到指针的浅色填充，增强方向感
            a, b = sorted((mid, nx))
            dr.rectangle((a, y - 2, b, y), fill=with_alpha(WHITE, 70 * alpha))
        self.ctx.fonts.text(dr, (x1, oy + 6), f"{fmt(v, 0)}°", 15,
                            with_alpha(WHITE, 205 * alpha), "bold", anchor="ra")
        self.ctx.fonts.text(dr, (x0, y + 4), "L", 10, with_alpha(WHITE, 130 * alpha), anchor="la")
        self.ctx.fonts.text(dr, (x1, y + 4), "R", 10, with_alpha(WHITE, 130 * alpha), anchor="ra")


class GpsMapWidget(Widget):
    """GPS 迷你轨迹图：完整路线 + 当前位置点。"""

    TYPE = "gps_map"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.w = int(spec.get("w", 168))
        self.h = int(spec.get("h", 112))
        self.route_alpha = float(spec.get("route_alpha", 0.45))
        self.dot_r = int(spec.get("dot_r", 4))
        self.label = spec.get("label", "GPS")

    def size(self):
        return self.w, self.h + (16 if self.label else 4)

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        pts = self.ctx.route(self.w, self.h)
        if pts is not None:
            draw_lines(dr, [(ox + px, oy + py) for px, py in pts],
                       with_alpha(WHITE, 255 * self.route_alpha * alpha), 2)
        pos = self.ctx.live_route_xy(i, self.w, self.h)
        if pos is not None:
            x, y = ox + pos[0], oy + pos[1]
            dr.ellipse((x - self.dot_r - 2, y - self.dot_r - 2, x + self.dot_r + 2, y + self.dot_r + 2),
                       fill=(0, 0, 0, 0), outline=with_alpha(WHITE, 200 * alpha), width=1)
            dr.ellipse((x - self.dot_r, y - self.dot_r, x + self.dot_r, y + self.dot_r),
                       fill=scale_color(GREEN, alpha))
        if self.label:
            self.ctx.fonts.text(dr, (ox, oy + self.h + 2), self.label, 11,
                                with_alpha(WHITE, 140 * alpha), "regular", letter_spacing=2)


class GMeterWidget(Widget):
    """G 力球：ring=完整圆环盘，dot=只有十字与球点（极简）。反向惯性显示。"""

    TYPE = "g_meter"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.radius = int(spec.get("radius", 44))
        self.variant = spec.get("variant", "ring")
        self.show_value = bool(spec.get("value", False))
        self.trail = float(spec.get("trail", 1.2))
        self.g_max = float(ctx.cfg["g_max"])

    def size(self):
        base = self.radius * 2 + 8
        h = base + (18 if self.show_value else 0)
        return base, h

    def offset(self, ax, ay, r):
        d = float(self.ctx.cfg.get("g_ball_direction", -1))
        return (d * np.clip(ay, -self.g_max, self.g_max) * r / self.g_max,
                -d * np.clip(ax, -self.g_max, self.g_max) * r / self.g_max)

    def paint(self, dr, i, ox, oy):
        cx = ox + self.radius + 4
        cy = oy + self.radius + 4
        r = self.radius
        alpha = self.opacity
        if self.variant == "ring":
            for rr in (r / 2, r):
                dr.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                           outline=with_alpha(WHITE, 80 * alpha), width=1)
            dr.line((cx - r, cy, cx + r, cy), fill=with_alpha(WHITE, 55 * alpha), width=1)
            dr.line((cx, cy - r, cx, cy + r), fill=with_alpha(WHITE, 55 * alpha), width=1)
        else:
            for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                dr.line((cx + dx * (r - 4), cy + dy * (r - 4), cx + dx * r, cy + dy * r),
                        fill=with_alpha(WHITE, 120 * alpha), width=1)
        fps = float(self.ctx.cfg["fps"])
        trail_frames = max(1, round(self.trail * fps))
        step = max(1, round(fps / 25))
        for j in range(max(0, i - trail_frames), i + 1, step):
            ax = self.ctx.get("ACC X", j)
            ay = self.ctx.get("ACC Y", j)
            if np.isfinite(ax + ay):
                dx, dy = self.offset(ax, ay, r)
                a = int(180 * (1 - (i - j) / trail_frames) * alpha)
                dr.ellipse((cx + dx - 2, cy + dy - 2, cx + dx + 2, cy + dy + 2),
                           fill=with_alpha(WHITE, a))
        ax = self.ctx.get("ACC X", i)
        ay = self.ctx.get("ACC Y", i)
        if np.isfinite(ax + ay):
            dx, dy = self.offset(ax, ay, r)
            dr.ellipse((cx + dx - 4, cy + dy - 4, cx + dx + 4, cy + dy + 4),
                       fill=scale_color(RED, alpha))
            if self.show_value:
                self.ctx.fonts.text(dr, (cx, oy + self.radius * 2 + 6), f"{math.hypot(ax, ay):.2f} g",
                                    13, with_alpha(WHITE, 190 * alpha), anchor="ma")
        elif self.show_value:
            self.ctx.fonts.text(dr, (cx, oy + self.radius * 2 + 6), "-- g", 13,
                                with_alpha(WHITE, 190 * alpha), anchor="ma")


class PedalBarsWidget(Widget):
    """油门/刹车竖条。variant=edge 时贴边、无外框，仅细条 + 小字。"""

    TYPE = "pedal_bars"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.bar_w = int(spec.get("bar_w", 12))
        self.bar_h = int(spec.get("bar_h", 150))
        self.gap = int(spec.get("gap", 16))
        self.variant = spec.get("variant", "boxed")
        self.labels = bool(spec.get("labels", True))

    def size(self):
        w = self.bar_w * 2 + self.gap
        h = self.bar_h + (16 if self.labels and self.variant != "edge" else 4)
        if self.variant == "boxed":
            w += 8
            h += 8
        return w, h

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        inner_ox = ox + (4 if self.variant == "boxed" else 0)
        inner_oy = oy + (4 if self.variant == "boxed" else 0)
        if self.variant == "boxed":
            dr.rounded_rectangle((ox, oy, ox + self.bar_w * 2 + self.gap + 8,
                                  oy + self.bar_h + 8), radius=6,
                                 outline=with_alpha(WHITE, 90 * alpha), width=1)
        bars = [("BRK", "Ave Brake", RED), ("THR", "Acc-2", GREEN)]
        for k, (label, key, color) in enumerate(bars):
            x = inner_ox + k * (self.bar_w + self.gap)
            y0, y1 = inner_oy, inner_oy + self.bar_h
            if self.variant == "boxed":
                dr.rectangle((x, y0, x + self.bar_w, y1),
                             outline=with_alpha(WHITE, 70 * alpha), width=1)
            else:
                dr.line((x + self.bar_w // 2, y0, x + self.bar_w // 2, y1),
                        fill=with_alpha(WHITE, 55 * alpha), width=1)
            v = self.ctx.get(key if key != "Ave Brake" else "Brake Relative", i)
            if np.isfinite(v):
                h = np.clip(v, 0, 100) / 100 * (self.bar_h - 1)
                if h >= 1:
                    dr.rectangle((x, y1 - h, x + self.bar_w, y1), fill=scale_color(color, alpha))
            if self.labels:
                self.ctx.fonts.text(dr, (x + self.bar_w / 2, y1 + 3), label, 10,
                                    with_alpha(WHITE, 150 * alpha), "regular", anchor="ma")


class ValueChipWidget(Widget):
    """通用数值条目：绑定任意数据键（标题 + 值 + 单位）。

    source 可以是逐帧数组键（如 'Power'、'Battery Soc'，
    见 render_demo.py 的 extra_channels 机制）。
    """

    TYPE = "value_chip"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.title = spec.get("title", "")
        self.source = spec.get("source", "Power")
        self.unit = spec.get("unit", "")
        self.digits = int(spec.get("digits", 0))
        self.value_size = int(spec.get("value_size", 22))
        self.width = int(spec.get("w", 120))

    def size(self):
        h = 20 + self.value_size + (12 if self.unit else 2)
        return self.width, h

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        v = self.ctx.get(self.source, i)
        x = ox
        if self.title:
            self.ctx.fonts.text(dr, (x, oy), self.title, 11,
                                with_alpha(WHITE, 150 * alpha), "regular", letter_spacing=1)
            oy += 18
        self.ctx.fonts.text(dr, (x, oy), fmt(v, self.digits), self.value_size,
                            WHITE, "bold", anchor="la")
        if self.unit:
            self.ctx.fonts.text(dr, (ox + self.width, oy + self.value_size * 0.28),
                                self.unit, 13, with_alpha(WHITE, 150 * alpha), anchor="ra")


class ValueStackWidget(Widget):
    """多行数值组：每行「标题 + 值 + 单位」，适合把相关条目（如电池 SOC/电压/电流）
    收进同一张卡片。rows: [{title, source, unit, digits}, ...]"""

    TYPE = "value_stack"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.rows = list(spec.get("rows", []))
        self.width = int(spec.get("w", 150))
        self.row_h = int(spec.get("row_h", 48))
        self.value_size = int(spec.get("value_size", 24))

    def size(self):
        return self.width, len(self.rows) * self.row_h

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        for k, row in enumerate(self.rows):
            y = oy + k * self.row_h
            v = self.ctx.get(row.get("source", ""), i)
            if row.get("title"):
                self.ctx.fonts.text(dr, (ox, y), row["title"], 11,
                                    with_alpha(WHITE, 150 * alpha), "regular", letter_spacing=1)
            vy = y + 16
            self.ctx.fonts.text(dr, (ox, vy), fmt(v, int(row.get("digits", 0))),
                                self.value_size, WHITE, "bold", anchor="la")
            unit = row.get("unit")
            if unit:
                self.ctx.fonts.text(dr, (ox + self.width, vy + self.value_size * 0.32),
                                    unit, 12, with_alpha(WHITE, 150 * alpha), anchor="ra")


class TimingWidget(Widget):
    """计时卡：车辆名 / LAP 圈数 / 当前圈用时 / 总用时，全部居中。

    lap_seconds 优先取 spec，其次 ctx.info（render_demo.py 从 CSV 元数据
    'Segment Times' 解析）；都没有则显示 --。圈数 = 整除圈时 + 1（等分段假设，
    真实信标圈计时属于后续工作）。
    """

    TYPE = "timing"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.width = int(spec.get("w", 150))
        self.source = spec.get("source", "Data Time")
        lap = spec.get("lap_seconds", ctx.info.get("lap_seconds", 0))
        self.lap_seconds = float(lap) if lap else None

    def size(self):
        return self.width, 96

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        mid = ox + self.width / 2
        t = self.ctx.get(self.source, i)
        fonts = self.ctx.fonts
        fonts.text(dr, (mid, oy + 2), self.ctx.info.get("vehicle", ""), 13,
                   with_alpha(WHITE, 165 * alpha), anchor="ma")
        if self.lap_seconds and np.isfinite(t) and t >= 0:
            n = int(t // self.lap_seconds) + 1
            cur = t - (n - 1) * self.lap_seconds
            fonts.text(dr, (mid, oy + 22), f"LAP {n}", 16, WHITE, "bold", anchor="ma")
            fonts.text(dr, (mid, oy + 42), fmt_clock(cur), 27, WHITE, "bold", anchor="ma")
            fonts.text(dr, (mid, oy + 76), f"TOTAL {fmt_clock(t)}", 13,
                       with_alpha(WHITE, 165 * alpha), anchor="ma")
        else:
            fonts.text(dr, (mid, oy + 22), "LAP --", 16, WHITE, "bold", anchor="ma")
            fonts.text(dr, (mid, oy + 42), "--:--.-", 27, WHITE, "bold", anchor="ma")
            fonts.text(dr, (mid, oy + 76), "TOTAL --:--.-", 13,
                       with_alpha(WHITE, 165 * alpha), anchor="ma")


class TimecodeWidget(Widget):
    """录像/数据双时间码，仅用于对齐校对。"""

    TYPE = "timecode"

    def size(self):
        return int(round(380 * self.s)), int(round(20 * self.s))

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        vt = self.ctx.get("Video Time", i)
        dt = self.ctx.get("Data Time", i)
        self.ctx.fonts.text(dr, (ox, oy), f"VIDEO {vt:7.3f}s   DATA {dt:7.3f}s", int(round(13 * self.s)),
                            with_alpha(WHITE, 170 * alpha), "regular", anchor="lm")


class BottomStripWidget(Widget):
    """F1 直播式底部信息带：一条半透明横带收纳全部仪表（复合控件示例）。"""

    TYPE = "bottom_strip"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        self.width = int(spec.get("w", CANVAS_W - 48))
        self.height = int(spec.get("h", 88))
        self.max_kmh = float(spec.get("speed_max", 0)) or float(ctx.cfg["speed_max_kmh"])
        self.max_nm = float(spec.get("torque_max", 0)) or float(ctx.cfg["torque_max_nm"])
        self._map_w = int(spec.get("map_w", 128))
        self._map_h = int(spec.get("map_h", 56))

    def size(self):
        return self.width, self.height

    def paint(self, dr, i, ox, oy):
        alpha = self.opacity
        w, h = self.width, self.height
        dr.rounded_rectangle((ox, oy, ox + w, oy + h), radius=10,
                             fill=(8, 10, 14, int(96 * alpha)),
                             outline=with_alpha(WHITE, 55 * alpha), width=1)
        cy = oy + h / 2
        fonts = self.ctx.fonts
        v = self.ctx.get("VehSpd", i)
        x = ox + 26
        fonts.text(dr, (x, cy - 10), fmt(v), 40, WHITE, "bold", anchor="lm")
        fonts.text(dr, (x + 2, cy + 22), "km/h", 12, with_alpha(WHITE, 150 * alpha), anchor="la")
        x += 118
        dr.line((x - 14, oy + 14, x - 14, oy + h - 14), fill=with_alpha(WHITE, 40 * alpha), width=1)
        p = self.ctx.get("Power", i)
        fonts.text(dr, (x, cy - 10), fmt(p, 1), 26, WHITE, "regular", anchor="lm")
        fonts.text(dr, (x + 2, cy + 16), "kW", 12, with_alpha(WHITE, 150 * alpha), anchor="la")
        x += 96
        dr.line((x - 14, oy + 14, x - 14, oy + h - 14), fill=with_alpha(WHITE, 40 * alpha), width=1)
        # 油门/刹车横条
        for k, (label, key, color) in enumerate([("THR", "Acc-2", GREEN), ("BRK", "Brake Relative", RED)]):
            y = oy + 20 + k * 26
            bar_w = 88
            fonts.text(dr, (x, y + 5), label, 10, with_alpha(WHITE, 160 * alpha), "regular")
            dr.rectangle((x + 26, y, x + 26 + bar_w, y + 9), outline=with_alpha(WHITE, 70 * alpha), width=1)
            val = self.ctx.get(key, i)
            if np.isfinite(val) and val > 0:
                dr.rectangle((x + 26, y, x + 26 + bar_w * min(val, 100) / 100, y + 9),
                             fill=scale_color(color, alpha))
        x += 132
        dr.line((x - 14, oy + 14, x - 14, oy + h - 14), fill=with_alpha(WHITE, 40 * alpha), width=1)
        # G 力小球（横置十字）
        gx, gy, gr = x + 30, cy, 22
        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
            dr.line((gx + dx * (gr - 3), gy + dy * (gr - 3), gx + dx * gr, gy + dy * gr),
                    fill=with_alpha(WHITE, 110 * alpha), width=1)
        meter = GMeterWidget({"variant": "dot"}, self.ctx)
        ax, ay = self.ctx.get("ACC X", i), self.ctx.get("ACC Y", i)
        if np.isfinite(ax + ay):
            dx, dy = meter.offset(ax, ay, gr)
            dr.ellipse((gx + dx - 4, gy + dy - 4, gx + dx + 4, gy + dy + 4), fill=scale_color(RED, alpha))
        x += 74
        dr.line((x - 14, oy + 14, x - 14, oy + h - 14), fill=with_alpha(WHITE, 40 * alpha), width=1)
        # 扭矩迷你柱
        for k, slot in enumerate(("FL", "FR", "RL", "RR")):
            bx = x + k * 22
            active = slot in self.ctx.motor_slots
            dr.rectangle((bx, oy + h / 2 - 16, bx + 12, oy + h / 2 + 16),
                         outline=with_alpha(WHITE, 80 * alpha), width=1)
            if active:
                tq = self.ctx.get(slot + " Torque", i)
                if np.isfinite(tq) and abs(tq) > 0:
                    bh = min(1.0, abs(tq) / self.max_nm) * 31
                    dr.rectangle((bx + 1, oy + h / 2 + 15 - bh, bx + 11, oy + h / 2 + 15),
                                 fill=scale_color(GREEN, alpha))
        x += 96
        dr.line((x - 14, oy + 14, x - 14, oy + h - 14), fill=with_alpha(WHITE, 40 * alpha), width=1)
        # GPS 迷你图
        mw, mh = self._map_w, self._map_h
        my = oy + (h - mh) / 2
        pts = self.ctx.route(mw, mh)
        if pts is not None:
            draw_lines(dr, [(ox + w - 10 - mw + px, my + py) for px, py in pts],
                       with_alpha(WHITE, 150 * alpha), 2)
        pos = self.ctx.live_route_xy(i, mw, mh)
        if pos is not None:
            px, py = ox + w - 10 - mw + pos[0], my + pos[1]
            dr.ellipse((px - 3, py - 3, px + 3, py + 3), fill=scale_color(GREEN, alpha))


class BottomBarWidget(Widget):
    """通栏底部信息带：贴满视频底边与左右两端，各区块等高。

    间距体系统一：所有内容与屏幕左右边缘、与区块分割线之间保持相同留白（PAD）。
    `BASE_DIVIDER_SHIFT` 可让某区块右缘的分割线单独位移而不移动内容（微调对齐用）。
    从左到右：GPS 迷你轨迹（无标题、占满高度、红点定位）→ 电池双层两列（紧凑列距）→
    转向圆环（底部缺口，绿色光标 + 中心数字，左正右负 ±max_deg）→
    速度（大号数字预留三位 + 方正条形图填满剩余、偏下）→
    G 力（X 值盘上方、Y 值盘左侧、G-FORCE 标题在底排）→
    踏板（THR/BRK）→ 四轮扭矩（正/负量程零线分割，条形+数字，最右）。
    """

    TYPE = "bottom_bar"
    DEFAULT_SOURCE = ["Steer Sense", "Ave Steer", "Battery Soc", "Battery Volt", "Battery Current"]  # 自动插值

    BASE_PAD = 15  # 统一留白：屏幕边缘 / 分割线 到内容的距离
    # 仅分割线位移（不改内容位置）：{区块名: 该区块右缘分割线额外右移 px}
    BASE_DIVIDER_SHIFT = {"pedals": 10}
    BASE_SECTIONS = [
        ("gps", 0, 305), ("battery", 305, 600), ("steer", 600, 800),
        ("speed", 800, 1215), ("pedals", 1215, 1371), ("gforce", 1371, 1570),
        ("motors", 1570, 1920)
    ]

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        s = self.s
        self.height = int(round(float(spec.get("h", 172)) * s))
        self.max_kmh = float(spec.get("speed_max", 0)) or float(ctx.cfg["speed_max_kmh"])
        self.max_nm = float(spec.get("torque_max", 0)) or float(ctx.cfg["torque_max_nm"])
        self.max_deg = float(spec.get("max_deg", 160))
        self.positive_left = bool(spec.get("positive_left", True))
        self.gap_deg = float(spec.get("gap_deg", 40))  # 圆环底部缺口总角度
        self.torque_pos_max = float(spec.get("torque_pos_max", 20))  # 正扭矩量程
        self.torque_neg_max = float(spec.get("torque_neg_max", 10))  # 负扭矩量程
        self.map_w = int(round(float(spec.get("map_w", 285)) * s))
        self.map_h = int(round(float(spec.get("map_h", 158)) * s))
        self.PAD = int(round(self.BASE_PAD * s))
        self.SECTIONS = [
            (name, int(round(x0 * s)), int(round(x1 * s)) if idx < len(self.BASE_SECTIONS) - 1 else ctx.width)
            for idx, (name, x0, x1) in enumerate(self.BASE_SECTIONS)
        ]

    def size(self):
        return self.ctx.width, self.height

    def paint_base(self, dr, ox, oy):
        s = self.s
        alpha = self.opacity
        H = self.height
        P = self.PAD
        cw = self.ctx.width
        top = oy + int(round(12 * s))                      # 内容区顶
        ch = H - int(round(12 * s)) - int(round(20 * s))   # 内容区高（留给底部标题行）
        title_y = oy + H - int(round(20 * s))              # 标题行文字锚点
        fonts = self.ctx.fonts

        # 通栏底色 + 上缘亮线
        dr.rectangle((0, oy, cw, oy + H), fill=(8, 10, 14, int(100 * alpha)))
        dr.line((0, oy, cw, oy), fill=with_alpha(WHITE, 60 * alpha), width=max(1, int(round(1 * s))))

        def title(cx, text):
            fonts.text(dr, (cx, title_y), text, int(round(12 * s)), with_alpha(WHITE, 160 * alpha),
                       "regular", anchor="ma", letter_spacing=max(1, int(round(2 * s))))

        def separator(x):
            dr.line((x, top - int(round(2 * s)), x, oy + H - int(round(30 * s))),
                    fill=with_alpha(WHITE, 40 * alpha), width=max(1, int(round(1 * s))))

        # ---- GPS 迷你轨迹静态路径（最左）----
        x0, x1 = ox + self.SECTIONS[0][1], ox + self.SECTIONS[0][2]
        mw = min(self.map_w, x1 - x0 - 2 * P)
        mh = min(self.map_h, H - int(round(26 * s)))
        mx, my = x0 + P + (x1 - x0 - 2 * P - mw) / 2, top + (H - int(round(16 * s)) - mh) / 2
        pts = self.ctx.route(mw, mh)
        if pts is not None:
            draw_lines(dr, [(mx + px, my + py) for px, py in pts],
                       with_alpha(WHITE, 165 * alpha), max(1, int(round(2 * s))))

        # ---- 电池区静态标签 ----
        x0, x1 = ox + self.SECTIONS[1][1], ox + self.SECTIONS[1][2]
        labels = ["SOC", "VOLT", "POWER", "CURRENT"]
        col_w = int(round(116 * s))
        block_w = col_w + int(round(76 * s))
        bx0 = x0 + (x1 - x0 - block_w) / 2  # 左右留白对称
        row_h = (ch - int(round(4 * s))) / 2
        for k, label in enumerate(labels):
            ix = bx0 + (k % 2) * col_w
            iy = top + int(round(10 * s)) + (k // 2) * row_h
            fonts.text(dr, (ix, iy), label, int(round(12 * s)), with_alpha(WHITE, 145 * alpha),
                       "regular", letter_spacing=max(1, int(round(1 * s))))
        title((x0 + x1) / 2, "BATTERY")

        # ---- 转向圆环静态背景 ----
        x0, x1 = ox + self.SECTIONS[2][1], ox + self.SECTIONS[2][2]
        g = self.gap_deg / 2
        r = int(round(50 * s))
        cx, cy = (x0 + x1) / 2, top + ch / 2 - int(round(3 * s))
        bbox = (cx - r, cy - r, cx + r, cy + r)
        arc_w = max(1, int(round(4 * s)))
        dr.arc(bbox, 90 + g, 450 - g, fill=with_alpha(WHITE, 75 * alpha), width=arc_w)
        usable = 180 - g
        for t_step in (-1.0, -0.5, 0.0, 0.5, 1.0):
            a = math.radians(270 - t_step * usable)
            tick_len = int(round(7 * s))
            dr.line((cx + math.cos(a) * (r - tick_len), cy + math.sin(a) * (r - tick_len),
                     cx + math.cos(a) * r, cy + math.sin(a) * r),
                    fill=with_alpha(WHITE, 120 * alpha), width=max(1, int(round(1 * s))))
        lr_size = int(round(11 * s))
        fonts.text(dr, (cx - r - int(round(6 * s)), cy), "L", lr_size, with_alpha(WHITE, 130 * alpha), anchor="rm")
        fonts.text(dr, (cx + r + int(round(6 * s)), cy), "R", lr_size, with_alpha(WHITE, 130 * alpha), anchor="lm")
        title(cx, "STEER")

        # ---- 速度静态底条与刻度 ----
        x0, x1 = ox + self.SECTIONS[3][1], ox + self.SECTIONS[3][2]
        spd_font_size = int(round(80 * s))
        digit_w = dr.textlength("0", font=fonts.get(spd_font_size, "regular"))
        bx0 = x0 + int(round(12 * s)) + round(digit_w * 3) + int(round(10 * s))
        bx1 = x1 - P
        bar_y = top + int(round(69 * s))
        fonts.text(dr, (bx0, top + int(round(44 * s))), "km/h", int(round(16 * s)),
                   with_alpha(WHITE, 165 * alpha), anchor="ls")
        bar_half = max(2, int(round(7 * s)))
        dr.rectangle((bx0, bar_y - bar_half, bx1, bar_y + bar_half),
                     fill=with_alpha(WHITE, 55 * alpha))
        ticks = speed_ticks()
        for k, tick in enumerate(ticks):
            tx = bx0 + (bx1 - bx0) * k / (len(ticks) - 1)
            dr.line((tx, bar_y + int(round(11 * s)), tx, bar_y + int(round(15 * s))),
                    fill=with_alpha(WHITE, 115 * alpha), width=max(1, int(round(1 * s))))
            fonts.text(dr, (tx, bar_y + int(round(17 * s))), str(tick), int(round(10 * s)),
                       with_alpha(WHITE, 155 * alpha), anchor="ma")
        title((x0 + x1) / 2, "SPEED")

        # ---- 四轮扭矩静态框 ----
        x0, x1 = ox + self.SECTIONS[6][1], ox + self.SECTIONS[6][2]
        bar_h = ch - int(round(14 * s))
        slot_w = (x1 - x0 - 2 * P - int(round(12 * s))) / 4
        bar_w, num_w = int(round(30 * s)), int(round(40 * s))
        pad_in = max(0.0, (slot_w - bar_w - int(round(5 * s)) - num_w) / 2)
        for k, slot in enumerate(("FL", "FR", "RL", "RR")):
            gx = x0 + P + int(round(12 * s)) + k * slot_w + pad_in
            by1 = top + int(round(2 * s)) + bar_h
            dr.rectangle((gx, by1 - bar_h, gx + bar_w, by1),
                         outline=with_alpha(WHITE, 95 * alpha), width=max(1, int(round(1 * s))))
            neg_h = bar_h * 0.25  # 零线固定 3:1（正:负）
            zero_y = by1 - neg_h
            dr.line((gx + 1, zero_y, gx + bar_w - 1, zero_y),
                    fill=with_alpha(WHITE, 150 * alpha), width=max(1, int(round(1 * s))))
            fonts.text(dr, (gx + bar_w + int(round(5 * s)), by1 - bar_h / 2 + int(round(9 * s))), "Nm", int(round(10 * s)),
                       with_alpha(WHITE, 145 * alpha), anchor="lm")
            fonts.text(dr, (gx + bar_w / 2, title_y), slot, int(round(12 * s)),
                       with_alpha(WHITE, 160 * alpha), anchor="ma", letter_spacing=max(1, int(round(1 * s))))

        # ---- 踏板静态框 ----
        x0, x1 = ox + self.SECTIONS[4][1], ox + self.SECTIONS[4][2]
        bar_h = ch - int(round(14 * s))
        slot_w = (x1 - x0 - 2 * P) / 2
        bar_w, num_w = int(round(24 * s)), int(round(26 * s))
        pad_in = max(0.0, (slot_w - bar_w - int(round(5 * s)) - num_w) / 2)
        for k, label in enumerate(("THR", "BRK")):
            bx = x0 + P + int(round(2 * s)) + k * slot_w + pad_in + (14 * s if k else 0)
            by1 = top + int(round(2 * s)) + bar_h
            dr.rectangle((bx, by1 - bar_h, bx + bar_w, by1),
                         outline=with_alpha(WHITE, 80 * alpha), width=max(1, int(round(1 * s))))
            fonts.text(dr, (bx + bar_w + int(round(5 * s)), by1 - bar_h / 2 + int(round(9 * s))), "%", int(round(10 * s)),
                       with_alpha(WHITE, 145 * alpha), anchor="lm", shadow=False)
            fonts.text(dr, (bx + bar_w / 2, title_y), label, int(round(12 * s)),
                       with_alpha(WHITE, 160 * alpha), anchor="ma", letter_spacing=max(1, int(round(1 * s))))

        # ---- G 力静态圆环（内圈加大、下沉填满）与底排标题 ----
        x0, x1 = ox + self.SECTIONS[5][1], ox + self.SECTIONS[5][2]
        r = int(round(52 * s))
        cx, cy = x0 + P + int(round(37 * s)) + int(round(22 * s)) + r, top + int(round(70 * s))
        for rr in (r * 0.62, r):
            dr.ellipse((cx - rr, cy - rr, cx + rr, cy + rr),
                       outline=with_alpha(WHITE, 80 * alpha), width=max(1, int(round(1 * s))))
        dr.line((cx - r, cy, cx + r, cy), fill=with_alpha(WHITE, 55 * alpha), width=max(1, int(round(1 * s))))
        dr.line((cx, cy - r, cx, cy + r), fill=with_alpha(WHITE, 55 * alpha), width=max(1, int(round(1 * s))))
        # 标题居中于左右两条分割线之间（左线含 BASE_DIVIDER_SHIFT 位移）
        left_div = self.SECTIONS[4][2] + int(round(self.BASE_DIVIDER_SHIFT.get("pedals", 0) * s))
        title((left_div + self.SECTIONS[5][2]) / 2 + int(round(2 * s)), "G-FORCE")

        # 区块分隔线（支持仅分割线位移，不影响内容布局）
        for name, _, edge in self.SECTIONS[:-1]:
            separator(ox + edge + int(round(self.BASE_DIVIDER_SHIFT.get(name, 0) * s)))

    def paint(self, dr, i, ox, oy):
        s = self.s
        alpha = self.opacity
        H = self.height
        P = self.PAD
        top = oy + int(round(12 * s))                      # 内容区顶
        ch = H - int(round(12 * s)) - int(round(20 * s))   # 内容区高（留给底部标题行）
        fonts = self.ctx.fonts

        # ---- GPS 动态位置红点 ----
        x0, x1 = ox + self.SECTIONS[0][1], ox + self.SECTIONS[0][2]
        mw = min(self.map_w, x1 - x0 - 2 * P)
        mh = min(self.map_h, H - int(round(26 * s)))
        mx, my = x0 + P + (x1 - x0 - 2 * P - mw) / 2, top + (H - int(round(16 * s)) - mh) / 2
        pos = self.ctx.live_route_xy(i, mw, mh)
        if pos is not None:
            px, py = mx + pos[0], my + pos[1]
            dot_r = max(2, int(round(3 * s)))
            dr.ellipse((px - dot_r, py - dot_r, px + dot_r, py + dot_r), fill=scale_color(RED, alpha))

        # ---- 电池动态数值 ----
        x0, x1 = ox + self.SECTIONS[1][1], ox + self.SECTIONS[1][2]
        items = [("Battery Soc", "%", 0), ("Battery Volt", "V", 1),
                 ("Power", "kW", 1), ("Battery Current", "A", 1)]
        col_w = int(round(116 * s))
        block_w = col_w + int(round(76 * s))
        bx0 = x0 + (x1 - x0 - block_w) / 2  # 左右留白对称
        row_h = (ch - int(round(4 * s))) / 2
        for k, (key, unit, digits) in enumerate(items):
            ix = bx0 + (k % 2) * col_w
            iy = top + int(round(10 * s)) + (k // 2) * row_h
            v = self.ctx.get(key, i)
            val_str = fmt(v, digits)
            f_size = int(round(26 * s))
            fonts.text(dr, (ix, iy + int(round(15 * s))), val_str, f_size, WHITE, "bold", anchor="la")
            if unit:
                ux = ix + dr.textlength(val_str, font=fonts.get(f_size, "bold")) + int(round(6 * s))
                fonts.text(dr, (ux, iy + int(round(27 * s))), unit, int(round(12 * s)),
                           with_alpha(WHITE, 150 * alpha), anchor="ls")

        # ---- 转向动态弧度与数字 ----
        x0, x1 = ox + self.SECTIONS[2][1], ox + self.SECTIONS[2][2]
        g = self.gap_deg / 2
        r = int(round(50 * s))
        cx, cy = (x0 + x1) / 2, top + ch / 2 - int(round(3 * s))
        bbox = (cx - r, cy - r, cx + r, cy + r)
        arc_w = max(1, int(round(4 * s)))
        usable = 180 - g
        v = self.ctx.get("Steer Sense", i)
        if not np.isfinite(v):
            v = self.ctx.get("Ave Steer", i)
        steer_f_size = int(round(22 * s))
        if np.isfinite(v):
            frac = float(np.clip(v / self.max_deg, -1, 1))
            if not self.positive_left:
                frac = -frac
            theta = 270 - frac * usable
            px, py = cx + math.cos(math.radians(theta)) * r, cy + math.sin(math.radians(theta)) * r
            delta = theta - 270
            if delta > 180:
                delta -= 360
            if delta > 0:
                dr.arc(bbox, 270, 270 + delta, fill=scale_color(GREEN, alpha), width=arc_w)
            else:
                dr.arc(bbox, 270 + delta, 270, fill=scale_color(GREEN, alpha), width=arc_w)
            dot_s = max(2, int(round(4 * s)))
            dr.ellipse((px - dot_s, py - dot_s, px + dot_s, py + dot_s), fill=scale_color(GREEN, alpha))
            fonts.text(dr, (cx, cy + int(round(2 * s))), steer_text(v), steer_f_size, WHITE, "bold", anchor="mm")
        else:
            fonts.text(dr, (cx, cy + int(round(2 * s))), steer_text(v), steer_f_size,
                       with_alpha(WHITE, 170 * alpha), "bold", anchor="mm")

        # ---- 速度动态数字与填充条 ----
        x0, x1 = ox + self.SECTIONS[3][1], ox + self.SECTIONS[3][2]
        v = self.ctx.get("VehSpd", i)
        frac = speed_fraction(v)
        cy_v = top + ch / 2 - int(round(5 * s))
        spd_font_size = int(round(80 * s))
        fonts.text(dr, (x0 + P + int(round(10 * s)), cy_v + int(round(10 * s))),
                   fmt(v), spd_font_size, WHITE, "regular", anchor="lm")
        digit_w = dr.textlength("0", font=fonts.get(spd_font_size, "regular"))
        bx0 = x0 + int(round(12 * s)) + round(digit_w * 3) + int(round(10 * s))
        bx1 = x1 - P
        bar_y = top + int(round(69 * s))
        bar_half = max(2, int(round(7 * s)))
        if frac > 0:
            fill = (bx1 - bx0) * frac
            if fill >= 2:
                dr.rectangle((bx0, bar_y - bar_half, bx0 + fill, bar_y + bar_half),
                             fill=with_alpha(WHITE, 230 * alpha))

        # ---- 四轮扭矩动态条与数字 ----
        x0, x1 = ox + self.SECTIONS[6][1], ox + self.SECTIONS[6][2]
        bar_h = ch - int(round(14 * s))
        slot_w = (x1 - x0 - 2 * P - int(round(12 * s))) / 4
        bar_w, num_w = int(round(30 * s)), int(round(40 * s))
        pad_in = max(0.0, (slot_w - bar_w - int(round(5 * s)) - num_w) / 2)
        for k, slot in enumerate(("FL", "FR", "RL", "RR")):
            gx = x0 + P + int(round(12 * s)) + k * slot_w + pad_in
            by1 = top + int(round(2 * s)) + bar_h
            active = slot in self.ctx.motor_slots
            neg_h = bar_h * 0.25  # 零线固定 3:1（正:负）
            zero_y = by1 - neg_h
            pos_h = bar_h - neg_h
            tq = self.ctx.get(slot + " Torque", i)
            if active and np.isfinite(tq):
                if tq >= 0:  # 正扭矩：零线向上，超量程封顶不溢出
                    h = min(tq / self.torque_pos_max, 1.0) * (pos_h - 1)
                    if h >= 1:
                        dr.rectangle((gx + 1, zero_y - h, gx + bar_w - 1, zero_y - 1),
                                     fill=scale_color(GREEN, alpha))
                else:  # 负扭矩：零线向下（能量回收/制动），红色区分
                    h = min(-tq / self.torque_neg_max, 1.0) * (neg_h - 1)
                    if h >= 1:
                        dr.rectangle((gx + 1, zero_y + 1, gx + bar_w - 1, zero_y + h),
                                     fill=scale_color(RED, alpha))
            num = fmt(tq, 1) if active else "--"
            fonts.text(dr, (gx + bar_w + int(round(5 * s)), by1 - bar_h / 2 - int(round(9 * s))), num, int(round(16 * s)), WHITE,
                       "bold", anchor="lm")

        # ---- 踏板动态填充与数字 ----
        x0, x1 = ox + self.SECTIONS[4][1], ox + self.SECTIONS[4][2]
        bar_h = ch - int(round(14 * s))
        slot_w = (x1 - x0 - 2 * P) / 2
        bar_w, num_w = int(round(24 * s)), int(round(26 * s))
        pad_in = max(0.0, (slot_w - bar_w - int(round(5 * s)) - num_w) / 2)
        for k, (key, color) in enumerate([("Acc-2", GREEN), ("Brake Relative", RED)]):
            bx = x0 + P + int(round(2 * s)) + k * slot_w + pad_in + (14 * s if k else 0)
            by1 = top + int(round(2 * s)) + bar_h
            val = self.ctx.get(key, i)
            if np.isfinite(val) and val > 0:
                h = np.clip(val, 0, 100) / 100 * (bar_h - 2)
                if h >= 1:
                    dr.rectangle((bx + 1, by1 - h, bx + bar_w - 1, by1 - 1), fill=scale_color(color, alpha))
            tx = bx + bar_w + int(round(5 * s))
            fonts.text(dr, (tx, by1 - bar_h / 2 - int(round(9 * s))), pedal_text(val), int(round(16 * s)), WHITE,
                       "bold", anchor="lm", shadow=False)

        # ---- G 力动态拖尾（更小更短）与小球、X/Y 读数 ----
        x0, x1 = ox + self.SECTIONS[5][1], ox + self.SECTIONS[5][2]
        r = int(round(52 * s))
        cx, cy = x0 + P + int(round(37 * s)) + int(round(22 * s)) + r, top + int(round(70 * s))
        meter = GMeterWidget({"variant": "ring"}, self.ctx)
        fps = float(self.ctx.cfg["fps"])
        trail_frames = max(1, round(0.6 * fps))  # 拖影更短
        for j in range(max(0, i - trail_frames), i + 1, max(1, round(fps / 25))):
            ax, ay = self.ctx.get("ACC X", j), self.ctx.get("ACC Y", j)
            if np.isfinite(ax + ay):
                dx, dy = meter.offset(ax, ay, r)
                a = int(180 * (1 - (i - j) / trail_frames) * alpha)
                dot_t = max(1, int(round(1.2 * s)))  # 拖影点更小
                dr.ellipse((cx + dx - dot_t, cy + dy - dot_t, cx + dx + dot_t, cy + dy + dot_t),
                           fill=with_alpha(WHITE, a))
        ax, ay = self.ctx.get("ACC X", i), self.ctx.get("ACC Y", i)
        if np.isfinite(ax + ay):
            dx, dy = meter.offset(ax, ay, r)
            dot_g = max(3, int(round(6 * s)))  # 红圆加大更醒目
            dr.ellipse((cx + dx - dot_g, cy + dy - dot_g, cx + dx + dot_g, cy + dy + dot_g),
                       fill=scale_color(RED, alpha))
        fonts.text(dr, (cx, cy - r - int(round(7 * s))), f"X {fmt(ax, 2)}", int(round(13 * s)),
                   with_alpha(WHITE, 205 * alpha), "bold", anchor="ms")
        ycol = cx - r - int(round(22 * s))
        fonts.text(dr, (ycol, cy - int(round(11 * s))), "Y", int(round(13 * s)),
                   with_alpha(WHITE, 205 * alpha), "bold", anchor="ms")
        fonts.text(dr, (ycol, cy), fmt(ay, 2), int(round(13 * s)), WHITE,
                   "bold", anchor="mt")

class TimingBarWidget(Widget):
    """顶部横条（右上角）：车辆 / 车手 / 当前时间 三段。"""

    TYPE = "timing_bar"
    DEFAULT_SOURCE = "Data Time"

    def __init__(self, spec, ctx):
        super().__init__(spec, ctx)
        s = self.s
        self.width = int(round(float(spec.get("w", 360)) * s))
        self.height = int(round(float(spec.get("h", 56)) * s))
        lap = spec.get("lap_seconds", ctx.info.get("lap_seconds", 0))
        self.lap_seconds = float(lap) if lap else None
        self.source = spec.get("source", "Data Time")

    def size(self):
        return self.width, self.height

    def paint_base(self, dr, ox, oy):
        s = self.s
        alpha = self.opacity
        H = self.height
        fonts = self.ctx.fonts
        dr.rounded_rectangle((ox, oy, ox + self.width, oy + H), radius=int(round(10 * s)),
                             fill=(8, 10, 14, int(92 * alpha)),
                             outline=with_alpha(WHITE, 55 * alpha), width=max(1, int(round(1 * s))))
        fonts.text(dr, (ox + 22 * s, oy + 10 * s), "TIME", int(round(10 * s)), with_alpha(WHITE, 140 * alpha),
                   "regular", letter_spacing=max(1, int(round(1 * s))))
        lx = ox + self.width - 170 * s
        dr.line((lx, oy + 12 * s, lx, oy + H - 12 * s), fill=with_alpha(WHITE, 45 * alpha), width=max(1, int(round(1 * s))))
        fonts.text(dr, (ox + self.width - 22 * s, oy + 15 * s), self.ctx.info.get("vehicle", ""), int(round(15 * s)),
                   with_alpha(WHITE, 210 * alpha), "regular", anchor="ra")
        fonts.text(dr, (ox + self.width - 22 * s, oy + 37 * s), self.ctx.info.get("racer", ""), int(round(15 * s)),
                   with_alpha(WHITE, 160 * alpha), "regular", anchor="ra")

    def paint(self, dr, i, ox, oy):
        s = self.s
        H = self.height
        fonts = self.ctx.fonts
        t = self.ctx.get(self.source, i)
        if self.lap_seconds and np.isfinite(t) and t >= 0:
            cur = t - int(t // self.lap_seconds) * self.lap_seconds
        else:
            cur = t
        draw_clock(dr, fonts, (ox + 22 * s, oy + H / 2 + 8 * s), fmt_clock(cur), int(round(37 * s)), WHITE,
                   anchor="lm")


# ---------------------------------------------------------------- 注册与构建

REGISTRY = {
    cls.TYPE: cls for cls in (
        LogoWidget, TorqueBarsWidget, TorqueStripWidget, SpeedDialWidget,
        SpeedFlatWidget, SteerIndicatorWidget, SpeedNumberWidget, GpsMapWidget,
        GMeterWidget, PedalBarsWidget, ValueChipWidget, ValueStackWidget,
        TimingWidget, TimingBarWidget, TimecodeWidget, BottomStripWidget,
        BottomBarWidget,
    )
}


def build_layout(layout_spec: dict, ctx: RenderContext) -> list[Widget]:
    widgets = []
    for spec in layout_spec["widgets"]:
        wtype = spec["type"]
        if wtype not in REGISTRY:
            raise KeyError(f"未知控件类型: {wtype}（可用: {sorted(REGISTRY)}）")
        widgets.append(REGISTRY[wtype](spec, ctx))
    return widgets


def _prepare_layout(ctx: RenderContext, widgets: list[Widget]):
    """缓存不随帧变化的卡片、刻度和标签，并记录动态内容的绘制原点。"""
    key = tuple(id(w) for w in widgets)
    cached = getattr(ctx, "_layout_cache", None)
    if cached is not None and cached[0] == key:
        return cached[1], cached[2]

    base = Image.new("RGBA", (ctx.width, ctx.height), (0, 0, 0, 0))
    dr = ImageDraw.Draw(base)
    origins = []
    for w in widgets:
        wd, ht = w.size()
        if w.card:
            pad = int(round(float(w.spec.get("card_pad", 12)) * ctx.scale))
            title = w.card.get("title")
            title_h = int(round(22 * ctx.scale)) if title else 0
            bw, bh = wd + 2 * pad, ht + 2 * pad + title_h
            bx, by = w.place(bw, bh)
            w.draw_card(dr, bx, by, bw, bh)
            ox, oy = bx + pad, by + title_h + pad
        else:
            ox, oy = w.content_origin(wd, ht)
        w.paint_base(dr, ox, oy)
        origins.append((ox, oy))
    ctx._layout_cache = (key, base, origins)
    return base, origins


def render_composite(ctx: RenderContext, widgets: list[Widget], i: int) -> Image.Image:
    base, origins = _prepare_layout(ctx, widgets)
    im = base.copy()
    dr = ImageDraw.Draw(im)
    for w, (ox, oy) in zip(widgets, origins):
        w.paint(dr, i, ox, oy)
    return im


def render_frame(ctx: RenderContext, widgets: list[Widget], i: int) -> Image.Image:
    """与 render_composite 相同的调用约定，便于以后替换实现。"""
    return render_composite(ctx, widgets, i)
