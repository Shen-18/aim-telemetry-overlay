"""渲染 UI demo 预览。

数据链路完全复用 skill 的 telemetry.py（列名解析、插值、时间对齐、
功率计算、刹车归一化），只在渲染层换成 widgets.py 的控件框架。

用法：
  python render_demo.py --csv <AiM.csv> --demo all|cards
                        [--config configs/du.json] [--start 8] [--duration 24]
                        [--video]

输出（output/<demo>/ 下）：
  frame_1/2/3.png   三个时间点的透明底 PNG（真实 alpha，index.html 里叠在模拟背景上）
  showcase.jpg      峰值速度帧的灰底 JPG（快速查看）
  preview.mp4       --video 时生成，灰底 H.264 动态预览

说明：正式交付走 skill 的 QTRLE ARGB MOV 管线（带逐帧 alpha 校验）。

extra_channels 机制：config 里列出的任意 CSV 通道都会被插值到同一时间轴，
供 value_chip 之类控件绑定；布局里控件声明的 source（含控件类默认值）也会自动补齐。
CSV 元数据（Vehicle、Segment Times）会传入渲染上下文供计时类控件使用。
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

HERE = Path(__file__).resolve().parent
SKILL_SCRIPTS = HERE.parent / "scripts"
sys.path.append(str(SKILL_SCRIPTS))  # telemetry 在 scripts；widgets 用本目录的

from telemetry import config, load_csv, prepare  # noqa: E402
import layouts  # noqa: E402
import widgets  # noqa: E402


def ffmpeg_path() -> str:
    try:
        import imageio_ffmpeg
        return imageio_ffmpeg.get_ffmpeg_exe()
    except ImportError:
        found = __import__("shutil").which("ffmpeg")
        if not found:
            raise SystemExit("需要 ffmpeg：pip install imageio-ffmpeg 或安装 ffmpeg 到 PATH")
        return found


def parse_segment_time(text) -> float:
    """AiM 'Segment Times'（如 '1:17.000'）→ 77.0；解析失败返回 0。"""
    try:
        parts = str(text).strip().split(":")
        if len(parts) == 2:
            return int(parts[0]) * 60 + float(parts[1])
        return float(text)
    except (ValueError, AttributeError):
        return 0.0


def attach_extra_channels(data: dict, csv_path: Path, keys: list[str]) -> tuple[list[str], dict]:
    """把额外原始通道插值到演示时间轴上（『任意通道皆可成为控件』）。

    同时返回 CSV 元数据（vehicle、Segment Times 等），供计时类控件使用。
    """
    if not keys:
        return [], {}
    df, meta, _ = load_csv(csv_path)
    query = np.asarray(data["Data Time"], dtype=float)
    missing = []
    for key in keys:
        if key in data:
            continue
        col = next((c for c in df.columns if c.lower() == key.lower()), None)
        if col is None:
            missing.append(key)
            continue
        series = df[["Time", col]].dropna()
        data[key] = np.interp(query, series["Time"], series[col],
                              left=np.nan, right=np.nan)
    return missing, meta


def collect_bound_sources(demo_ids: list[str]) -> list[str]:
    """收集布局里控件绑定的数据键（spec 的 source 或控件类默认值），自动补充插值。"""
    keys = []
    for demo_id in demo_ids:
        for spec in layouts.DEMOS[demo_id]["widgets"]:
            wtype = spec["type"]
            source = spec.get("source")
            if source is None and wtype in widgets.REGISTRY:
                source = widgets.REGISTRY[wtype].DEFAULT_SOURCE
            for item in (source if isinstance(source, (list, tuple)) else [source]):
                if item and item not in keys:
                    keys.append(item)
    return keys


def gray_background(im: Image.Image) -> Image.Image:
    bg = Image.new("RGBA", im.size, (82, 90, 99, 255))
    bg.alpha_composite(im)
    return bg.convert("RGB")


def encode_video(ff: str, frames, path: Path, size: tuple[int, int], fps: int) -> None:
    args = [ff, "-y", "-hide_banner", "-loglevel", "error",
            "-f", "rawvideo", "-pixel_format", "rgb24",
            "-video_size", f"{size[0]}x{size[1]}", "-framerate", str(fps), "-i", "pipe:0", "-an",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20", "-pix_fmt", "yuv420p",
            "-movflags", "+faststart"]
    args += [str(path)]
    with path.with_suffix(".log").open("w", encoding="utf-8") as log:
        p = subprocess.Popen(args, stdin=subprocess.PIPE, stderr=log)
        try:
            for frame in frames:
                p.stdin.write(frame.tobytes())
            p.stdin.close()
            if p.wait() != 0:
                raise RuntimeError(f"编码失败，见 {path.with_suffix('.log')}")
        except BaseException:
            p.kill()
            p.wait()
            raise


def render_demo(demo_id: str, data: dict, cfg: dict, info: dict, out_root: Path,
                video: bool) -> dict:
    spec = layouts.DEMOS[demo_id]
    ctx = widgets.RenderContext(data, cfg, info=info)
    ws = widgets.build_layout(spec, ctx)
    out = out_root / demo_id
    out.mkdir(parents=True, exist_ok=True)

    total = ctx.frame_count
    speeds = np.asarray(data["VehSpd"], dtype=float)
    peak = int(np.nanargmax(speeds)) if np.any(np.isfinite(speeds)) else total // 2
    stills = sorted({int(total * 0.15), peak, int(total * 0.85)})

    files = []
    for n, idx in enumerate(stills, start=1):
        im = widgets.render_frame(ctx, ws, idx)
        p = out / f"frame_{n}.png"
        im.save(p)
        files.append(p.name)
        if idx == peak:
            gray_background(im).save(out / "showcase.jpg")

    if video:
        ff = ffmpeg_path()
        begin = max(0, peak - 4 * cfg["fps"])
        end = min(total, begin + 8 * cfg["fps"])
        indices = np.arange(begin, end, max(1, cfg["fps"] // 30))
        encode_video(ff, (gray_background(widgets.render_frame(ctx, ws, int(i)))
                          for i in indices), out / "preview.mp4",
                     (ctx.width, ctx.height), 30)
        files.append("preview.mp4")

    return {"id": demo_id, "name": spec["name"], "desc": spec["desc"],
            "files": files, "peak_frame": peak, "total_frames": total}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", required=True)
    ap.add_argument("--config", default=str(HERE / "configs" / "du.json"))
    ap.add_argument("--demo", default="all", help="all | cards | <布局JSON路径>")
    ap.add_argument("--out", default=str(HERE / "output"))
    ap.add_argument("--start", type=float, default=None, help="录像时间轴起点（秒）")
    ap.add_argument("--duration", type=float, default=None, help="导出时长（秒）")
    ap.add_argument("--video", action="store_true", help="生成灰底 mp4 动态预览")
    args = ap.parse_args()

    if args.demo == "all":
        demo_ids = list(layouts.DEMOS)
    elif args.demo in layouts.DEMOS:
        demo_ids = [args.demo]
    else:
        layout_path = Path(args.demo)
        spec = json.loads(layout_path.read_text(encoding="utf-8-sig"))
        layouts.DEMOS[spec["id"]] = spec
        demo_ids = [spec["id"]]

    cfg = config(args.config)
    bound = collect_bound_sources(demo_ids) + list(cfg.pop("extra_channels", []))
    data, _, report = prepare(args.csv, cfg, args.start, args.duration)
    missing, meta = attach_extra_channels(data, Path(args.csv), bound)
    for key in missing:
        print(f"警告: 控件绑定的通道 {key} 不在 CSV 中，相关控件将显示 --")

    info = {"vehicle": meta.get("Vehicle", ""),
            "racer": meta.get("Racer", ""),
            "lap_seconds": parse_segment_time(meta.get("Segment Times", 0))}

    out_root = Path(args.out)
    manifest = [render_demo(d, data, cfg, info, out_root, args.video)
                for d in demo_ids]

    # demos.js 供 index.html 以 file:// 直接加载（fetch 在 file:// 下会被浏览器拦截）
    js = out_root / "demos.js"
    js.write_text("window.DEMOS = " + json.dumps(manifest, ensure_ascii=False, indent=2) + ";",
                  encoding="utf-8")
    (out_root / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print("完成 ->", out_root)
    for m in manifest:
        print(f"  {m['id']}: {len(m['files'])} 个文件")


if __name__ == "__main__":
    main()
