# 配置、四电机与时间码

配置 JSON 与默认配置递归合并；只写需要改变的字段。通道值可以是一个确切列名、按优先级排列的列名数组，或 `null`。

## 四电机空位

`motors` 的四个键固定为 FL、FR、RL、RR。每个槽位有 `active`、`torque`、`rpm`。`active: "auto"` 表示找到该位置的扭矩列才启用；`true` 明确启用，`false` 明确禁用。不存在的槽位始终保留空框。启用但缺失的数据不会显示为零。

默认左右后电机分别匹配 `L Motor Torque` / `L MOTOR SPEED` 和 `R Motor Torque` / `R MOTOR SPEED`；前电机预留 `FL Motor Torque` / `FL MOTOR SPEED`、`FR Motor Torque` / `FR MOTOR SPEED` 等名称。如果四电机数据使用其他列名，修改映射，例如：

```json
{
  "motors": {
    "FL": {"active": true, "torque": "Motor1 Torque", "rpm": "Motor1 RPM"},
    "FR": {"active": true, "torque": "Motor2 Torque", "rpm": "Motor2 RPM"},
    "RL": {"active": true, "torque": "Motor3 Torque", "rpm": "Motor3 RPM"},
    "RR": {"active": true, "torque": "Motor4 Torque", "rpm": "Motor4 RPM"}
  }
}
```

只有在用户或数据文档明确给出电机编号与车轮位置关系后，才能进行这种编号映射。不能凭编号猜测前后左右。

## 时间对齐

统一关系：`录像时间 = 数据时间 × scale + offset_seconds`。渲染时按反函数读取数据，所有仪表共用该时间变换。

1. **秒数偏移**：数据 0 秒对应录像 5.2 秒，则 `offset_seconds: 5.2`。正值会让数据在录像中晚出现；负值使数据提前出现。
2. **单个同步点**：给出一个事件的 CSV Time 和录像时间。程序计算偏移，时钟倍率为 1。
3. **两个同步点**：给出相隔较远的两个同一事件配对，程序同时计算倍率与偏移，用于线性时间漂移。不能用不同事件凑成配对。

单点示例：录像 30 fps，数据 12.5 秒对应录像 `00:00:20:15`（即 20.5 秒）：

```json
{
  "sync": {
    "timeline_fps": 30,
    "anchors": [{"data_seconds": 12.5, "video_time": "00:00:20:15"}],
    "output_start": 0,
    "show_timecode": false
  }
}
```

此时偏移为 +8 秒，输出前 8 秒不伪造数据。`timeline_fps` 是用户提供的录像时间码帧率，不是输出视频帧率；成品仍默认为 100 fps。

双点示例：

```json
{
  "sync": {
    "anchors": [
      {"data_seconds": 10, "video_time": 18},
      {"data_seconds": 610, "video_time": 618.3}
    ],
    "output_start": 18,
    "duration": 600.3,
    "show_timecode": true
  }
}
```

此例 `scale = 1.0005`、偏移 `7.995` 秒，文件第 0 帧放在录像时间轴 18 秒处，首帧显示数据 10 秒。`show_timecode` 在底部显示录像与数据秒数，仅用作校对。

锚点和非零 `offset_seconds` 不能同时使用。时间输入支持秒数、`HH:MM:SS.sss` 和整数帧率的非丢帧 `HH:MM:SS:FF`。29.97/59.94 或丢帧时间码请先转换为实际经过秒数；脚本会拒绝分号格式以免产生错误偏移。相机时间码是一天中的时刻时，应先减去片段起始时间码，转换为该录像片段内的时间；不得直接当作片段偏移。

本程序不扫描录像自动识别起步事件，也不向 MOV 写入专用 SMPTE tmcd 轨。它通过锚点实际对齐数据，并在报告中记录时间关系。没有可信锚点时状态为 `unverified_identity`，不声称同步已验证。

## 布局（layout.widgets）

默认布局为卡片舱：左上 logo、右上计时条（车辆/车手/当前时间，时间为主信息）、底部通栏信息带（从左到右：GPS 轨迹、电池、转向圆环、速度、踏板（THR 左 / BRK 右）、G 力、四轮扭矩）。每个控件是 JSON 对象：`type` 控件类型、`x`/`y` 坐标、`origin` 锚定角（`tl/tc/tr/bl/bc/br` 与垂直居中 `ml/mr`）、`opacity` 整体透明度，另有各控件自有参数（如圆环半径、柱宽、量程覆盖）。`bottom_bar` 是复合控件（高 172px），内部区块边界由其 `BASE_SECTIONS` 常量描述。定稿参数：转向 `max_deg`=160（左正右负）、扭矩 `torque_pos_max`=20 / `torque_neg_max`=10（零线固定 3:1，正绿负红，超量程封顶、数值照实）。`source` 字段可把任意 CSV 通道绑定到数值控件；绑定通道会自动插值到时间轴，缺失显示 `--` 并计入警告。

## 其他字段

`width` / `height` 支持 16:9 偶数分辨率（默认 2560×1440）；布局按比例缩放。`fps` 默认为 100。
`render_fps` 默认为 20，必须整除 `fps`：Python 只绘制这些独立 HUD 帧，FFmpeg 将其保持到成品帧率，播放速度和时长不变。`render_workers` 默认为 4，使用有界线程池并行绘制且保持输出顺序；内存不会随视频长度增长。
`alpha_codec` 默认为 `prores4444`，使用 ProRes 4444 与高精度 alpha，改善剪辑软件的透明通道兼容性。如需兼容旧流程，可设为 `qtrle`（ARGB）。
`padding_seconds.head` / `tail` 默认各为 5 秒，表示在数据内容之外额外加入空数据 HUD：完整 UI 和队标保持可见，数值显示 `--`、动态柱条为空，便于剪辑时保留叠加层画面余量。CSV 自身原有的无数据时段仍保留。设为 0 可关闭相应空数据段。

`speed_max_kmh` 默认 120；`torque_max_nm` 默认 25；`g_max` 默认 2；`trail_seconds` 默认 1.2。扭矩柱表示绝对值，功率保留正负。

`g_ball_direction` 默认 -1，将 G 球与整段拖影同时反向，形成惯性显示。默认车辆坐标为 ACC X 正值向前、ACC Y 正值向右：加速下移、刹车上移、左转右移、右转左移。显示的合加速度数值不变。设为 1 可恢复加速度向量显示；原始传感器轴方向不符时应先明确轴映射，不能仅凭图形猜测安装方向。

`max_gap_seconds` 默认 0.5。超过此间隔不跨缺失区间插值，也不将 GPS 轨迹跨长间断连线。按数据采样特性调整，不能为了隐藏丢包随意放大。

速度支持 km/h、m/s、mph 的单位转换；加速度支持 g、m/s²。扭矩需要 Nm，电机转速需要 rpm。油门默认输入已经是百分比；若源数据是 0–1、小数电压或其他单位，应先明确标定规则再扩展预处理，不直接标成百分比。

`--start` / `--duration` 覆盖对应导出区间；它们使用录像时间轴秒数。即使只导出短片，GPS 路线和刹车归一化范围也根据完整源记录生成。
