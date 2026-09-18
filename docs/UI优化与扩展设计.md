# UI 优化与扩展设计（含升级路线）

> 2026-09-15 · 针对 aim-telemetry-overlay 原 HUD（codex 版）的重设计预研与实现记录。
> 配套代码：`ui-demos/`（控件框架 + 4 个 demo），本文说明「为什么这么改」和「以后怎么长」。

> **2026-09-16 更新（选型结论）**：用户从 A/B/C/D 四个 demo 中选定 **D 卡片舱**并完成细调，
> 其余三个 demo 已删除。细调内容：
> 1. 字体切换为 **F1 Display**（Regular/Bold，TTF 取自自研软件 design-demos/fonts；F1 Display
>    无中间字重，小号标签统一用 Regular + 字距）；
> 2. 扭矩改 **2×2 网格**（`torque_bars` 新增 `columns` 参数）：前轮 FL/FR 在上、后轮 RL/RR
>    在下，与车身方位对应；
> 3. 速度改为**扁平横条卡**（新控件 `speed_flat`：大数字 + 横向进度条 + 功率，390×84），
>    放底部中央（锚定新增 `bc/tc` 水平居中原点）；
> 4. 速度卡上方新增**转向角标尺**（新控件 `steer_indicator`：水平标尺 + 指针 + 度数，
>    默认绑定 `Ave Steer`，`max_deg` 可调；⚠️ 传感器左右方向未验证，反了就在 spec 加
>    `"flip": true`——延续 skill「不凭图形猜传感器方向」的原则）；
> 5. G 力 + 踏板卡片移到右下角，GPS 卡留左下，电池条目留右上，中央完全净空。
> 控件总数 13 种；`Widget.DEFAULT_SOURCE` 类属性让控件声明的默认数据通道被渲染器自动
> 插值加载（`render_demo.py` 的 `collect_bound_sources`）。
>
> **2026-09-16 二轮细调（v3）**：速度扁平卡移回左下角；GPS 轨迹移到左侧垂直居中
> （新增 `ml/mr` 垂直居中锚定原点）；扭矩柱加宽（bar_w 38）；右下角 G 力与踏板两卡
> 放大且内容区高度统一为 118px；电池三项合并为 BATTERY 卡（新控件 `value_stack`：
> 多行「标题+值+单位」，rows 数组任意绑定通道）。控件总数 14 种。
>
> **2026-09-16 三轮细调（v4）**：速度卡加模拟元素（270° 指针小圆表）；底部三卡
> （速度/踏板/G 力）内容区统一为 106px、底边对齐；踏板柱加宽；扭矩柱加长（bar_h 78）；
> logo 放大至 h=56 并与控件边距一致（36px）；转向标尺确认**左正右负**、量程 ±160°、
> 角度值置于卡内右上；新增 **TIMING 计时卡**（`timing`：车辆/LAP/当前圈/总用时，居中，
> 与电池卡同宽），圈时由 CSV 元数据 `Segment Times` 自动解析（等分段假设，真实信标
> 圈计时属后续工作）；CSV 元数据经 `RenderContext.info` 进入控件。控件总数 15 种。
>
> **2026-09-16 四轮调整（v5，布局重构）**：底部改为**通栏信息带**（新复合控件
> `bottom_bar`）：贴满底边与左右两端、各区块等高、标题统一在最下排；区块从左到右为
> 电池（SOC/功率/电压/电流）→ 转向圆环（上 半圆 + 绿色光标 + 中心带符号度数，
> 左正右负 ±160°）→ 速度（数字+条形图）→ 四轮扭矩（条形+数字）→ 踏板 → G 力。
> GPS 卡移右上角，顶部边距加宽至 60px；新增顶部中央横向计时条（`timing_bar`：
> 车辆 · 当前圈用时 · 第几圈）。控件总数 17 种。
>
> **2026-09-16 五轮精修（v6）**：通栏信息带压掉底部空白（h 140，内容区顶 8px、
> 标题行 20px）；GPS 迷你轨迹并入信息带最左；电池改双层（SOC/VOLT 上、POWER/CURRENT 下）；
> 转向改**完整圆环**（12 刻度，绿色光标弧沿短方向绘制，中心带符号度数）；速度区重排：
> km/h 移到数值右上、条形图 0..120 六等分且每格有刻度数字；G 力区右侧改为 ACC X / ACC Y
> 上下两行（替代合成 g 值，缩小右侧空隙）。

## 1. 原 UI 的问题清单

原版渲染器是 `scripts/hud.py`：一个 121 行的脚本，所有坐标硬编码在 `make_renderer()` 里，
通过 `ScaledDraw` 做 150% 整体缩放换算。具体问题：

| 问题 | 具体位置（1920×1080 画布） |
|---|---|
| 右侧整列被占 | 速度圆环（半径约 200px）+ 上方 G 球盘（半径 130px）+ 功率/踏板条，从 y≈470 一直排到 y≈1080，占满右缘近 60% 高度 |
| 左下角 GPS 图过大 | 约 400×345px，且路线以 100% 视觉权重绘制 |
| 无透明度层级 | 描边/文字全部接近实色（α 190~255），叠加在明亮画面上非常显眼 |
| 元素不可配置 | 想去掉 G 球、放大速度、换位置都要改源码；150% 缩放换算进一步把坐标焊死 |
| 观感 | 元素之间比例失衡（速度表巨大、扭矩柱迷你），无统一字号/间距体系 |

## 2. 重设计原则

1. **中央净空**：行车画面视觉焦点在中部（车、弯道、对手），仪表只允许出现在四角与边缘；
2. **贴角锚定 + 极小占位**：每个控件声明 `origin`（贴哪个角）和自身尺寸，默认方案 A/B/C 的
   全部控件覆盖面积约为原版的 1/4~1/3；
3. **透明度分级**：结构线 α≈55-95、动态主体 α≈150-235、大数字水印 α≈100。让「看一眼」和
   「完全忽略」都成立；
4. **无面板框**（除 B/D 有意为之）：细线 + 文字浮在画面上，不做实色底板；
5. **统一字体体系**：Titillium（车队自研软件同款字体，OFL 开源），三级字号（数据 46-62、
   标注 13-17、微标 10-12），替代原版 Segoe UI Light 的松散观感；
6. **语义色不变**：绿=油门/扭矩、红=刹车/G 球、白=结构与速度，与原 skill 及车手习惯一致。

## 3. 控件框架（ui-demos/widgets.py）

核心抽象：**布局 = 控件 spec 的列表**，每个 spec 五要素：`type / x / y / origin / opacity`，
加上控件自有参数（半径、条宽、字号等）和可选 `card` 卡片包装。渲染时：

```
telemetry.prepare()  →  RenderContext（逐帧数组 + 路线缓存 + 字体）
                     →  build_layout(specs) → [Widget]
                     →  render_frame(i) = 各控件依序绘制到 1920×1080 RGBA 画布
```

- 与 `scripts/telemetry.py` 的关系：**只替换渲染层，数据层零改动**（列名解析、单位换算、
  插值、锚点对齐、功率/刹车归一化、缺失值策略全部继承）；
- 与旧 `hud.py` 的关系：`hud.py` 是「一张硬编码的图」，本框架是「一组可配置的控件」；
  `ScaledDraw` 缩放技巧被弃用，直接按 1080p 设计（`telemetry.config()` 校验 16:9，其余
  分辨率由既有 resize 逻辑处理）。

当前 11 种控件：`logo` `torque_bars` `torque_strip` `speed_dial` `speed_number` `gps_map`
`g_meter` `pedal_bars` `value_chip` `timecode` `bottom_strip`。

`value_chip` 是「任意数据」的通用出口：`{"type":"value_chip","source":"Battery Soc",
"unit":"%"}` ——渲染器自动把绑定的原始通道插值到时间轴（`render_demo.py` 的
`attach_extra_channels`），无需预处理，绑定失败显示 `--` 并告警（不伪造数据，延续 skill 原则）。

## 4. 四个 demo 的取舍（选择指南）

| | 中央占位 | 信息完整度 | 观感 | 注意点 |
|---|---|---|---|---|
| A corner | 零 | 全部保留 | 干净但四角有物 | 角落在超广角画面里可能压到边缘细节 |
| B strip | 零（底部一条） | 全部保留 | 最像 F1 转播 | 底部横带会盖住仪表台画面 |
| C watermark | 零 | 关键项（速度/功率/扭矩趋势/踏板/G/轨迹轮廓） | 最隐形 | 无精确数值读数（扭矩无数字），轨迹只做轮廓 |
| D cards | 零 | 全部 + 电池信息 | 最「软件感」，可读性最好 | 卡片底板在亮画面下最显眼 |

对比入口：`ui-demos/index.html`（切换模拟行车画面/灰底/棋盘背景评估挡视野程度）。

## 5. 选定后如何并入正式渲染管线（✅ 已完成，2026-09-16）

实际落地与下述计划一致，另有两处增强：
1. `ui-demos/widgets.py` → `scripts/widgets.py`（框架与资产同步迁移：`scripts/assets/fonts/`
   内置 Formula1 Display + Titillium，`scripts/assets/logo_white.png` 纯白 logo）；
2. v11 布局写入 `assets/default-config.json` 的 `layout.widgets`（logo / timing_bar /
   bottom_bar 三个顶层控件，GPS/电池/转向等都在 bottom_bar 内部）；
3. `hud.py` 重写为薄封装：`make_renderer(data, ts, cfg, info)` → RenderContext →
   `build_layout(cfg['layout'])` → `render_frame(i)`（尺寸自适应 resize；`DEFAULT_LAYOUT`
   兜底；`g_ball_offset` 保留供测试）；
4. `telemetry.py` 增强：`report.meta`（vehicle/racer/lap_seconds，来自 CSV 元数据
   Segment Times）；新增 `bound_channels(c)`——布局控件绑定的通道（spec `source` 或
   控件类 `DEFAULT_SOURCE`，支持列表）自动插值到时间轴，缺失显式告警；
5. `dashboard.py`：`make_renderer(data,ts,c,info=report['meta'])`，移除 font_path
   （字体已内置）；速度刻度改为「整齐步长」算法（120→0/40/80/120，80→0/20/40/60/80），
   bottom_bar 速度量程回退到 `speed_max_kmh` 配置；
6. SKILL.md 与 references/configuration.md 已同步新界面描述与 layout 说明。

1. 把 `ui-demos/widgets.py` 拷入 `scripts/`，`layouts.py` 中选定方案的 spec 写进
   `assets/default-config.json` 的新键 `"layout": {"widgets": [...]}`；
2. `hud.py` 的 `make_renderer()` 改为薄封装：构造 `RenderContext(data, cfg)` →
   `build_layout(cfg["layout"])` → `render_frame(i)`（`dashboard.py` 无需改动，它只消费
   `make_renderer` 返回的 frame 函数）；
3. 兼容旧配置：`cfg` 无 `layout` 键时回退内置默认布局；
4. 字体：`assets/fonts/`（Titillium，OFL 协议可随仓库分发）；
5. `test_telemetry.py` 不受影响（数据层零改动）；按 skill 约定跑一次 `--preview-only` 核对。

## 6. 升级路线（对应「预留以后升级」）

**v1（已实现）——JSON 布局**
布局就是 JSON；复制 `ui-demos/my_layout.example.json` 改坐标/增删控件，
`render_demo.py --demo my.json` 即可渲染。「自己摆放控件」在文件层面已经可用。

**v2（软件集成阶段）——表单 + 预设**
自研软件里做「叠加层导出」面板时：
- 预设 = A/B/C/D 四个布局一键选择；
- 通道绑定下拉框列出数据集全部 `ChannelMeta.key`（替代 skill 的「猜列名」机制，见集成预研文档 §3）；
- 量程（speed_max/torque_max）按所选数据自动建议（P95 分位数），允许手改；
- 每个 `value_chip` 的 source 就是下拉框，天然支持任意通道。

**v3（远期）——画布拖放**
控件 spec 模型与画布坐标 (1920×1080) 完全对齐，前端用 SVG/绝对定位 div 实现
所见即所得编辑器，保存成同一份 JSON 交给渲染器。控件卡片（`card`）即编辑器里的
可拖拽单元。前端实时预览与 Python 渲染共用 spec（见集成预研文档 §4 方案 3）。

**控件扩充候选**（按车队优先级建议）
- 圈速/差速卡（依赖圈计时，数据层 `LapInfo` 已在自研软件建模）
- 单圈迷你柱状图（本圈油门/刹车使用占比）
- 电池功率曲线 sparkline（`value_chip` 加 `sparkline: true` 变体即可）
- 温度组（电机/逆变器/IBGT，自动取max标红）
- 方向盘转向角指示（`Ave Steer` 已有通道）
- 单圈轨迹着色（按速度给 GPS 路线上色的变体）

## 7. 已知限制 / TODO

- Titillium 数字非严格等宽，速度快速跳动时个别数字有 ±1px 抖动；如介意可换
  `consola.ttf` 或给数字位加固定步进绘制；
- 100fps 全片渲染速度与原 skill 相同（PIL 逐帧），长视频导出慢——软件集成时建议
  默认 30/50fps（见集成预研文档 §7 性能一节）；
- `logo` 控件引用 `ui-demos/assets/logo_white.png`，并入正式管线时把该文件挪到
  `scripts/assets/` 并调整 `LOGO_PATH`；
- 深浅背景自适应（亮画面下加暗描边）目前靠固定 1px 黑描边（α≈110）解决，未做动态判断。


## 8. ✅ 卡片舱 v24 冻结版（2026-09-17 用户验收「很满意，固化现在的设计」）

经多轮迭代，界面按用户要求固化并写入 skill 正式管线。此章为当前生效的最终状态。

### 布局区块边界（1920 设计基准，渲染时按 ctx.scale 缩放）

| 区块 | 范围 | 内容 |
|---|---|---|
| gps | 0-305 | GPS 迷你轨迹 285×158，红色定位点（按时间插值），无标题 |
| battery | 305-600 | 双层两列：SOC/VOLT 上排、POWER/CURRENT 下排；值 26px，单位紧跟数值；块内左右对称 |
| steer | 600-800 | 圆环 r50、底部缺口 40°（±160° 恰 1:1），绿光标短弧，中心带符号角度；Steer Sense 优先 |
| speed | 800-1215 | 数字 80px Regular（按字形实测预留三位）+ 方正条形图（刻度 0/30/60/90/120），km/h 在条左上 |
| pedals | 1215-1371 | THR/BRK 各 24px 柱 + 右侧百分比数字（油门在左，BRK 间距 +14px） |
| gforce | 1371-1570 | 盘 r52 内圈 0.62r，圆心距左缘 PAD+37+22；X 盘上方、Y 竖排在左（字体与 X 一致 13px bold）；红点 6px、拖影 0.6s/1.2px；G-FORCE 标题居中于左右两条分割线之间（+2px） |
| motors | 1570-1920 | 四轮 30px 柱 + 数字；零线固定 3:1（正:负），正绿负红，超量程封顶、数值照实 |

顶部：logo 左上 (60,48) h56；timing_bar 右上 370×60（与 logo 等高）——时间 37px 主信息
（`draw_clock()` 手工双点冒号，F1 Display 冒号字形近似句点），车辆/车手 15px 辅助右对齐。
统一 PAD=15px；bar 高 172px；标题行距底 20px。

### 冻结版微调记录（v21–v24）

| 项 | 最终值 |
|---|---|
| 踏板顺序 | THR 左、BRK 右（标签同步），两柱间距 +14px |
| 区块顺序 | …速度 → 踏板 → G 力 → 扭矩（gforce 与 pedals 对调） |
| 分割线 | `BASE_DIVIDER_SHIFT = {"pedals": 10}`：pedal 与 gforce 之间那条线画在 1381，内容仍在 1371 边界（线与内容解耦） |
| G 力圆环 | 圆心距区块左缘 PAD+37+22（累计左移 7px） |
| G-FORCE 标题 | 居中于左右两条分割线之间 +2px（与圆环位置解耦） |
| 负扭矩 | 柱体红色（正绿负红），零线固定 3:1 |

### 分割线微调机制

`BASE_DIVIDER_SHIFT = {"pedals": 10}`：分区边界（`BASE_SECTIONS`）决定**内容**位置，
此表可让某区块右缘的**分割线**单独位移（当前 pedal|gforce 线 +10px），
用于在不移动柱/圆盘的前提下微调视觉分隔。


2560×1440（2K）@ 100fps（HUD 以 render_fps=20 绘制、8 workers 并行），
QTRLE ARGB（ProRes 4444 备选），前后 5s 空数据垫片（数值 `--`、柱条空）。

### 数据绑定（自动）

布局控件绑定的通道（控件 `DEFAULT_SOURCE`：Steer Sense、Ave Steer、电池三项）
由 `telemetry.bound_channels()` 自动插值到渲染时间轴，缺失显式告警、控件显示 `--`。

### 双份 widgets.py 的同步约定

`ui-demos/widgets.py`（设计 playground）与 `scripts/widgets.py`（正式管线）是同一文件的两份拷贝；
**改 UI 先在 ui-demos 验证，再整文件拷贝到 scripts/**，不要在 scripts 单独改。
