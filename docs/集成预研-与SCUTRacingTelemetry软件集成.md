# 集成预研：遥测叠加层渲染 × SCUTRacingTelemetry 自研软件

> 2026-09-15 · 预研结论与可行性分析。目标场景：**在自研软件里选择数据集/通道/布局，
> 导出一条透明叠加层视频，用户在剪辑软件（Premiere/剪映/达芬奇等）里叠到行车录像上**。
> 本文只做预研，不含实现。

---

## 1. 两边的现状

### 1.1 aim-telemetry-overlay skill（学长写的）

本质是「SKILL.md + Python CLI 管线」，为 Agent 按指令调用而设计：

```
dashboard.py (CLI/编排/校验)
   ├── telemetry.py  数据层：AiM CSV 解析 → 列名模糊匹配 → 单位换算 →
   │                 按 scale+offset 重采样到视频时间轴 → 功率/刹车派生 → 缺失值策略
   ├── hud.py        渲染层：PIL 逐帧画 1920×1080 RGBA（坐标硬编码，将被 ui-demos 控件框架取代）
   └── FFmpeg 管道   rgba 原始帧 → QTRLE ARGB MOV（+ 灰底 MP4 预览），逐帧 alpha/帧数/分辨率校验
```

亮点（集成时应原样继承的资产）：
- **时间对齐模型**：`录像时间 = 数据时间 × scale + offset`，支持 0/1/2 个锚点（两点可解
  时钟漂移），输出 `alignment` 报告并诚实标注 `unverified_identity`；
- **数据卫生原则**：缺失不插值（超过 max_gap 断开）、通道缺失显式 `--`、不复制后电机数据
  冒充前电机、功率缺任一电机则总功率显示缺失；
- **导出后自动校验**（`verify()`：直接解析 MOV atom 树数帧数、验分辨率/fps、抽帧验 alpha）；
- 配置即 JSON（通道映射、量程、同步锚点），与「软件里做表单」天然对齐。

局限：面向一次性任务（CLI + 新输出目录约定），无进程模型、无进度上报 API、渲染层不可配置
（正在由 `ui-demos/` 解决，见《UI优化与扩展设计.md》）。

### 1.2 SCUTRacingTelemetry 自研软件（Tauri 2 + React 18）

按 2026-09 仓库状态：

- **数据链路已通**：XRK 经 `aim-ffi`（AiM 官方 DLL, libloading）解析 → `cache-core` 落盘
  （manifest + raw blob + 金字塔降采样）→ IPC（specta 生成 TS 类型）→ 前端 uPlot 消费。
  通道模型：`ChannelMeta {key, name, unit, source, sample_rate_hz}` +
  `ChannelSeries {times: Vec<f64>, values: Vec<f32>}`（NaN=缺失）；
- **IPC 边界只有降采样包络**（SXK1 min/max 帧）和 `cursor_values`；**全分辨率原始数据只在
  磁盘缓存 raw blob 里**，前端拿不到——这是叠加层渲染（需要逐帧全精度）的第一个缺口；
- **视频/overlay/导出全部为零**：无 ffmpeg 依赖、无 sidecar、`export_csv` 是 stub
  （协议 `Request::ExportCsv` 已预留；施工手册裁决「格式化在 core、文件选择/落盘在 Tauri 边界」）；
- **面板架构**：`src/panels/registry.ts` 的 `PanelDef` 注册表（注意 D16 决策：dockview 将被
  固定三栏 Grid 取代，新面板不要耦合 dockview API）；
- **设计体系**：tokens.css（F1 风格，红 #E10600）+ Titillium 字体 + 通道固定色板；
- 质量门禁 `tests/tooling/check.ps1`（clippy -D warnings、eslint --max-warnings 0 是硬约束）。

---

## 2. 目标功能拆解

| 需求 | 现成度 | 缺口 |
|---|---|---|
| R1 选择数据文件 | ✅ 导入/数据集流程完整 | 无 |
| R2 选择通道/数据 → 控件 | ⚠️ skill 有 channels 映射机制 | 软件里应做成「勾选通道 → 控件绑定」，映射逻辑可退役 |
| R3 布局（位置/大小） | ✅ ui-demos 控件 spec 模型 | 软件内编辑器（v2 表单 / v3 拖放） |
| R4 导出透明视频 | ⚠️ skill 的 Python 管线完整 | 软件内没有调用通道（sidecar/打包/进度） |
| R5 与录像时间对齐 | ⚠️ skill 锚点机制完整 | 缺少「选择录像文件→取时间码/波形」的 UX；`align.rs` 已留签名 |

## 3. 关键技术决策点

### 3.1 全精度数据怎么给渲染器（最重要的架构缺口）

软件 IPC 只给包络，渲染需要逐帧全精度。三条路：

- **A（推荐）新增 Tauri 命令 `export_series`**：按 `channel key + 时间区间` 从 cache raw blob
  （memmap）读全精度 `ChannelSeries`，序列化写临时文件（NPZ 或自定义二进制）交给渲染器。
  与现有 `window_series` 同层，复用 `CacheRoot` 读取路径，不暴露内部目录结构。
- B 让 Python 侧直读 `.cache/datasets/<hash>/`——耦合缓存内部格式（manifest/raw 布局将来
  可能变，cache-core 尚无稳定版本承诺），不推荐。
- C 渲染走 `cursor_values` 式 RPC 逐帧取数——IPC 往返次数爆炸，否决。

数据量级评估：FS 短程 90s × 20Hz × 80 通道 ≈ 1.4MB CSV，全精度导出毫无压力；
耐力赛 2-3h × 100Hz × 20 个渲染通道 ≈ 每通道 200 万样本 × 12B ≈ 24MB/通道，二进制传输
+流式读取仍是小数。**瓶颈不在数据量，在帧渲染速度**（见 §7）。

### 3.2 渲染器放哪：三条路线

| 路线 | 说明 | 优点 | 代价 | 结论 |
|---|---|---|---|---|
| **① Python sidecar**（短期推荐） | skill 管线打包成独立 exe（PyInstaller onedir + 静态 ffmpeg），软件以子进程调用，stdio JSON lines 通信（进度/日志） | skill 代码 90% 复用（telemetry.py 原样、hud.py 换 widgets.py）、迭代最快、QTRLE/ProRes 编码现成、可独立使用和调试 | 包体积 +120~180MB（Python 运行时 + numpy/pandas + ffmpeg）；跨进程生命周期管理；发布链路多一件制品 | **M1 就做**，风险最低 |
| ② Rust 原生渲染 | 用 tiny-skia + ab_glyph 重写控件绘制，帧管道喂 ffmpeg（`ffmpeg-sidecar` crate 或系统 ffmpeg） | 单二进制、无 Python、与 check.ps1 门禁同栈 | 重写全部 11 类控件绘制 + 时间对齐/插值在 Rust 再实现一遍（约 2-4 周量级）；渲染结果需要与 Python 版逐像素对齐否则用户体验分裂 | M3+ 视 sidecar 痛点再立项；`widgets.py` 的 spec 模型即移植接口文档 |
| ③ Web 前端渲染 | React 控件组件 + OffscreenCanvas 逐帧 → WebCodecs 编码 | 布局编辑器与预览天然同构（所见即所得）；无打包增量 | WebCodecs 编不了 ProRes/QTRLE；VP9 alpha 需手工拆 alpha 平面 + webm-muxer，剪辑软件对 WebM alpha 支持差；Canvas 文本渲染与 PIL 有差异，成品要再对齐 | 不作为导出引擎；其 React 控件可降级为**布局编辑器的实时预览**（§5 v3） |

**推荐组合**：① 起步 + ③ 的编辑器形态 + ② 作为远期选项。skill 与软件的关系从「集成」变为
「同一套 spec，两个宿主」：spec JSON 是唯一契约。

### 3.3 透明视频格式（交付给剪辑软件）

| 格式 | 剪辑软件支持 | 大小 | 现成编码 |
|---|---|---|---|
| QTRLE ARGB MOV | Premiere ✅ 达芬奇 ✅ Vegas ✅ FCP ✅ | 极大（1080p100 一小时 >200GB） | skill 现状，已验证 |
| **ProRes 4444 (+alpha) MOV** | 同上全 ✅，行业交付标准 | 大（约为 QTRLE 的 1/3~1/2） | ffmpeg `prores_ks:pix_fmt=yuva444p10le`，本机 ffmpeg 已含 |
| WebM VP9 alpha | 剪辑软件基本 ❌（浏览器 ✅） | 小 | 已验证本机 libvpx alpha 编码**不可靠**，放弃 |
| PNG 序列 | 全 ✅ | 天文数字 | 仅作兜底 |

**结论**：软件集成后默认交付 **ProRes 4444**（选项保留 QTRLE），导出 fps 默认降到与录像
一致（30/50/60），除非用户明确要 100fps。100fps QTRLE 全片仅适合短片。

### 3.4 时间对齐的软件化 UX

skill 的锚点模型直接变成表单：
- 无锚点：默认 0 偏移，报告标 `unverified_identity`（UI 上黄条提示「未验证同步」）；
- 单锚点：用户在录像里看到一个明确事件（如起步绿灯），输入录像时间码 + 从数据里点选同一
  事件（软件的游标 cursorT 可以直接当数据时间选择器！）——这比 skill 的纯文本交互强得多；
- 双锚点：同上两次，自动解 scale/offset，解漂移；
- 远期：`estimate_offset` stub（main.rs 已预留命令名）→ 导入录像音轨与数据派生信号
  （如电机转速 vs 引擎音pitch、加速度 vs 画面抖动）自动估计偏移。此为独立研究项，不阻塞 M1-M3。

---

## 4. 软件内 UI 集成路径

1. **面板**：`registry.ts` 加 `overlay-exporter` 面板（三步：PanelDef → AppShell addPanel →
   zustand 状态字段）。面板职责：选数据集（复用当前打开的 dataset）、勾选通道、选布局预设、
   设置锚点、导出按钮 + 进度条。**不要耦合 dockview API**（D16：将被固定三栏 Grid 取代）。
2. **状态**：`appStore` 加 `overlayConfig`（控件 spec 列表 + 同步参数 + 输出格式），与
   skill 的 config JSON 字段一一对应，序列化后即是 sidecar 的 `--config` 输入。
3. **进度**：渲染是分钟级任务，复用导入任务的轮询模式（`import_status` 250ms 轮询 →
   sidecar 同样暴露 `status` 行协议，前端复用 ImportProgressBar 的交互模式）。
4. **视觉**：面板与预览全部走 tokens.css 令牌 + Titillium；导出的叠加层本身保持 HUD 白色
   语义（叠加层是给观众看的，不是软件 UI 的一部分，不需要跟随软件主题）。
5. **命令边界**：遵守施工手册裁决——文件对话框（`tauri-plugin-dialog`）与输出落盘在 Tauri
   层做，渲染器只拿「输入数据文件路径 + config JSON + 输出目录」。capabilities 目前为空，
   新增 dialog/fs 插件时要补权限配置。

## 5. 分阶段落地建议（对齐施工手册 Step 11/12 导出里程碑）

| 里程碑 | 内容 | 验收 |
|---|---|---|
| **M1 POC（1-2 天）** | ① `export_series` 命令（数据集全精度通道→临时二进制）；② skill 打包 sidecar POC（PyInstaller + ffmpeg）；③ 命令行打通：软件选 XRK → 出 10s 透明 MOV | 用 AGX.xrk 走通全链，MOV 通过 skill 自带 `verify()` |
| **M2 面板（3-5 天）** | overlay-exporter 面板：布局预设 A/B/C/D 单选 + 通道映射表单 + fps/格式选择 + 进度条 + 输出目录 | 导出 1 分钟全片；UI 过 eslint/tsc 门禁 |
| **M3 对齐与任意数据（3-5 天）** | 锚点表单（配合游标选点）；value_chip 任意通道绑定下拉；量程自动建议 | 双锚点漂移用例误差 < 1 帧 |
| **M4 布局编辑器（1-2 周）** | 画布拖放（spec JSON v3）；React 控件实时预览（方案③的预览部分） | 所见即所得与导出结果肉眼一致 |
| **M5 Rust 化评估** | 视 sidecar 的体积/启动/维护痛点决定是否启动方案② | —— |

## 6. 打包与工程细节（sidecar 路线）

- `tauri.conf.json` 增加 `bundle.externalBin`（现无先例）或把 PyInstaller onedir 整个塞进
  `bundle.resources`（推荐后者：不用处理 target triple 后缀）；NSIS 打包体积预计 +150MB；
- ffmpeg：静态版随 sidecar 分发（imageio-ffmpeg 的构建为 LGPL，随包分发需在关于页附
  LGPL 声明与源码链接；或打包时改用用户系统 ffmpeg，作为可配置项）；
- Python 运行时：PyInstaller onedir（启动 <1s）优于 onefile（每次解压，启动 3-8s）；
  numpy/pandas 体积可用 `--exclude-module` 裁剪（pandas 在渲染链路里仅 telemetry.py 用到，
  若 Rust 化前想瘦身可把 telemetry.py 的 pandas 依赖换掉，约半天工作量）；
- 通信协议：stdio JSON lines（`{"event":"progress","frames":123,"total":720}`），stderr 进日志；
  Windows 下注意子进程 CREATE_NO_WINDOW 防止弹黑框；
- 缓存与临时文件：中间数据文件放 `app_cache_dir()/overlay-tmp/`，导出完成即删。

## 7. 性能预估（决定默认参数）

- PIL 渲染 1080p 单帧 ≈ 15-40ms（控件数量敏感，B 方案复合控件最重）；100fps 长片意味着
  渲染时间 ≈ 2-4× 视频时长——可用但煎熬；
- ProRes 4444 编码吞吐 ≈ 60-120fps（1080p，本机 ffmpeg），不是瓶颈；
- **默认建议**：fps 跟随录像（30/50/60）；整段导出走「边渲染边编码」流式（skill 已是此模式）；
  进度条必须做（用户感知的等待 = max(渲染, 编码)，不再有假死观感）；
- M5 Rust 化的收益主要在渲染（tiny-skia 单帧 <2ms，10-20× 提速），这是它最硬的理由。

## 8. 风险清单

| 风险 | 等级 | 缓解 |
|---|---|---|
| 全精度导出命令与 cache 内部结构耦合 | 中 | `export_series` 只经 CacheRoot 公开 API |
| PyInstaller + 杀毒软件误报 | 中 | onedir + 签名；或 embeddable python + 脚本目录 |
| 双渲染实现（编辑器预览 vs Python 导出）像素不一致 | 中 | spec 是唯一契约；预览标注「示意」，以导出为准；M4 后做像素回归样本 |
| 100fps 默认导致用户导出一小时视频等半小时 | 高（体验） | 默认 fps 跟随录像 + 预估导出时长显示 |
| F1 Display 字体版权 | 低 | 用户已选定 F1 Display 作叠加层主字体（与自研软件一致，FOM 版权仅限车队内部使用）；ui-demos 的 `Fonts.FILES` 保留 Titillium（OFL）作为一键回退 |
| skill 的 SRC/XRK 差异（skill 只吃 CSV） | 低 | 软件侧数据经 `export_series` 中转，渲染器不再直接解析 XRK；skill 原样保留独立可用 |

## 9. 结论

- **可行性：高**。数据链路（导入/缓存/通道模型）与渲染管线（skill）各自完整且互补，
  缺的只是 `export_series` 一座桥和一个 sidecar 宿主；两套代码唯一的契约是
  「控件 spec JSON + 通道全精度数据文件」，两者都已存在或已在 ui-demos 中原型化；
- **推荐路径**：M1 sidecar POC → M2 面板 → M3 锚点/任意数据 → M4 拖放编辑器 →
  M5 视情况 Rust 化；
- 顺带收益：ui-demos 控件框架并入 skill 后，skill 本身也获得布局可配置能力，
  软件未上线前团队就能产出成品级叠加视频。
