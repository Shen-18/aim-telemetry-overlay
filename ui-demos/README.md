# ui-demos · 遥测叠加层 UI（卡片舱 · 细调版）

> **v24 冻结版（2026-09-17，用户验收「很满意」）已并入 skill 正式管线**：本目录的 widgets.py（含 v11 布局的渲染代码）
> 已复制到 `../scripts/widgets.py`，选定的布局写入 `../assets/default-config.json` 的
> `layout` 键，`../scripts/hud.py` 改为薄封装。以下内容保留作为设计 playground 与
> 对照参考；改 UI 时先改这里验证，再同步到 scripts/。
初版做了 A/B/C/D 四个候选布局供选型，用户选定 **D 卡片舱** 并提出细调要求，
本目录现在只保留细调后的版本（2026-09-16）：

- **F1 Display 字体**（Regular/Bold，取自自研软件 design-demos/fonts，数字近等宽、转播感强）；
- **扭矩 2×2 网格**：前轮 FL/FR 在上、后轮 RL/RR 在下，与车身边缘对应（宽柱）；
- **底部通栏信息带**（`bottom_bar`，核心控件）：贴满视频底边与左右两端，各区块等高。
  **统一留白体系**：内容与屏幕左右边缘、与区块分割线之间一律保持 `PAD`=15px。
  从左到右：GPS 迷你轨迹（304×124，无标题、**红色定位点**）→ 电池双层两列（列距 112，
  单位紧跟数值）→ 转向圆环（加宽描边，**底部留缺口** `gap_deg`=40°，±160° 恰好 1:1
  映射；绿色光标 + 中心带符号数字，左正右负）→ 速度（80px Regular 数字 +
  **方正**条形图填满剩余宽度、偏下、14px 粗、刻度 0/40/80/120，16px km/h 在条形图
  左端上方）→ 踏板（THR/BRK 24px 柱，油门在左）→ G 力（X 值盘上方、Y 竖排在左）
  → 四轮扭矩（30px 宽柱 + 数字，槽内居中，正绿负红）；
- 转向圆环中心使用 22px 数字显示带符号角度与 `°`，在圆环视觉中心对齐；
- THR / BRK 踏板（油门在左）采用与转矩一致的“柱 + 右侧数字/单位”结构，整数开度裁剪到 0–100，数字无黑色描边，下方显示 `%`；
- 速度条固定为 0–120 km/h，显示 0 / 30 / 60 / 90 / 120 五个刻度；GPS 区横向压缩到 290px，为踏板数字留出空间；
- **横向计时条**（`timing_bar`）：顶部中央，车辆 · 当前圈用时 · 第几圈；
  圈时自动取 CSV 元数据 Segment Times，可在 spec 用 `lap_seconds` 覆盖；
- **计时条**（`timing_bar`）在右上角（高度与 logo 相近）：车辆 / 车手 / 当前时间
  三段；logo 左上角（顶角边距 60px）；
- 画面其余部分完全净空。

## 快速开始

```bash
# 渲染（需要 Python + numpy/pandas/Pillow）
python render_demo.py --csv "D:\Desktop\SCUTRacingTelemetry\Data\Du.csv" --demo all --start 8 --duration 24 --video

# 自由摆放控件的布局 JSON（示例文件，改坐标/增删控件即可）
python render_demo.py --csv <AiM.csv> --demo my_layout.example.json
```

双击 `index.html` 看效果（单页：大图 + 动态预览 + 背景切换）。产物在 `output/cards/`：
三个时间点的透明底 PNG + 峰值帧灰底 JPG + 灰底动态预览 `preview.mp4`。

## 控件框架（widgets.py）

每个控件 = 一份 spec：`{"type", "x", "y", "origin", "opacity", ...控件参数}`；
`origin: tl/tc/tr/bl/bc/br`（c = 水平居中）；`card: {"title": "..."}` 给任意控件包半透明卡片。
数据层完全复用 skill 的 `scripts/telemetry.py`，本框架只负责「画」。

当前 17 种控件（v6 重构 `bottom_bar`：GPS 入带、电池双层、完整圆环、速度刻度数字；此前的 speed_flat / steer_indicator / value_stack / timing 等控件仍保留在 REGISTRY 里可随时复用）：`logo` `torque_bars`（支持 `columns: 2` 双行网格）`torque_strip`
`speed_dial` `speed_flat` `steer_indicator` `speed_number` `gps_map` `g_meter` `pedal_bars`
`value_chip`（绑定任意通道）`timecode` `bottom_strip`。

新增控件三步：继承 `Widget` → 实现 `size()/paint()` → 注册进 `REGISTRY`。
若控件绑定数据（如 steer 的 `Ave Steer`），设类属性 `DEFAULT_SOURCE`，渲染器会自动把
该通道插值到时间轴；绑定不存在的通道显示 `--` 并告警。

## 字体

`assets/fonts/`：Formula1-Display-Regular/Bold（主字体，FOM 版权，车队内部使用与自研软件
保持一致；对外发布视频如有顾虑可在 `Fonts.FILES` 一键切回 Titillium-Regular/SemiBold，文件仍在）。

## 数据配置

`configs/du.json`：Du.csv 的通道映射与量程（速度 20 / 扭矩 4 N·m，低速测试数据）。
正式比赛数据请改 `speed_max_kmh`/`torque_max_nm` 和 `steer_indicator` 的 `max_deg`。
